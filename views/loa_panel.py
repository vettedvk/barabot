"""
LOA panel — persistent message with a single button:
  • Request LOA -> duration/return/reason modal -> posts a review embed to the
    LOA approval channel (config.CHANNEL_LOA_REVIEW).

Mirrors the discharge panel. The review embed carries the LOA Log page id in its
footer ('ref:<id>') and the member id in the 'Member' field, so the Approve/Deny
buttons (views/loa_review.py) keep working after a restart with no in-memory
state.

PERSISTENT: the button uses a fixed custom_id and survives restarts.
Register once at startup via bot.add_view(LOAPanelView()).
"""

import discord

import config
import notion_service as ns
from views.loa_review import LOAReviewView


class LOAModal(discord.ui.Modal, title="House Baratheon — LOA Request"):
    duration = discord.ui.TextInput(
        label="How long?",
        placeholder="e.g. 2 weeks, until Aug 30",
        style=discord.TextStyle.short,
        max_length=100,
        required=True,
    )
    return_date = discord.ui.TextInput(
        label="Expected return date (optional)",
        placeholder="e.g. 2026-08-30",
        style=discord.TextStyle.short,
        max_length=100,
        required=False,
    )
    reason = discord.ui.TextInput(
        label="Reason (optional)",
        placeholder="Why are you requesting leave?",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        pages = await ns.get_members_by_discord_id(str(interaction.user.id))
        all_stats = [ns.extract_member_stats(p["properties"]) for p in pages]
        active = [s for s in all_stats if s["status"] == "Active"]
        if not pages:
            await interaction.followup.send("❌ You are not in the roster.", ephemeral=True)
            return
        if not active:
            await interaction.followup.send(
                "❌ Your account is not active — you may already be on LOA or "
                "discharged. Contact an officer.",
                ephemeral=True,
            )
            return

        duration = self.duration.value.strip()
        return_note = self.return_date.value.strip()
        reason = self.reason.value.strip()

        log_page = await ns.create_loa_log_entry(
            discord_user_id=str(interaction.user.id),
            reason=reason or "No reason provided.",
            duration=duration,
            return_note=return_note,
        )

        # Approving sets EVERY active row to LOA, so list them all for the reviewer.
        positions = "\n".join(
            f"• {s['detachment'] or '—'} / {s['rank'] or '—'}" for s in active
        )

        embed = discord.Embed(
            title="Leave of Absence Request",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Member",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=False,
        )
        embed.add_field(name="Position(s)",     value=positions, inline=False)
        embed.add_field(name="Duration",        value=duration or "—", inline=True)
        embed.add_field(name="Expected return", value=return_note or "—", inline=True)
        embed.add_field(name="Reason",          value=reason or "None provided.", inline=False)
        if log_page:
            embed.set_footer(text=f"ref:{log_page['id']}")

        if config.CHANNEL_LOA_REVIEW == 0:
            await interaction.followup.send(
                "❌ LOA review channel not configured. Contact an admin.",
                ephemeral=True,
            )
            return

        review_channel = interaction.guild.get_channel(config.CHANNEL_LOA_REVIEW)
        if not review_channel:
            await interaction.followup.send(
                "❌ Could not find the LOA review channel.", ephemeral=True
            )
            return

        await review_channel.send(embed=embed, view=LOAReviewView())
        await interaction.followup.send(
            "✅ Your LOA request has been submitted for review.", ephemeral=True
        )


class LOAPanelView(discord.ui.View):
    """Persistent panel with the Request LOA button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Request LOA",
        style=discord.ButtonStyle.primary,
        emoji="🌙",
        custom_id="bar_loa_request",
    )
    async def request_loa(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LOAModal())
