"""
Migration cog — /toggle_sync flips the Discord→Notion sync worker on/off at
runtime (config.SYNC_ENABLED ships False during migrations; edit it to True
for a permanent re-enable once everything checks out).

The old /migrate_notion command is gone — the 2026-07 Baratheon roster
migration was run directly against the Notion API.
"""

import discord
from discord import app_commands
from discord.ext import commands

import audit_log
import config
import util


class MigrationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="toggle_sync",
        description="[Ruler] Turn the periodic Discord→Notion sync on/off (runtime; resets on restart).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def toggle_sync(self, interaction: discord.Interaction):
        if not util.is_ruler(interaction.user):
            await interaction.response.send_message(
                "❌ Restricted to the Heir, Lady, and Lord of Storm's End.", ephemeral=True)
            return

        config.SYNC_ENABLED = not config.SYNC_ENABLED
        state = "ON ✅" if config.SYNC_ENABLED else "OFF ⛔"
        await interaction.response.send_message(
            f"🔁 Sync worker is now **{state}**.\n"
            "(Runtime only — edit `SYNC_ENABLED` in config.py to persist across restarts.)",
            ephemeral=True,
        )
        await audit_log.log_event(
            self.bot,
            title=f"🔁 Sync toggled {state}",
            color=discord.Color.dark_gold(),
            fields=[("Admin", f"{interaction.user.mention} (`{interaction.user.id}`)", True)],
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MigrationCog(bot))
