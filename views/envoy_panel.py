"""
Envoy panel — its own entry point for diplomatic envoys of other houses.

  Envoy Application -> modal (House/Allegiance, Roblox username, purpose) -> review

The applicant names the house or allegiance they represent (a real Game of
Thrones house or allegiance, e.g. House Stark, the Faith of the Seven, the
Night's Watch). Reviewers decide by hand; on approval the Envoy role is granted
(see views/enlistment_review.py: EnvoyReviewView).
"""

import discord

import config
from views.enlistment_review import EnvoyReviewView


class EnvoyModal(discord.ui.Modal, title="House Baratheon — Envoy Application"):
    house = discord.ui.TextInput(
        label="House / Allegiance represented",
        placeholder="A real GoT house or allegiance — e.g. House Stark, Faith of the Seven",
        max_length=100, required=True,
    )
    roblox_username = discord.ui.TextInput(
        label="Roblox Username", placeholder="Your Roblox username", max_length=50, required=True)
    purpose = discord.ui.TextInput(
        label="Purpose (optional)", placeholder="The relations you seek / reason for your visit",
        style=discord.TextStyle.paragraph, max_length=500, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        house_display = (self.house.value or "").strip()
        if not house_display:
            await interaction.followup.send(
                "❌ Enter the house or allegiance you represent.", ephemeral=True)
            return

        embed = discord.Embed(title="🕊️ Diplomatic Entry — Pending Review", color=discord.Color.teal())
        embed.add_field(name="House / Allegiance", value=house_display, inline=True)
        embed.add_field(name="Applicant",
                        value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Roblox Username", value=self.roblox_username.value, inline=True)
        embed.add_field(name="Purpose", value=(self.purpose.value or "—")[:1024], inline=False)
        embed.set_footer(text="Approving grants the Envoy role.")

        review_channel = interaction.client.get_channel(config.CHANNEL_ENLISTMENT_REVIEW)
        if review_channel is None:
            await interaction.followup.send(
                "❌ Review channel not found. Please contact an admin.", ephemeral=True)
            return
        await review_channel.send(embed=embed, view=EnvoyReviewView())
        await interaction.followup.send(
            f"🕊️ Your envoy application for **{house_display}** has been submitted. "
            "Be patient for review.", ephemeral=True)


class EnvoyPanelView(discord.ui.View):
    """Persistent panel with the Envoy application button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Envoy Application", style=discord.ButtonStyle.primary,
                       emoji="🕊️", custom_id="vel_envoy_apply_panel")
    async def envoy_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EnvoyModal())
