"""
AROK — House Baratheon Discord Bot
Entry point. Run with: python bot.py
"""

import asyncio
import logging
import os
import time

import discord
from discord.ext import commands
from dotenv import load_dotenv

import config
from views.enlistment_panel import EnlistmentPanelView
from views.envoy_panel import EnvoyPanelView
from views.court_panel import CourtPanelView
from views.enlistment_review import EnlistmentReviewView, EnvoyReviewView
from views.discharge_panel import DischargePanelView
from views.discharge_review import DischargeReviewView
from views.region_panel import RegionPanelView
from views.trials_panel import TRIALS, TrialRequestView, TrialTicketCloseView

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("baratheon")

# If the gateway stays disconnected longer than this, exit the process so the
# host (PebbleHost) auto-restarts us with a fresh connection — recovers from
# DNS/network blips in ~this many seconds instead of discord.py's backoff,
# which can balloon to 9+ minutes.
WATCHDOG_TIMEOUT_SECONDS = 180
WATCHDOG_CHECK_SECONDS = 30


class BaratheonBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True  # required for on_member_remove
        super().__init__(command_prefix="!", intents=intents)
        # Gateway connectivity tracking for the watchdog.
        self._gw_connected = False
        self._gw_since = time.monotonic()

    def _mark_gateway(self, connected: bool):
        if connected != self._gw_connected:
            self._gw_connected = connected
            self._gw_since = time.monotonic()

    async def on_connect(self):
        self._mark_gateway(True)

    async def on_resumed(self):
        self._mark_gateway(True)

    async def on_disconnect(self):
        self._mark_gateway(False)

    async def _connection_watchdog(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(WATCHDOG_CHECK_SECONDS)
            down_for = time.monotonic() - self._gw_since
            if not self._gw_connected and down_for > WATCHDOG_TIMEOUT_SECONDS:
                log.critical(
                    "Gateway disconnected for %.0fs (> %ss). Exiting for a clean "
                    "host restart.", down_for, WATCHDOG_TIMEOUT_SECONDS,
                )
                os._exit(1)  # hard exit → PebbleHost relaunches with fresh DNS

    async def setup_hook(self):
        # Start the connectivity watchdog.
        self.loop.create_task(self._connection_watchdog())

        # Register persistent views so buttons survive restarts
        self.add_view(EnlistmentPanelView())
        self.add_view(EnvoyPanelView())
        self.add_view(CourtPanelView())
        self.add_view(EnlistmentReviewView())
        self.add_view(EnvoyReviewView())
        self.add_view(DischargePanelView())
        self.add_view(DischargeReviewView())
        self.add_view(RegionPanelView())
        for trial_key in TRIALS:  # one persistent button per trial
            self.add_view(TrialRequestView(trial_key))
        self.add_view(TrialTicketCloseView())

        # Load cogs
        for cog in [
            "cogs.enlistment",
            "cogs.discharge",
            "cogs.audit",
            "cogs.help",
            "cogs.role_hygiene",
            "cogs.region",
            "cogs.trials",
            "cogs.weekly_report",
        ]:
            await self.load_extension(cog)
            log.info("Loaded cog: %s", cog)

        # Sync slash commands to the guild
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Slash commands synced to guild %s", config.GUILD_ID)

    async def on_ready(self):
        self._mark_gateway(True)
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Ours is the Fury.",
            )
        )


async def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")

    async with BaratheonBot() as bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
