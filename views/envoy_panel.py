"""
Envoy panel — its own entry point for diplomatic envoys of other houses.

  Envoy Application -> modal (House/Allegiance, Roblox username, purpose) -> review

The applicant names the house or allegiance they represent (a real Game of
Thrones house or allegiance, e.g. House Stark, the Faith of the Seven, the
Night's Watch). Every house is capped at config.ENVOY_CAP active envoys, except
the houses in config.ENVOY_EXEMPT_HOUSES (e.g. Arryn), which are unlimited. On
approval the Envoy role is granted and the envoy is recorded in the Notion Envoys
DB (see views/enlistment_review.py: EnvoyReviewView).
"""

import discord

import config
import notion_service as ns
from views.enlistment_review import EnvoyReviewView


async def cap_blocked(house_key: str) -> bool:
    """True if this house is at/over its active-envoy cap (exempt houses never are)."""
    if house_key in config.ENVOY_EXEMPT_HOUSES:
        return False
    counts = await ns.count_active_envoys_by_house()
    return counts.get(house_key, 0) >= config.ENVOY_CAP


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

        # One active envoy row per person.
        if await ns.get_active_envoy_by_discord_id(str(interaction.user.id)):
            await interaction.followup.send(
                "❌ You're already registered as an envoy. Contact an officer if this is an error.",
                ephemeral=True)
            return

        house_display, house_key = ns.normalize_house(self.house.value)
        if not house_display:
            await interaction.followup.send(
                "❌ Enter the house or allegiance you represent.", ephemeral=True)
            return
        if await cap_blocked(house_key):
            await interaction.followup.send(
                f"❌ **{house_display}** already has the maximum of **{config.ENVOY_CAP}** envoys. "
                "Another house may still have openings.", ephemeral=True)
            return

        embed = discord.Embed(title="🕊️ Diplomatic Entry — Pending Review", color=discord.Color.teal())
        embed.add_field(name="House / Allegiance", value=house_display, inline=True)
        embed.add_field(name="Applicant",
                        value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Roblox Username", value=self.roblox_username.value, inline=True)
        embed.add_field(name="Purpose", value=(self.purpose.value or "—")[:1024], inline=False)
        embed.set_footer(text=f"Approving grants the Envoy role (cap {config.ENVOY_CAP}/house, "
                              "Arryn exempt) and records them in the Envoys DB.")

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
