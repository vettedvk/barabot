"""
Discharge panel — persistent message with a single button:
  • Request Discharge -> reason modal -> posts a review embed to the
    discharge review channel (config.CHANNEL_DISCHARGE_REVIEW).

Replaces the old /discharge slash command. The review embed carries the
Discharge Log page id in its footer ('ref:<id>') and the member id in the
'Member' field, so the Approve/Deny buttons (views/discharge_review.py) keep
working unchanged.

PERSISTENT: the button uses a fixed custom_id and survives restarts.
Register once at startup via bot.add_view(DischargePanelView()).
"""

import discord

import config
import notion_service as ns
from views.discharge_review import DischargeReviewView


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

        pages = await ns.get_members_by_discord_id(str(interaction.user.id))
        all_stats = [ns.extract_member_stats(p["properties"]) for p in pages]
        active = [s for s in all_stats if s["status"] == "Active"]
        if not pages:
            await interaction.followup.send("❌ You are not in the roster.", ephemeral=True)
            return
        if not active:
            await interaction.followup.send(
                "❌ Your account is not active — contact an admin.", ephemeral=True
            )
            return

        reason = self.reason.value.strip()

        log_page = await ns.create_discharge_log_entry(
            discord_user_id=str(interaction.user.id),
            reason=reason or "No reason provided.",
        )

        # Approving discharges EVERY active row, so list them all for the reviewer.
        positions = "\n".join(
            f"• {s['detachment'] or '—'} / {s['rank'] or '—'}" for s in active
        )

        embed = discord.Embed(
            title="Discharge Request",
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="Member",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=False,
        )
        embed.add_field(name="Position(s)", value=positions, inline=False)
        embed.add_field(name="Reason",      value=reason or "None provided.", inline=False)
        embed.set_footer(text=f"ref:{log_page['id']}")

        if config.CHANNEL_DISCHARGE_REVIEW == 0:
            await interaction.followup.send(
                "❌ Discharge review channel not configured. Contact an admin.",
                ephemeral=True,
            )
            return

        review_channel = interaction.guild.get_channel(config.CHANNEL_DISCHARGE_REVIEW)
        if not review_channel:
            await interaction.followup.send(
                "❌ Could not find the discharge review channel.", ephemeral=True
            )
            return

        await review_channel.send(embed=embed, view=DischargeReviewView())
        await interaction.followup.send(
            "✅ Your discharge request has been submitted for admin review.", ephemeral=True
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
