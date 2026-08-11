"""
Self-update panel — persistent message with a single button that lets a member
fill in their Roblox ID + username themselves. The values are written straight
to Notion (no review). Only allowed when their Roblox info isn't already set;
updates ALL of the member's roster entries (command staff may hold several).

PERSISTENT: fixed custom_id, survives restarts.
Register once at startup via bot.add_view(SelfUpdatePanelView()).
"""

import asyncio
import logging

import discord

import audit_log
import notion_service as ns

log = logging.getLogger(__name__)


def _has_roblox(stats: dict) -> bool:
    return bool(stats["roblox_id"]) and bool(stats["roblox_username"])


class SelfUpdateModal(discord.ui.Modal, title="Update Your Roblox Info"):
    roblox_id = discord.ui.TextInput(
        label="Roblox ID",
        placeholder="Your numeric Roblox ID",
        max_length=20,
        required=True,
    )
    roblox_username = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Your Roblox username",
        max_length=50,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        pages = await ns.get_members_by_discord_id(str(interaction.user.id))
        if not pages:
            await interaction.followup.send("❌ You're not in the roster.", ephemeral=True)
            return

        rid = self.roblox_id.value.strip()
        ruser = self.roblox_username.value.strip()

        updated = 0
        for p in pages:
            try:
                await ns.update_roster_identity(p["id"], roblox_id=rid, roblox_username=ruser)
                updated += 1
                await asyncio.sleep(0.34)  # stay under Notion's ~3 req/s
            except Exception as exc:
                log.error("self_update: failed for %s: %s", p.get("id"), exc)

        await interaction.followup.send(
            f"✅ Saved your Roblox info (**{ruser}**, ID `{rid}`) to "
            f"{updated} roster entr{'y' if updated == 1 else 'ies'}.",
            ephemeral=True,
        )

        await audit_log.log_event(
            interaction.client,
            title="📝 Self-update — Roblox info",
            color=discord.Color.blurple(),
            fields=[
                ("Member", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Roblox", f"{ruser} (`{rid}`)", True),
                ("Entries updated", str(updated), True),
            ],
        )


class SelfUpdatePanelView(discord.ui.View):
    """Persistent panel with the Update Roblox Info button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Update Roblox Info",
        style=discord.ButtonStyle.primary,
        emoji="🪪",
        custom_id="vel_self_update",
    )
    async def update_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        pages = await ns.get_members_by_discord_id(str(interaction.user.id))
        if not pages:
            await interaction.response.send_message(
                "❌ You're not in the roster, so there's nothing to update.", ephemeral=True
            )
            return

        # Only allow if their Roblox info isn't already set on every entry.
        all_filled = all(_has_roblox(ns.extract_member_stats(p["properties"])) for p in pages)
        if all_filled:
            await interaction.response.send_message(
                "✅ Your Roblox info is already on file. Contact an officer if it needs changing.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(SelfUpdateModal())
