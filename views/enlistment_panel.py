"""
Enlistment panel — persistent message with three buttons:
  • Begin Enlistment  -> region picker (EU/NA) -> modal -> review
  • Court Application  -> court modal (+ written-test stub) -> review
  • Envoy Application  -> diplomatic application modal -> review

New Levys are NO LONGER auto-sorted into a retinue — approval enlists them as an
UNSORTED Levy, and they're placed into a detachment by hand after a Basic Levy
Training (see cogs/events.py). Region (EU/NA) is still asked and granted as a
blanket tag. All submissions post an embed with Accept/Decline to the enlistment
review channel (config.CHANNEL_ENLISTMENT_REVIEW); a "Type" field routes approval.
"""

import re

import discord

import config
import notion_service as ns
from roblox import validate_roblox_user, RobloxValidationError
from views.enlistment_review import EnlistmentReviewView, EnvoyReviewView


# House Words the applicant must type (case/punctuation-insensitive).
_HOUSE_WORDS_NORMALIZED = "ours is the fury"


def _words_match(value: str) -> bool:
    norm = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return norm == _HOUSE_WORDS_NORMALIZED


class EnlistModal(discord.ui.Modal, title="House Baratheon — Enlistment"):
    roblox_id = discord.ui.TextInput(
        label="Roblox ID",
        placeholder="Your numeric Roblox ID (not a URL)",
        max_length=20, required=True,
    )
    roblox_username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Your Roblox username (exact capitalisation)",
        max_length=50, required=True,
    )
    lorename = discord.ui.TextInput(
        label="Lore Name",
        placeholder="Your in-universe character name",
        max_length=100, required=True,
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


class CourtIdentityModal(discord.ui.Modal, title="House Baratheon — Court Application"):
    """Step 1: identity. Step 2 (the written test) follows via a button."""
    roblox_id = discord.ui.TextInput(
        label="Roblox ID", placeholder="Your numeric Roblox ID", max_length=20, required=True)
    roblox_username = discord.ui.TextInput(
        label="Roblox Username", placeholder="Your Roblox username", max_length=50, required=True)
    lorename = discord.ui.TextInput(
        label="Lore Name", placeholder="Your in-universe character name", max_length=100, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        existing = await ns.get_member_by_discord_id(str(interaction.user.id))
        if existing and ns.extract_member_stats(existing["properties"])["status"] == "Active":
            await interaction.followup.send(
                "❌ You're already in the roster! Contact an officer if this is an error.",
                ephemeral=True)
            return
        try:
            roblox_data = await validate_roblox_user(self.roblox_id.value, self.roblox_username.value)
        except RobloxValidationError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        await interaction.followup.send(
            "⚖️ Identity confirmed. Press **Begin Written Test** to finish your application.",
            view=CourtTestButtonView(roblox_data["name"], str(roblox_data["id"]), self.lorename.value),
            ephemeral=True)


class CourtTestButtonView(discord.ui.View):
    def __init__(self, roblox_name: str, roblox_id: str, lorename: str):
        super().__init__(timeout=600)
        self.roblox_name = roblox_name
        self.roblox_id = roblox_id
        self.lorename = lorename

    @discord.ui.button(label="Begin Written Test", style=discord.ButtonStyle.primary, emoji="📝")
    async def begin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            CourtTestModal(self.roblox_name, self.roblox_id, self.lorename))


class CourtTestModal(discord.ui.Modal, title="Court — Written Test"):
    def __init__(self, roblox_name: str, roblox_id: str, lorename: str):
        super().__init__()
        self.roblox_name = roblox_name
        self.roblox_id = roblox_id
        self.lorename = lorename
        self._inputs: list[discord.ui.TextInput] = []
        for i, question in enumerate(config.COURT_TEST_QUESTIONS[:5]):
            field = discord.ui.TextInput(
                label=(question[:45] or f"Question {i + 1}"),
                placeholder=question[:100],
                style=discord.TextStyle.paragraph, max_length=500, required=True)
            self._inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title="⚖️ Court Application — Pending Review",
                              color=discord.Color.purple())
        embed.add_field(name="Type", value="Court", inline=True)
        embed.add_field(name="Applicant",
                        value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Roblox Username", value=self.roblox_name, inline=True)
        embed.add_field(name="Roblox ID", value=self.roblox_id, inline=True)
        embed.add_field(name="Lore Name", value=self.lorename, inline=False)
        for question, field in zip(config.COURT_TEST_QUESTIONS, self._inputs):
            embed.add_field(name=f"❓ {question[:250]}", value=(field.value or "—")[:1024], inline=False)
        embed.set_footer(text="Approving grants Court entry (Clerk).")

        review_channel = interaction.client.get_channel(config.CHANNEL_ENLISTMENT_REVIEW)
        if review_channel is None:
            await interaction.followup.send(
                "❌ Review channel not found. Please contact an admin.", ephemeral=True)
            return
        await review_channel.send(embed=embed, view=EnlistmentReviewView())
        await interaction.followup.send(
            "⚖️ Your Court application and written test have been submitted for review.",
            ephemeral=True)


class EnvoyModal(discord.ui.Modal, title="House Baratheon — Envoy Application"):
    roblox_username = discord.ui.TextInput(
        label="Roblox Username", placeholder="Your Roblox username", max_length=50, required=True)
    house = discord.ui.TextInput(
        label="House / Group Represented",
        placeholder="Which house or group are you representing?", max_length=100, required=True)
    purpose = discord.ui.TextInput(
        label="Purpose", placeholder="The purpose of your diplomatic visit / relations sought",
        style=discord.TextStyle.paragraph, max_length=500, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title="🕊️ Diplomatic Entry — Pending Review", color=discord.Color.teal())
        embed.add_field(name="Applicant",
                        value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Roblox Username", value=self.roblox_username.value, inline=True)
        embed.add_field(name="House / Group", value=self.house.value, inline=True)
        embed.add_field(name="Purpose", value=self.purpose.value, inline=False)
        embed.set_footer(text="Approving grants the Envoy role.")

        review_channel = interaction.client.get_channel(config.CHANNEL_ENLISTMENT_REVIEW)
        if review_channel is None:
            await interaction.followup.send(
                "❌ Review channel not found. Please contact an admin.", ephemeral=True)
            return
        await review_channel.send(embed=embed, view=EnvoyReviewView())
        await interaction.followup.send(
            "🕊️ Your envoy application has been submitted. Be patient for review.", ephemeral=True)


class EnlistmentPanelView(discord.ui.View):
    """Persistent panel with the entry buttons."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Begin Enlistment", style=discord.ButtonStyle.primary,
                       custom_id="vel_enlist_begin")
    async def begin_enlistment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🌍 Where are you based? (Region is a tag — you'll be sorted into a retinue "
            "after your Basic Levy Training.)", view=RegionChoiceView(), ephemeral=True)

    @discord.ui.button(label="Court Application", style=discord.ButtonStyle.secondary,
                       emoji="⚖️", custom_id="vel_court_apply")
    async def court_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CourtIdentityModal())

    @discord.ui.button(label="Envoy Application", style=discord.ButtonStyle.secondary,
                       custom_id="vel_envoy_apply")
    async def envoy_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EnvoyModal())
