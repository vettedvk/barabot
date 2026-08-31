"""
Profile-completion panel — the button attached to the weekly Saturday
missing-field DM (cogs/profile_sweep.py). A member whose roster entry is missing
its Roblox ID, Roblox username, or lore name gets a DM with this button; pressing
it opens a modal containing ONLY the fields they still need, and the answers are
written to every one of their roster rows (no review).

PERSISTENT: fixed custom_id, survives restarts. Register once at startup via
bot.add_view(ProfileCompletionView()). The modal is built dynamically on click,
so it always reflects the member's current blanks.
"""

import asyncio
import logging

import discord

import audit_log
import notion_service as ns

log = logging.getLogger(__name__)

# (stat key, modal label, placeholder, max_length)
_FIELDS = [
    ("roblox_id",       "Roblox ID",       "Your numeric Roblox ID", 20),
    ("roblox_username", "Roblox Username",  "Your Roblox username",   50),
    ("lorename",        "Lore Name",        "Your in-universe character name", 100),
]


def missing_fields(stats_list: list[dict]) -> list[str]:
    """Which of Roblox ID / username / lore name are blank across ALL of a
    member's rows (a value present on any row counts as filled)."""
    missing = []
    for key, *_ in _FIELDS:
        if not any((s.get(key) or "").strip() for s in stats_list):
            missing.append(key)
    return missing


class ProfileCompletionModal(discord.ui.Modal):
    def __init__(self, needed: list[str]):
        super().__init__(title="Complete Your Roster Profile")
        self._inputs: dict[str, discord.ui.TextInput] = {}
        for key, label, placeholder, max_len in _FIELDS:
            if key in needed:
                field = discord.ui.TextInput(
                    label=label, placeholder=placeholder,
                    max_length=max_len, required=True)
                self._inputs[key] = field
                self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        pages = await ns.get_members_by_discord_id(str(interaction.user.id))
        if not pages:
            await interaction.followup.send("❌ You're not in the roster.", ephemeral=True)
            return

        values = {k: f.value.strip() for k, f in self._inputs.items() if f.value.strip()}
        if not values:
            await interaction.followup.send("Nothing was entered.", ephemeral=True)
            return

        kwargs = {}
        if "roblox_id" in values:
            kwargs["roblox_id"] = values["roblox_id"]
        if "roblox_username" in values:
            kwargs["roblox_username"] = values["roblox_username"]
        if "lorename" in values:
            kwargs["lorename"] = values["lorename"]

        updated = 0
        for p in pages:
            try:
                await ns.update_roster_identity(p["id"], **kwargs)
                updated += 1
                await asyncio.sleep(0.34)  # stay under Notion's ~3 req/s
            except Exception as exc:
                log.error("profile_completion: failed for %s: %s", p.get("id"), exc)

        filled = ", ".join(f"**{k.replace('_', ' ')}**" for k in values)
        await interaction.followup.send(
            f"✅ Thank you — saved {filled} to your roster "
            f"entr{'y' if updated == 1 else 'ies'}. Ours is the Fury.",
            ephemeral=True,
        )
        await audit_log.log_event(
            interaction.client,
            title="📝 Profile completed (weekly sweep)",
            color=discord.Color.blurple(),
            fields=[
                ("Member", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Filled", filled, True),
                ("Entries updated", str(updated), True),
            ],
        )


class ProfileCompletionView(discord.ui.View):
    """Persistent DM panel — one button that opens the dynamic completion modal."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Complete My Profile",
        style=discord.ButtonStyle.primary,
        emoji="🪪",
        custom_id="vel_complete_profile",
    )
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        pages = await ns.get_members_by_discord_id(str(interaction.user.id))
        if not pages:
            await interaction.response.send_message(
                "❌ You're not in the roster, so there's nothing to complete.", ephemeral=True)
            return
        stats_list = [ns.extract_member_stats(p["properties"]) for p in pages]
        needed = missing_fields(stats_list)
        if not needed:
            await interaction.response.send_message(
                "✅ Your roster profile is already complete — thank you!", ephemeral=True)
            return
        await interaction.response.send_modal(ProfileCompletionModal(needed))
