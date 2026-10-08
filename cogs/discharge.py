"""
Discharge cog — posts the persistent discharge request panel.

Discharge is a panel button (see views/discharge_panel.py), not a slash command.
This cog only provides the admin command to (re)post that panel. Approval strips
military roles and grants Visitor — pure Discord, no external store.
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import util
from views.discharge_panel import DischargePanelView


class DischargeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setup_discharge_panel",
        description="[Admin] Post the persistent Discharge Request panel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def setup_discharge_panel(self, interaction: discord.Interaction):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        channel = self.bot.get_channel(config.CHANNEL_DISCHARGE_PANEL)
        if channel is None:
            await interaction.followup.send(
                "❌ Discharge panel channel not found (check CHANNEL_DISCHARGE_PANEL).",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="House Baratheon — Discharge",
            description=(
                "Wish to step down from service? Press **Request Discharge** below "
                "and provide an optional reason. Your request will be sent to the "
                "command staff for review."
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Any issues? Contact an officer for assistance.")

        await channel.send(embed=embed, view=DischargePanelView())
        await interaction.followup.send(
            f"✅ Discharge panel posted in {channel.mention}.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(DischargeCog(bot))
