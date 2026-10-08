"""
Discharge panel — persistent message with a single button:
  • Request Discharge -> reason modal -> posts a review embed to the
    discharge review channel (config.CHANNEL_DISCHARGE_REVIEW).

Pure Discord: the review embed carries the member id in the 'Member' field and a
summary of their current rank/retinue roles, so the Approve/Deny buttons
(views/discharge_review.py) work with no external store.

PERSISTENT: the button uses a fixed custom_id and survives restarts.
Register once at startup via bot.add_view(DischargePanelView()).
"""

import discord

import config
from views.discharge_review import DischargeReviewView, summarize_service


class DischargeModal(discord.ui.Modal, title="House Baratheon — Discharge Request"):
    reason = discord.ui.TextInput(
        label="Reason (optional)",
        placeholder="Why are you requesting discharge?",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        reason = self.reason.value.strip()

        embed = discord.Embed(title="Discharge Request", color=discord.Color.orange())
        embed.add_field(
            name="Member",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=False,
        )
        embed.add_field(name="Current standing",
                        value=summarize_service(interaction.user), inline=False)
        embed.add_field(name="Reason", value=reason or "None provided.", inline=False)
        embed.set_footer(text="Approving strips military roles and grants Visitor.")

        review_channel = interaction.guild.get_channel(config.CHANNEL_DISCHARGE_REVIEW)
        if not review_channel:
            await interaction.followup.send(
                "❌ Could not find the discharge review channel. Contact an admin.",
                ephemeral=True,
            )
            return

        await review_channel.send(embed=embed, view=DischargeReviewView())
        await interaction.followup.send(
            "✅ Your discharge request has been submitted for review.", ephemeral=True
        )


class DischargePanelView(discord.ui.View):
    """Persistent panel with the Request Discharge button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Request Discharge",
        style=discord.ButtonStyle.danger,
        emoji="📜",
        custom_id="vel_discharge_request",
    )
    async def request_discharge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DischargeModal())
