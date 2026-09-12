"""
Discord-authority sync — the "Discord at the centre" listener.

When a member's RANK or DETACHMENT roles — or their NICKNAME — change in Discord,
this upserts their Notion roster to match (sync_service.reconcile_member): a
hand-given rank role is mirrored to Notion, a new detachment gets a row, a
dropped detachment's row is archived, the lore name on every row is refreshed
from the nickname, and a member with no roster entry at all gets one created from
their Discord ID. Discord is the source of truth; Notion is the durable store
that follows it.

Two things keep this quiet and safe:
  • It only fires when the tracked (rank/detachment/command) role set OR the
    nickname actually changes — separator and status role edits are ignored.
  • It skips members the bot itself just edited (role_service loop-guard), so a
    bot promotion (which already wrote Notion first) isn't re-processed.

It never DMs members about missing fields — bulk role changes shouldn't spam
anyone. Missing fields are chased once a week by the Saturday sweep.
"""

import logging

import discord
from discord.ext import commands

import config
import role_service
import sync_service

log = logging.getLogger(__name__)

# Role IDs that, when gained or lost, mean a member's rank/detachment changed.
_TRACKED_ROLE_IDS = (
    set(config.RANK_ROLE_IDS.values())
    | set(config.COMPANY_ROLE_IDS.values())
    | set(config.COMMAND_ROLE_IDS)
)


class DiscordSyncCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if not getattr(config, "DISCORD_AUTHORITY_SYNC", False):
            return
        if after.guild.id != config.GUILD_ID or after.bot:
            return

        before_tracked = {r.id for r in before.roles} & _TRACKED_ROLE_IDS
        after_tracked = {r.id for r in after.roles} & _TRACKED_ROLE_IDS
        roles_changed = before_tracked != after_tracked
        nick_changed = before.nick != after.nick
        if not roles_changed and not nick_changed:
            return  # nothing rank/detachment/name-related changed

        # Loop-guard: the bot's own promotions/placements/discharges write Notion
        # first and mark the member here, so skip those (avoids a redundant round
        # trip and any double promotion announcement).
        if role_service.was_bot_edit(after.id):
            return

        try:
            await sync_service.reconcile_member(after.guild, self.bot, after)
        except Exception as exc:
            log.error("discord_sync: reconcile_member failed for %s: %s", after, exc)


async def setup(bot: commands.Bot):
    await bot.add_cog(DiscordSyncCog(bot))
