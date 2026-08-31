"""
Weekly missing-field sweep — every Saturday, DM members whose Notion roster
entry is missing a field (Roblox ID, Roblox username, or lore name) with a button
to fill it in (views/profile_completion_panel). This is a gentle weekly reminder,
NOT an immediate ping on bulk role changes (those are handled silently by the
Discord-authority sync).

Anything the bot can't chase directly is escalated to the house lead
(config.HOUSE_LEAD_DM_ID) in one summary DM:
  • rows with a BLANK Discord User ID — can't be tied to a member, so a human
    must reconcile them by hand;
  • members whose DMs are closed (unreachable), so the reminder didn't land.

A ruler can trigger a run on demand with /run_profile_sweep (dry-run by default).
"""

import asyncio
import logging
from datetime import datetime, time as dtime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import notion_service as ns
import util
from views.profile_completion_panel import ProfileCompletionView, missing_fields

log = logging.getLogger(__name__)

_SATURDAY = 5  # datetime.weekday(): Mon=0 … Sat=5, Sun=6

_FIELD_LABEL = {
    "roblox_id": "Roblox ID",
    "roblox_username": "Roblox username",
    "lorename": "lore name",
}


class ProfileSweepCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.weekly_sweep.start()

    def cog_unload(self):
        self.weekly_sweep.cancel()

    @tasks.loop(time=dtime(hour=17, minute=0, tzinfo=timezone.utc))
    async def weekly_sweep(self):
        # The loop fires daily at 17:00 UTC; only actually run on Saturdays.
        if datetime.now(timezone.utc).weekday() != _SATURDAY:
            return
        try:
            await self.run_sweep(dry_run=False)
        except Exception as exc:
            log.warning("weekly_sweep skipped: %s", exc)

    @weekly_sweep.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def run_sweep(self, dry_run: bool = False) -> dict:
        """One sweep pass. Returns a summary dict. dry_run sends no DMs."""
        result = {"dmed": 0, "unreachable": [], "blank_id": [], "checked": 0}
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            return result

        pages = await ns.get_all_active_members()
        by_uid: dict[str, list[dict]] = {}
        for page in pages:
            stats = ns.extract_member_stats(page["properties"])
            uid = stats["discord_user_id"]
            if uid:
                by_uid.setdefault(uid, []).append(stats)
            else:
                # No Discord ID → can't DM anyone; escalate to the house lead.
                label = stats["lorename"] or stats["roblox_username"] or "(unknown)"
                result["blank_id"].append(label)

        for uid, stats_list in by_uid.items():
            needed = missing_fields(stats_list)
            if not needed:
                continue
            result["checked"] += 1
            label = stats_list[0]["lorename"] or stats_list[0]["roblox_username"] or f"`{uid}`"
            gm = guild.get_member(int(uid)) if uid.isdigit() else None
            if gm is None:
                result["unreachable"].append(f"{label} (`{uid}`) — not in server")
                continue
            if dry_run:
                result["dmed"] += 1
                continue
            try:
                await gm.send(embed=self._member_embed(needed), view=ProfileCompletionView())
                result["dmed"] += 1
            except (discord.Forbidden, discord.HTTPException):
                result["unreachable"].append(f"{gm} (`{uid}`) — DMs closed")
            await asyncio.sleep(0.5)

        if not dry_run:
            await self._report_to_house_lead(result)
        return result

    def _member_embed(self, needed: list[str]) -> discord.Embed:
        fields = ", ".join(_FIELD_LABEL.get(k, k) for k in needed)
        return discord.Embed(
            title="⚡ House Baratheon — complete your roster profile",
            description=(
                "Our records are missing some of your details:\n"
                f"**{fields}**\n\n"
                "Press the button below to fill them in — it only takes a moment. "
                "Ours is the Fury."
            ),
            color=discord.Color.dark_gold(),
        )

    async def _report_to_house_lead(self, result: dict):
        if not result["unreachable"] and not result["blank_id"]:
            return
        lead = self.bot.get_user(config.HOUSE_LEAD_DM_ID)
        if lead is None:
            try:
                lead = await self.bot.fetch_user(config.HOUSE_LEAD_DM_ID)
            except discord.HTTPException:
                return

        embed = discord.Embed(
            title="🗒️ Weekly profile sweep — needs your attention",
            description=(
                f"Reminders sent: **{result['dmed']}**\n"
                "The entries below couldn't be chased automatically."
            ),
            color=discord.Color.orange(),
        )
        if result["unreachable"]:
            embed.add_field(
                name=f"⚠️ Unreachable members ({len(result['unreachable'])})",
                value=("\n".join(f"• {x}" for x in result["unreachable"]))[:1024],
                inline=False)
        if result["blank_id"]:
            embed.add_field(
                name=f"❓ Rows with no Discord ID ({len(result['blank_id'])})",
                value=("\n".join(f"• {x}" for x in result["blank_id"]))[:1024],
                inline=False)
        try:
            await lead.send(embed=embed)
        except discord.HTTPException:
            pass

    @app_commands.command(
        name="run_profile_sweep",
        description="[Ruler] Run the weekly missing-field sweep now (dry-run by default).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(dry_run="Preview only (default). Set False to actually DM members.")
    async def run_profile_sweep(self, interaction: discord.Interaction, dry_run: bool = True):
        if not util.is_ruler(interaction.user):
            await interaction.response.send_message(
                "❌ Heir / Lady / Lord of Storm's End only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        result = await self.run_sweep(dry_run=dry_run)
        mode = "🔎 DRY RUN — no DMs sent" if dry_run else "✅ Sweep run"
        msg = (
            f"**{mode}**\n"
            f"Members with missing fields: **{result['checked']}**\n"
            f"{'Would DM' if dry_run else 'DMed'}: **{result['dmed']}**\n"
            f"Unreachable: **{len(result['unreachable'])}**\n"
            f"Blank-Discord-ID rows: **{len(result['blank_id'])}**"
        )
        if result["unreachable"]:
            msg += "\n\n__Unreachable:__\n" + "\n".join(f"• {x}" for x in result["unreachable"][:20])
        if result["blank_id"]:
            msg += "\n\n__Blank Discord ID:__\n" + "\n".join(f"• {x}" for x in result["blank_id"][:20])
        await interaction.followup.send(msg[:1990], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileSweepCog(bot))
