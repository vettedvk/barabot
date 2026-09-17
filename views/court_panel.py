"""
Court panel — its own entry point for Court of Storm's End applications.

  Court Application -> identity modal -> written test -> review

On approval the applicant joins the Court at Clerk (routed by the shared
EnlistmentReviewView via the embed's Type=Court field).
"""

import discord

import config
from roblox import fetch_roblox_by_id, RobloxValidationError
from views.enlistment_review import EnlistmentReviewView


def _norm_gender(value: str) -> str | None:
    v = (value or "").strip().lower()
    if v in ("m", "male"):
        return "M"
    if v in ("f", "female"):
        return "F"
    return None


class CourtIdentityModal(discord.ui.Modal, title="House Baratheon — Court Application"):
    """Step 1: identity. Step 2 (the written test) follows via a button."""
    roblox_id = discord.ui.TextInput(
        label="Roblox ID", placeholder="Your numeric Roblox ID", max_length=20, required=True)
    lorename = discord.ui.TextInput(
        label="Lore Name", placeholder="Your in-universe character name", max_length=100, required=True)
    gender = discord.ui.TextInput(
        label="Lore Character Gender (M/F)", placeholder="M or F", max_length=6, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gender = _norm_gender(self.gender.value)
        if gender is None:
            await interaction.followup.send(
                "❌ Lore character gender must be **M** or **F**.", ephemeral=True)
            return
        try:
            roblox_data = await fetch_roblox_by_id(self.roblox_id.value)
        except RobloxValidationError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        questions = "\n".join(f"**{i + 1}.** {q}" for i, (_lbl, q) in enumerate(config.COURT_TEST_QUESTIONS))
        await interaction.followup.send(
            "⚖️ Identity confirmed. Read the questions below, then press **Begin Written Test**:\n\n"
            + questions,
            view=CourtTestButtonView(roblox_data["name"], str(roblox_data["id"]),
                                     self.lorename.value, gender),
            ephemeral=True)


class CourtTestButtonView(discord.ui.View):
    def __init__(self, roblox_name: str, roblox_id: str, lorename: str, gender: str):
        super().__init__(timeout=600)
        self.roblox_name = roblox_name
        self.roblox_id = roblox_id
        self.lorename = lorename
        self.gender = gender

    @discord.ui.button(label="Begin Written Test", style=discord.ButtonStyle.primary, emoji="📝")
    async def begin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            CourtTestModal(self.roblox_name, self.roblox_id, self.lorename, self.gender))


class CourtTestModal(discord.ui.Modal, title="Court — Written Test"):
    def __init__(self, roblox_name: str, roblox_id: str, lorename: str, gender: str):
        super().__init__()
        self.roblox_name = roblox_name
        self.roblox_id = roblox_id
        self.lorename = lorename
        self.gender = gender
        self._inputs: list[discord.ui.TextInput] = []
        for i, (label, question) in enumerate(config.COURT_TEST_QUESTIONS[:5]):
            field = discord.ui.TextInput(
                label=(label[:45] or f"Question {i + 1}"),
                placeholder=question[:100],
                style=discord.TextStyle.paragraph, max_length=500, required=True)
            self._inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(title="⚖️ Court Application — Pending Review",
                              color=discord.Color.purple())
        embed.add_field(name="Type", value="Court", inline=True)
        embed.add_field(name="Gender", value=self.gender, inline=True)
        embed.add_field(name="Applicant",
                        value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Roblox Username", value=self.roblox_name, inline=True)
        embed.add_field(name="Roblox ID", value=self.roblox_id, inline=True)
        embed.add_field(name="Lore Name", value=self.lorename, inline=False)
        for (_label, question), field in zip(config.COURT_TEST_QUESTIONS, self._inputs):
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


class CourtPanelView(discord.ui.View):
    """Persistent panel with the Court application button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Court Application", style=discord.ButtonStyle.primary,
                       emoji="⚖️", custom_id="vel_court_apply_panel")
    async def court_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CourtIdentityModal())
