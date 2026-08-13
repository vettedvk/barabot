"""
LOA cog — posts the persistent LOA request panel and provides /end_loa to
restore a member when their leave is over.

Requesting LOA is a panel button (see views/loa_panel.py); this cog only
(re)posts that panel and handles ending an approved LOA. Approving/denying a
request is done with the buttons on the review embed (views/loa_review.py).
"""

import logging
from datetime import date, time as dtime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import audit_log
import config
import notion_service as ns
import util
from views.loa_panel import LOAPanelView

log = logging.getLogger(__name__)


class LOACog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.loa_expiry_check.start()

    def cog_unload(self):
        self.loa_expiry_check.cancel()

    # ── /setup_loa_panel ─────────────────────────────────────────────────

    @app_commands.command(
        name="setup_loa_panel",
        description="[Admin] Post the persistent LOA (Leave of Absence) request panel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def setup_loa_panel(self, interaction: discord.Interaction):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if config.CHANNEL_LOA_PANEL == 0:
            await interaction.followup.send(
                "❌ LOA panel channel not configured (set CHANNEL_LOA_PANEL).",
                ephemeral=True,
            )
            return

        channel = self.bot.get_channel(config.CHANNEL_LOA_PANEL)
        if channel is None:
            await interaction.followup.send(
                "❌ LOA panel channel not found (check CHANNEL_LOA_PANEL).",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="House Baratheon — Leave of Absence",
            description=(
                "Need time away from service? Press **Request LOA** below and tell "
                "us how long you'll be gone (and, optionally, why). Your request "
                "will be sent to Command for review. Your rank and post are kept "
                "while you're on leave."
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Any issues? Contact an officer for assistance.")

        await channel.send(embed=embed, view=LOAPanelView())
        await interaction.followup.send(
            f"✅ LOA panel posted in {channel.mention}.", ephemeral=True
        )

    # ── /end_loa ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="end_loa",
        description="[Command/Court] End a member's approved LOA — restore them to Active.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="The member returning from leave")
    async def end_loa(self, interaction: discord.Interaction, member: discord.Member):
        if not util.is_loa_reviewer(interaction.user):
            await interaction.response.send_message(
                "❌ Only Command, the Court, or Bot Admins may end an LOA.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        pages = await ns.get_members_by_discord_id(str(member.id))
        on_loa = [p for p in pages
                  if ns.extract_member_stats(p["properties"])["status"] == config.LOA_STATUS]

        has_role = interaction.guild.get_role(config.ROLE_LOA) in member.roles

        if not on_loa and not has_role:
            await interaction.followup.send(
                f"❌ {member.mention} isn't marked as being on LOA.", ephemeral=True
            )
            return

        # Restore every LOA row to Active (roster rows are never archived for LOA).
        for page in on_loa:
            await ns.set_member_status(page["id"], "Active")

        # Drop the LOA role.
        await util.remove_role(member, config.ROLE_LOA, reason="LOA ended")

        try:
            await member.send(
                "⚡ Welcome back — your **Leave of Absence** has ended and your "
                "service record is **Active** again. Ours is the Fury."
            )
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"✅ Ended LOA for {member.mention} — {len(on_loa)} roster row(s) set "
            f"back to Active and the LOA role removed.",
            ephemeral=True,
        )

        await audit_log.log_event(
            self.bot,
            title="⚡ LOA ended",
            color=discord.Color.gold(),
            fields=[
                ("Ended by", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Member", f"{member.mention} (`{member.id}`)", True),
                ("Rows restored", str(len(on_loa)), True),
            ],
        )

    # ── daily LOA auto-expiry ────────────────────────────────────────────
    # Restores members whose LOA end date (the "LOA Until" roster column, set
    # from the requested day count) has passed. LOAs approved before this
    # feature have no end date and are left for the manual /end_loa command.

    @tasks.loop(time=dtime(hour=6, minute=0, tzinfo=timezone.utc))
    async def loa_expiry_check(self):
        try:
            await self._loa_expiry_once()
        except Exception as exc:
            log.warning("loa_expiry_check skipped: %s", exc)

    async def _loa_expiry_once(self):
        guild = self.bot.get_guild(config.GUILD_ID)
        today = date.today()

        by_uid: dict[str, list] = {}
        for page in await ns.get_members_on_loa():
            uid = ns.extract_member_stats(page["properties"])["discord_user_id"]
            if uid:
                by_uid.setdefault(uid, []).append(page)

        for uid, plist in by_uid.items():
            due = [p for p in plist
                   if (u := ns.member_loa_until(p["properties"])) and u <= today]
            if not due:
                continue
            for page in due:
                await ns.restore_member_from_loa(page["id"])

            member = guild.get_member(int(uid)) if guild and uid.isdigit() else None
            # Only drop the LOA role once none of their rows are on leave.
            if member and len(due) == len(plist):
                await util.remove_role(member, config.ROLE_LOA, reason="LOA expired")
                try:
                    await member.send(
                        "⚡ Welcome back — your **Leave of Absence** has ended and your "
                        "service record is **Active** again. Ours is the Fury."
                    )
                except discord.HTTPException:
                    pass

            await audit_log.log_event(
                self.bot,
                title="⏳ LOA auto-expired",
                color=discord.Color.gold(),
                fields=[
                    ("Member", f"<@{uid}> (`{uid}`)", True),
                    ("Rows restored", str(len(due)), True),
                ],
            )

    @loa_expiry_check.before_loop
    async def _before_loa_expiry(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(LOACog(bot))
