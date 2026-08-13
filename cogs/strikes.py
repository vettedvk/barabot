"""
Strikes cog — light disciplinary tracking (Officers / Bot Admins).

  /strike  <member> <reason>  — issue a strike. A strike stays "active" for
                                config.STRIKE_EXPIRY_DAYS days. Reaching
                                STRIKE_DEMOTE active strikes drops the member one
                                ladder rank; STRIKE_REMOVE discharges them.
  /strikes <member>           — list a member's active strikes.
  /clear_strike <member>      — wipe a member's active strikes.

Strikes expire simply by ageing out of the active window — there's no cleanup
job; old rows just stop counting (and stay as history in Notion).
"""

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

import audit_log
import config
import notion_service as ns
import role_service
import util
from rank_engine import AUTO_LADDERS

log = logging.getLogger(__name__)


def _configured() -> bool:
    return bool(os.environ.get("NOTION_STRIKES_DB_ID"))


class StrikesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── consequences ─────────────────────────────────────────────────────

    async def _demote(self, member: discord.Member) -> str:
        page = await ns.get_fleet_member_by_discord_id(str(member.id))
        if page is None:
            return "⚠️ Hit the demotion threshold but no ladder roster row was found — demote manually."
        s = ns.extract_member_stats(page["properties"])
        ladder = AUTO_LADDERS.get(s["detachment"])
        if not ladder or s["rank"] not in ladder or ladder.index(s["rank"]) == 0:
            return ("⚠️ Hit the demotion threshold but couldn't auto-demote "
                    "(already at the bottom, or an appointed rank) — Command should act.")
        new_rank = ladder[ladder.index(s["rank"]) - 1]
        await ns.set_member_rank(page["id"], new_rank)
        await role_service.apply_rank_and_company(
            member, s["detachment"], new_rank, old_rank=s["rank"], lorename=s["lorename"])
        return f"⬇️ **Demoted** to **{new_rank}** (3 active strikes)."

    async def _remove(self, member: discord.Member) -> str:
        pages = await ns.get_members_by_discord_id(str(member.id))
        removable = [p for p in pages
                     if ns.extract_member_stats(p["properties"])["status"] in ("Active", config.LOA_STATUS)]
        lorename = ns.extract_member_stats(removable[0]["properties"])["lorename"] if removable else ""
        for page in removable:
            await ns.discharge_member(page["id"])
        await role_service.apply_discharge_roles(member, lorename=lorename)
        return "⛔ **Removed** from House Baratheon — discharged (5 active strikes)."

    # ── /strike ──────────────────────────────────────────────────────────

    @app_commands.command(name="strike", description="[Officer] Issue a disciplinary strike.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="Member to strike", reason="Why the strike is being issued")
    async def strike(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not util.is_officer(interaction.user):
            await interaction.response.send_message("❌ Officers / Bot Admins only.", ephemeral=True)
            return
        if not _configured():
            await interaction.response.send_message(
                "❌ Strikes database not configured (set NOTION_STRIKES_DB_ID).", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await ns.create_strike(str(member.id), reason, str(interaction.user))
        active = await ns.get_active_strikes(str(member.id), config.STRIKE_EXPIRY_DAYS)
        count = len(active)

        action = ""
        if count >= config.STRIKE_REMOVE:
            action = await self._remove(member)
        elif count == config.STRIKE_DEMOTE:
            action = await self._demote(member)

        try:
            await member.send(
                f"⚠️ You've received a **strike** in House Baratheon.\n"
                f"**Reason:** {reason}\n"
                f"**Active strikes:** {count}/{config.STRIKE_REMOVE}"
                + (f"\n\n{action}" if action else "")
            )
        except discord.HTTPException:
            pass

        msg = f"✅ Strike issued to {member.mention}. **Active strikes: {count}/{config.STRIKE_REMOVE}.**"
        if action:
            msg += f"\n{action}"
        await interaction.followup.send(msg, ephemeral=True)

        await audit_log.log_event(
            self.bot,
            title="⚠️ Strike issued",
            color=discord.Color.orange(),
            fields=[
                ("Member", f"{member.mention} (`{member.id}`)", True),
                ("Issued by", f"{interaction.user.mention}", True),
                ("Active strikes", f"{count}/{config.STRIKE_REMOVE}", True),
                ("Reason", reason[:1024], False),
                ("Action", action or "—", False),
            ],
        )

    # ── /strikes ─────────────────────────────────────────────────────────

    @app_commands.command(name="strikes", description="[Officer] View a member's active strikes.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="Member to check")
    async def strikes(self, interaction: discord.Interaction, member: discord.Member):
        if not util.is_officer(interaction.user):
            await interaction.response.send_message("❌ Officers / Bot Admins only.", ephemeral=True)
            return
        if not _configured():
            await interaction.response.send_message(
                "❌ Strikes database not configured (set NOTION_STRIKES_DB_ID).", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        active = await ns.get_active_strikes(str(member.id), config.STRIKE_EXPIRY_DAYS)

        embed = discord.Embed(
            title=f"⚠️ Active strikes — {member.display_name}",
            color=discord.Color.orange(),
        )
        if not active:
            embed.description = "No active strikes. ✅"
        else:
            lines = []
            for p in active:
                props = p["properties"]
                reason = ns.get_prop_text(props, "Reason") or "—"
                by = ns.get_prop_text(props, "Issued By") or "—"
                when = (props.get("Timestamp", {}).get("date") or {}).get("start", "")[:10]
                lines.append(f"• **{reason}** — by {by} ({when})")
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"{len(active)}/{config.STRIKE_REMOVE} active "
                                  f"• expire after {config.STRIKE_EXPIRY_DAYS} days")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /clear_strike ────────────────────────────────────────────────────

    @app_commands.command(name="clear_strike", description="[Officer] Clear a member's active strikes.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="Member whose active strikes to clear")
    async def clear_strike(self, interaction: discord.Interaction, member: discord.Member):
        if not util.is_officer(interaction.user):
            await interaction.response.send_message("❌ Officers / Bot Admins only.", ephemeral=True)
            return
        if not _configured():
            await interaction.response.send_message(
                "❌ Strikes database not configured (set NOTION_STRIKES_DB_ID).", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        cleared = await ns.clear_active_strikes(str(member.id), config.STRIKE_EXPIRY_DAYS)
        await interaction.followup.send(
            f"✅ Cleared **{cleared}** active strike(s) for {member.mention}.", ephemeral=True)

        await audit_log.log_event(
            self.bot,
            title="🧽 Strikes cleared",
            color=discord.Color.green(),
            fields=[
                ("Member", f"{member.mention} (`{member.id}`)", True),
                ("Cleared by", f"{interaction.user.mention}", True),
                ("Count", str(cleared), True),
            ],
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StrikesCog(bot))
