"""
Enlistment panel — persistent message with two buttons:
  • Begin Enlistment  -> region picker -> (retinue picker for Asia) -> modal -> review
  • Envoy Application -> diplomatic application modal -> review

Retinues are region-based: EU and Middle East join the Black Stags, NA joins
the Thunderhooves, and Asian members choose either. The chosen region/retinue
ride along on the review embed so approval assigns the right retinue.

Both submissions post an embed with Accept/Decline to the enlistment review
channel (config.CHANNEL_ENLISTMENT_REVIEW).
"""

import re

import discord

import config
import notion_service as ns
from rank_engine import AUTO_LADDERS
from roblox import validate_roblox_user, RobloxValidationError
from views.enlistment_review import EnlistmentReviewView, EnvoyReviewView


# House Words the applicant must type (not case-sensitive; punctuation/spacing
# are normalised away so commas and extra spaces are tolerated).
_HOUSE_WORDS_NORMALIZED = "ours is the fury"


def _words_match(value: str) -> bool:
    norm = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return norm == _HOUSE_WORDS_NORMALIZED


def _starting_rank(fleet: str) -> str:
    ladder = AUTO_LADDERS.get(fleet)
    return ladder[0] if ladder else "Levy"


class EnlistModal(discord.ui.Modal, title="House Baratheon — Enlistment"):
    roblox_id = discord.ui.TextInput(
        label="Roblox ID",
        placeholder="Your numeric Roblox ID (not a URL)",
        max_length=20,
        required=True,
    )
    roblox_username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Your Roblox username (exact capitalisation)",
        max_length=50,
        required=True,
    )
    lorename = discord.ui.TextInput(
        label="Lore Name",
        placeholder="Your in-universe character name",
        max_length=100,
        required=True,
    )
    house_words = discord.ui.TextInput(
        label="House Words",
        placeholder="Enter House Baratheon's words",
        max_length=100,
        required=True,
    )

    def __init__(self, region: str, fleet: str):
        super().__init__()
        self.region = region
        self.fleet = fleet

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Reject if already actively enlisted
        existing = await ns.get_member_by_discord_id(str(interaction.user.id))
        if existing and ns.extract_member_stats(existing["properties"])["status"] == "Active":
            await interaction.followup.send(
                "❌ You're already enlisted! Contact an officer if this is an error.",
                ephemeral=True,
            )
            return

        # Verify the House Words (case-insensitive)
        if not _words_match(self.house_words.value):
            await interaction.followup.send(
                "❌ Those aren't the House words. Re-read them and try again.",
                ephemeral=True,
            )
            return

        # Validate Roblox identity up front so reviewers see clean data
        try:
            roblox_data = await validate_roblox_user(
                self.roblox_id.value, self.roblox_username.value
            )
        except RobloxValidationError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        rank = _starting_rank(self.fleet)

        embed = discord.Embed(
            title="📜 Military Enlistment — Pending Review",
            color=discord.Color.dark_blue(),
        )
        embed.add_field(name="Applicant", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Roblox Username", value=roblox_data["name"], inline=True)
        embed.add_field(name="Roblox ID", value=str(roblox_data["id"]), inline=True)
        embed.add_field(name="Region", value=self.region, inline=True)
        embed.add_field(name="Retinue", value=self.fleet, inline=True)
        embed.set_footer(text=f"Approving adds them to the {self.fleet} at {rank}.")
        embed.add_field(name="Lore Name", value=self.lorename.value, inline=False)

        review_channel = interaction.client.get_channel(config.CHANNEL_ENLISTMENT_REVIEW)
        if review_channel is None:
            await interaction.followup.send(
                "❌ Review channel not found. Please contact an admin.", ephemeral=True
            )
            return

        await review_channel.send(embed=embed, view=EnlistmentReviewView())

        await interaction.followup.send(
            f"⚡ Your enlistment into the **{self.fleet}** ({self.region}) has been "
            "submitted. Be patient while it's reviewed.",
            ephemeral=True,
        )


class FleetChoiceView(discord.ui.View):
    """Ephemeral retinue picker shown to Asian applicants, who may choose either."""

    def __init__(self, region: str):
        super().__init__(timeout=180)
        self.region = region

    @discord.ui.button(label="Black Stags", style=discord.ButtonStyle.primary, emoji="🦌")
    async def black_stags(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EnlistModal(self.region, "Black Stags"))

    @discord.ui.button(label="Thunderhooves", style=discord.ButtonStyle.success, emoji="⚡")
    async def thunderhooves(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EnlistModal(self.region, "Thunderhooves"))


class RegionChoiceView(discord.ui.View):
    """
    Ephemeral, transient region picker shown before the enlistment modal.
    EU / Middle East -> Black Stags, NA -> Thunderhooves (config.REGION_FLEETS);
    Asia -> the member chooses their retinue.
    """

    def __init__(self):
        super().__init__(timeout=180)
        for region in config.REGION_CHOICES:
            button = discord.ui.Button(label=region, style=discord.ButtonStyle.secondary)
            button.callback = self._make_callback(region)
            self.add_item(button)

    def _make_callback(self, region: str):
        async def callback(interaction: discord.Interaction):
            fleet = config.REGION_FLEETS.get(region)
            if fleet is None:  # Asia — the member picks
                await interaction.response.send_message(
                    "Your region may join either retinue — choose one:",
                    view=FleetChoiceView(region),
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(EnlistModal(region, fleet))
        return callback


class EnvoyModal(discord.ui.Modal, title="House Baratheon — Envoy Application"):
    roblox_username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Your Roblox username",
        max_length=50,
        required=True,
    )
    house = discord.ui.TextInput(
        label="House / Group Represented",
        placeholder="Which house or group are you representing?",
        max_length=100,
        required=True,
    )
    purpose = discord.ui.TextInput(
        label="Purpose",
        placeholder="The purpose of your diplomatic visit / relations sought",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="🕊️ Diplomatic Entry — Pending Review",
            color=discord.Color.teal(),
        )
        embed.add_field(name="Applicant", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Roblox Username", value=self.roblox_username.value, inline=True)
        embed.add_field(name="House / Group", value=self.house.value, inline=True)
        embed.add_field(name="Purpose", value=self.purpose.value, inline=False)
        embed.set_footer(text="Approving grants the Envoy role.")

        review_channel = interaction.client.get_channel(config.CHANNEL_ENLISTMENT_REVIEW)
        if review_channel is None:
            await interaction.followup.send(
                "❌ Review channel not found. Please contact an admin.", ephemeral=True
            )
            return

        await review_channel.send(embed=embed, view=EnvoyReviewView())

        await interaction.followup.send(
            "🕊️ Your envoy application has been submitted. Once you send in your submission, "
            "be patient for review.",
            ephemeral=True,
        )


class EnlistmentPanelView(discord.ui.View):
    """Persistent panel with the two entry buttons."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Begin Enlistment",
        style=discord.ButtonStyle.primary,
        custom_id="vel_enlist_begin",
    )
    async def begin_enlistment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🌍 Where are you based? Your region decides your retinue "
            "(EU & Middle East → Black Stags, NA → Thunderhooves, Asia → your choice).",
            view=RegionChoiceView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Envoy Application",
        style=discord.ButtonStyle.secondary,
        custom_id="vel_envoy_apply",
    )
    async def envoy_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EnvoyModal())
