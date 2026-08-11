"""
Schedule cog — the weekly training schedule.

Commands (Officers / Court / Bot Admins):
  /create_schedule — open the builder. If a schedule already exists for the
                     current week it loads that one, so this doubles as edit.
  /edit_schedule   — alias of /create_schedule.
  /post_schedule   — backup: (re)post or refresh the public embed. Normally the
                     builder's Post button and live edits handle this.

The public embed is posted once (config.CHANNEL_SCHEDULE) and edited in place.
Every Monday 00:00 UK the wipe loop resets it to a placeholder; a startup pass
catches up if the bot was offline over the boundary.
"""

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

import audit_log
import config
import notion_service as ns
import util
from views.schedule_builder import (
    SchedulerView, load_state, new_state, save_state, sync_public,
    placeholder_embed, current_uk_monday,
)

log = logging.getLogger(__name__)


def _configured() -> bool:
    return bool(os.environ.get("NOTION_SCHEDULE_DB_ID"))


class ScheduleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.wipe_check.start()

    def cog_unload(self):
        self.wipe_check.cancel()

    # ── shared builder opener (create == edit) ───────────────────────────

    async def _open_builder(self, interaction: discord.Interaction):
        if not util.is_schedule_manager(interaction.user):
            await interaction.response.send_message(
                "❌ Command, the Court, or Bot Admins only.", ephemeral=True)
            return
        if not _configured():
            await interaction.response.send_message(
                "❌ Schedule database not configured (set NOTION_SCHEDULE_DB_ID).",
                ephemeral=True)
            return

        state = load_state(await ns.get_schedule_row())
        # If the stored schedule is from a previous week, start a fresh week but
        # keep the public message so it's edited in place, not reposted.
        if state.get("week_start") != current_uk_monday().isoformat():
            fresh = new_state()
            fresh["message_id"] = state.get("message_id")
            fresh["channel_id"] = state.get("channel_id")
            state = fresh
            await save_state(state)

        view = SchedulerView(state, interaction)
        await interaction.response.send_message(
            embed=view.draft_embed(), view=view, ephemeral=True)

    @app_commands.command(
        name="create_schedule",
        description="[Command/Court] Build the weekly training schedule (also edits the current week).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def create_schedule(self, interaction: discord.Interaction):
        await self._open_builder(interaction)

    @app_commands.command(
        name="edit_schedule",
        description="[Command/Court] Edit the current week's training schedule.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def edit_schedule(self, interaction: discord.Interaction):
        await self._open_builder(interaction)

    @app_commands.command(
        name="post_schedule",
        description="[Command/Court] Post or refresh the public weekly schedule embed.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def post_schedule(self, interaction: discord.Interaction):
        if not util.is_schedule_manager(interaction.user):
            await interaction.response.send_message(
                "❌ Command, the Court, or Bot Admins only.", ephemeral=True)
            return
        if not _configured():
            await interaction.response.send_message(
                "❌ Schedule database not configured (set NOTION_SCHEDULE_DB_ID).",
                ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        state = load_state(await ns.get_schedule_row())
        state = await sync_public(self.bot, state)
        await save_state(state)
        await interaction.followup.send(
            f"✅ Public schedule posted/updated in <#{config.CHANNEL_SCHEDULE}>.",
            ephemeral=True)

    # ── weekly wipe (Monday 00:00 UK) + reboot catch-up ──────────────────

    @tasks.loop(minutes=10)
    async def wipe_check(self):
        if not _configured():
            return
        state = load_state(await ns.get_schedule_row())
        if not state.get("message_id"):
            return  # nothing has been posted, nothing to wipe
        if state.get("week_start") == current_uk_monday().isoformat():
            return  # still the current week

        # Stale schedule from a past week → reset the public embed to the
        # placeholder and clear the week (reusing the same public message).
        channel = self.bot.get_channel(config.CHANNEL_SCHEDULE)
        if channel is not None:
            try:
                msg = await channel.fetch_message(int(state["message_id"]))
                await msg.edit(embed=placeholder_embed())
            except discord.HTTPException:
                pass

        fresh = new_state()
        fresh["message_id"] = state.get("message_id")
        fresh["channel_id"] = state.get("channel_id")
        await save_state(fresh)

        log.info("Weekly schedule wiped for new week starting %s", fresh["week_start"])
        await audit_log.log_event(
            self.bot,
            title="🧹 Weekly schedule reset",
            color=discord.Color.gold(),
            fields=[
                ("New week", fresh["week_start"], True),
                ("Public embed", "reset to placeholder", True),
            ],
        )

    @wipe_check.before_loop
    async def _before_wipe(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ScheduleCog(bot))
