"""
Region cog — posts the persistent "Set My Region" panel (see
views/region_panel.py). Members use it to be auto-sorted into their fleet by
region, even if they already hold a fleet role.
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import util
from views.region_panel import RegionPanelView


class RegionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setup_region_panel",
        description="[Admin] Post the persistent 'Set My Region' retinue-sorting panel in this channel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def setup_region_panel(self, interaction: discord.Interaction):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🌍 House Baratheon — Set Your Region",
            description=(
                "Press **Set My Region** below to tag yourself **EU** or **NA**. "
                "It's just a region tag — your retinue is assigned after your Basic "
                "Levy Training, not by region."
            ),
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="Any issues? Contact an officer for assistance.")

        await interaction.channel.send(embed=embed, view=RegionPanelView())
        await interaction.response.send_message("✅ Region panel posted.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RegionCog(bot))
