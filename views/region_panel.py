"""
Region panel — persistent "Set My Region" button that lets ANY member pick
their region and be auto-sorted into the matching retinue, even if they
already hold one (EU & Middle East → Black Stags, NA → Thunderhooves, Asia →
chooses).

On selection the bot swaps the Discord retinue role and points any existing
Notion retinue row(s) at the new retinue, keeping rank and points intact.
Members with no roster row just get the role — the sync worker creates it.

PERSISTENT: fixed custom_id, survives restarts.
Register once at startup via bot.add_view(RegionPanelView()).
"""

import asyncio
import logging

import discord

import audit_log
import config
import notion_service as ns

log = logging.getLogger(__name__)

_FLEETS = ("Black Stags", "Thunderhooves")


async def _apply_fleet(interaction: discord.Interaction, region: str, fleet: str) -> None:
    """Swap the member onto `fleet`: Discord role + existing Notion fleet rows."""
    member: discord.Member = interaction.user
    guild = member.guild
    bot_top = guild.me.top_role

    target = guild.get_role(config.COMPANY_ROLE_IDS[fleet])
    other = guild.get_role(
        config.COMPANY_ROLE_IDS["Thunderhooves" if fleet == "Black Stags" else "Black Stags"]
    )

    if target is None or target >= bot_top or target.managed:
        await interaction.response.send_message(
            "❌ I can't assign the retinue role right now — contact an admin.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    already = target in member.roles
    try:
        if other and other in member.roles:
            await member.remove_roles(other, reason=f"Region sort — moved to {fleet}")
        if not already:
            await member.add_roles(target, reason=f"Region sort ({region})")
    except discord.HTTPException as exc:
        log.warning("region_panel: role swap failed for %s: %s", member, exc)
        await interaction.followup.send(
            "❌ Couldn't update your roles — contact an admin.", ephemeral=True
        )
        return

    # Point any existing fleet roster row(s) at the new fleet (rank/points kept).
    rows_moved = 0
    try:
        pages = await ns.get_members_by_discord_id(str(member.id))
        for page in pages:
            stats = ns.extract_member_stats(page["properties"])
            if stats["detachment"] in _FLEETS and stats["detachment"] != fleet:
                await ns.set_member_company(page["id"], fleet, stats["rank"] or "Levy")
                rows_moved += 1
                await asyncio.sleep(0.34)
    except Exception as exc:
        log.warning("region_panel: Notion update failed for %s: %s", member, exc)

    await interaction.followup.send(
        f"✅ You've been sorted into the **{fleet}** ({region})."
        + (" Your roster entry moved with you." if rows_moved else ""),
        ephemeral=True,
    )
    await audit_log.log_event(
        interaction.client,
        title="🌍 Region sorted",
        color=discord.Color.blue(),
        fields=[
            ("Member", f"{member.mention} (`{member.id}`)", True),
            ("Region → Retinue", f"{region} → {fleet}", True),
            ("Roster rows moved", str(rows_moved), True),
        ],
    )


class _RegionFleetChoiceView(discord.ui.View):
    """Retinue picker for regions that may choose (Asia)."""

    def __init__(self, region: str):
        super().__init__(timeout=180)
        self.region = region

    @discord.ui.button(label="Black Stags", style=discord.ButtonStyle.primary, emoji="🦌")
    async def black_stags(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _apply_fleet(interaction, self.region, "Black Stags")

    @discord.ui.button(label="Thunderhooves", style=discord.ButtonStyle.success, emoji="⚡")
    async def thunderhooves(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _apply_fleet(interaction, self.region, "Thunderhooves")


class _RegionSelectView(discord.ui.View):
    """Ephemeral region picker behind the panel button."""

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
                    view=_RegionFleetChoiceView(region),
                    ephemeral=True,
                )
                return
            await _apply_fleet(interaction, region, fleet)
        return callback


class RegionPanelView(discord.ui.View):
    """Persistent panel with the Set My Region button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Set My Region",
        style=discord.ButtonStyle.primary,
        emoji="🌍",
        custom_id="vel_region_set",
    )
    async def set_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🌍 Pick your region — it decides your retinue "
            "(EU & Middle East → Black Stags, NA → Thunderhooves, Asia → your choice).",
            view=_RegionSelectView(),
            ephemeral=True,
        )
