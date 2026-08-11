"""
Sync worker cog — runs sync_service.reconcile() on a timer (config.SYNC_INTERVAL_SECONDS).

All the logic lives in sync_service so the manual /sync command and this
background loop share one implementation. This cog only schedules it and honours
the config.SYNC_ENABLED kill-switch.
"""

import logging

from discord.ext import commands, tasks

import config
import sync_service

log = logging.getLogger(__name__)


class SyncWorkerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sync_loop.start()

    def cog_unload(self):
        self.sync_loop.cancel()

    @tasks.loop(seconds=config.SYNC_INTERVAL_SECONDS)
    async def sync_loop(self):
        if not getattr(config, "SYNC_ENABLED", True):
            return  # reconciliation disabled (e.g. during incident recovery)
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            return
        try:
            summary = await sync_service.reconcile(guild, self.bot)
        except Exception as exc:
            log.error("Sync worker: reconcile failed: %s", exc)
            return
        # Only log a heartbeat when something actually changed, to avoid noise.
        # (.get keeps this robust if reconcile's summary keys ever change.)
        if any(summary.get(k) for k in ("created", "rank_updated", "archived", "abandoned",
                                        "lorename_updated", "errors")):
            log.info("Sync worker: %s", summary)

    @sync_loop.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(SyncWorkerCog(bot))
