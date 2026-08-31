"""
Enlistment panel — military entry only. One button:
  • Begin Enlistment -> region picker (EU/NA) -> modal -> review

The modal collects Lore Name, Roblox Username, Roblox User ID, any past
experience (optional), and the House Words. On approval the applicant enlists as
an UNSORTED Levy in House Baratheon (see views/enlistment_review.py) and is
placed into a detachment by hand after a Basic Levy Training (see cogs/events.py).

Envoy and Court entry live on their own panels now (views/envoy_panel.py,
views/court_panel.py).
"""

import re

import discord

import config
import notion_service as ns
from roblox import validate_roblox_user, RobloxValidationError
from views.enlistment_review import EnlistmentReviewView


# House Words the applicant must type (case/punctuation-insensitive).
_HOUSE_WORDS_NORMALIZED = "ours is the fury"


def _words_match(value: str) -> bool:
    norm = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return norm == _HOUSE_WORDS_NORMALIZED


class EnlistModal(discord.ui.Modal, title="House Baratheon — Enlistment"):
    lorename = discord.ui.TextInput(
        label="Lore Name",
        placeholder="Your in-universe character name",
        max_length=100, required=True,
    )
    roblox_username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Your Roblox username (exact capitalisation)",
        max_length=50, required=True,
    )
    roblox_id = discord.ui.TextInput(
        label="Roblox User ID",
        placeholder="Your numeric Roblox ID (not a URL)",
        max_length=20, required=True,
    )
    experience = discord.ui.TextInput(
        label="Any past experience (optional)",
        placeholder="Groups/genres you've been part of, roles held, etc.",
        style=discord.TextStyle.paragraph, max_length=500, required=False,
    )
    house_words = discord.ui.TextInput(
        label="House Words",
        placeholder="Enter House Baratheon's words",
        max_length=100, required=True,
    )

    def __init__(self, region: str):
        super().__init__()
        self.region = region

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        existing = await ns.get_member_by_discord_id(str(interaction.user.id))
        if existing and ns.extract_member_stats(existing["properties"])["status"] == "Active":
            await interaction.followup.send(
                "❌ You're already enlisted! Contact an officer if this is an error.",
                ephemeral=True)
            return
        if not _words_match(self.house_words.value):
            await interaction.followup.send(
                "❌ Those aren't the House words. Re-read them and try again.", ephemeral=True)
            return
        try:
            roblox_data = await validate_roblox_user(self.roblox_id.value, self.roblox_username.value)
        except RobloxValidationError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        embed = discord.Embed(title="📜 Military Enlistment — Pending Review",
                              color=discord.Color.dark_blue())
        embed.add_field(name="Type", value="Military", inline=True)
        embed.add_field(name="Region", value=self.region, inline=True)
        embed.add_field(name="Applicant",
                        value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Roblox Username", value=roblox_data["name"], inline=True)
        embed.add_field(name="Roblox ID", value=str(roblox_data["id"]), inline=True)
        embed.add_field(name="Lore Name", value=self.lorename.value, inline=False)
        embed.add_field(name="Past Experience",
                        value=(self.experience.value or "—")[:1024], inline=False)
        embed.set_footer(text="Approving enlists them as an UNSORTED Levy — place them "
                              "into a retinue after their Basic Levy Training.")

        review_channel = interaction.client.get_channel(config.CHANNEL_ENLISTMENT_REVIEW)
        if review_channel is None:
            await interaction.followup.send(
                "❌ Review channel not found. Please contact an admin.", ephemeral=True)
            return
        await review_channel.send(embed=embed, view=EnlistmentReviewView())
        await interaction.followup.send(
            f"⚡ Your enlistment ({self.region}) has been submitted. You'll be sorted into a "
            "retinue after your first training. Be patient while it's reviewed.", ephemeral=True)


class RegionChoiceView(discord.ui.View):
    """Ephemeral region picker (EU / NA) shown before the enlistment modal."""

    def __init__(self):
        super().__init__(timeout=180)
        for region in config.REGION_CHOICES:
            button = discord.ui.Button(label=region, style=discord.ButtonStyle.secondary)
            button.callback = self._make_callback(region)
            self.add_item(button)

    def _make_callback(self, region: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_modal(EnlistModal(region))
        return callback


class EnlistmentPanelView(discord.ui.View):
    """Persistent panel with the military entry button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Begin Enlistment", style=discord.ButtonStyle.primary,
                       custom_id="vel_enlist_begin")
    async def begin_enlistment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🌍 Where are you based? (Region is a tag — you'll be sorted into a retinue "
            "after your Basic Levy Training.)", view=RegionChoiceView(), ephemeral=True)
