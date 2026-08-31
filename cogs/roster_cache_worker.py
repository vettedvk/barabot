"""
Roster cache worker — keeps the in-memory hot layer (roster_cache) warm.

Notion is the durable store; roster_cache is a per-member read cache that writes
invalidate. This cog does the other half: a periodic FULL refresh
(config.ROSTER_CACHE_REFRESH_SECONDS) that reloads the whole roster from Notion,
so rows added or edited directly in Notion are picked up. It also enables the
cache at startup per config.ROSTER_CACHE_ENABLED, and offers a ruler
/roster_cache command to inspect / refresh / toggle it at runtime.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import notion_service as ns
import roster_cache
import util

log = logging.getLogger(__name__)


class RosterCacheCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        roster_cache.enable(getattr(config, "ROSTER_CACHE_ENABLED", True))
        self.refresh_loop.change_interval(
            seconds=getattr(config, "ROSTER_CACHE_REFRESH_SECONDS", 180))
        self.refresh_loop.start()

    def cog_unload(self):
        self.refresh_loop.cancel()

    @tasks.loop(seconds=180)
    async def refresh_loop(self):
        if not roster_cache.is_enabled():
            return
        try:
            count = await ns.refresh_roster_cache()
            log.debug("roster cache refreshed: %d members", count)
        except Exception as exc:
            # A refresh failure just means the cache ages out via its TTL and
            # reads fall through to Notion — never fatal.
            log.warning("roster cache refresh skipped: %s", exc)

    @refresh_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="roster_cache",
        description="[Ruler] Inspect, refresh, or toggle the in-memory roster cache.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(action="What to do (default: status)")
    @app_commands.choices(action=[
        app_commands.Choice(name="status",  value="status"),
        app_commands.Choice(name="refresh", value="refresh"),
        app_commands.Choice(name="on",      value="on"),
        app_commands.Choice(name="off",     value="off"),
    ])
    async def roster_cache_cmd(self, interaction: discord.Interaction,
                               action: app_commands.Choice[str] = None):
        if not util.is_ruler(interaction.user):
            await interaction.response.send_message(
                "❌ Heir / Lady / Lord of Storm's End only.", ephemeral=True)
            return
        act = action.value if action else "status"
        await interaction.response.defer(ephemeral=True)

        if act == "on":
            roster_cache.enable(True)
            count = await ns.refresh_roster_cache()
            await interaction.followup.send(
                f"✅ Roster cache **enabled** and warmed ({count} members).", ephemeral=True)
            return
        if act == "off":
            roster_cache.enable(False)
            await interaction.followup.send("🛑 Roster cache **disabled** and cleared.", ephemeral=True)
            return
        if act == "refresh":
            count = await ns.refresh_roster_cache()
            await interaction.followup.send(
                f"🔄 Roster cache refreshed — **{count}** members cached.", ephemeral=True)
            return

        s = roster_cache.stats()
        await interaction.followup.send(
            f"📊 Roster cache — enabled: **{s['enabled']}**, members: **{s['members']}**, "
            f"pages: **{s['pages']}** (TTL {int(roster_cache.TTL_SECONDS)}s, "
            f"refresh {getattr(config, 'ROSTER_CACHE_REFRESH_SECONDS', 180)}s).",
            ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RosterCacheCog(bot))
