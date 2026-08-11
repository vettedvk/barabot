"""
Trials cog — /setup_trials_panel posts one embed + request button per
requestable assessment (Corporal & Lieutenant; the specialised-detachment
trials are invitation-only). Requests open a private ticket channel — all the
eligibility/channel/ping logic lives in views/trials_panel.py.
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import util
from views.trials_panel import TRIALS, TrialRequestView, build_trial_embed


class TrialsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setup_trials_panel",
        description="[Admin] Post the trial-request panels (one embed + button per trial) in this channel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def setup_trials_panel(self, interaction: discord.Interaction):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        header = discord.Embed(
            title="⚡ House Baratheon — Officer Assessments",
            description=(
                "Ready to rise? Request an assessment below — a private channel "
                "opens between you and your hosts to arrange it. Only **Knights** "
                "may take the officer path; make sure you meet the requirements "
                "before requesting.\n\n"
                "*The Knight Trial and Stormguard tryouts are by invitation from "
                "their commands.*"
            ),
            color=discord.Color.dark_gold(),
        )
        await interaction.channel.send(embed=header)

        for key in TRIALS:
            await interaction.channel.send(
                embed=build_trial_embed(key), view=TrialRequestView(key)
            )

        await interaction.followup.send(
            f"✅ Posted {len(TRIALS)} trial panels in {interaction.channel.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TrialsCog(bot))
