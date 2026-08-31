"""
Region panel — persistent "Set My Region" button. Region is now just a blanket
EU / NA tag (the close-combat retinue keeps its internal split via these); it no
longer sorts anyone into a detachment. Selecting a region grants that role and
removes the other.

PERSISTENT: fixed custom_id, survives restarts.
Register once at startup via bot.add_view(RegionPanelView()).
"""

import logging

import discord

import audit_log
import config

log = logging.getLogger(__name__)


async def _apply_region(interaction: discord.Interaction, region: str) -> None:
    member: discord.Member = interaction.user
    guild = member.guild
    bot_top = guild.me.top_role

    target = guild.get_role(config.REGION_ROLE_IDS[region])
    others = [guild.get_role(rid) for r, rid in config.REGION_ROLE_IDS.items() if r != region]

    if target is None or target >= bot_top or target.managed:
        await interaction.response.send_message(
            "❌ I can't assign the region role right now — contact an admin.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        drop = [r for r in others if r and r in member.roles and r < bot_top and not r.managed]
        if drop:
            await member.remove_roles(*drop, reason="Region change")
        if target not in member.roles:
            await member.add_roles(target, reason=f"Region set — {region}")
    except discord.HTTPException as exc:
        log.warning("region_panel: role update failed for %s: %s", member, exc)
        await interaction.followup.send(
            "❌ Couldn't update your roles — contact an admin.", ephemeral=True)
        return

    await interaction.followup.send(f"✅ Your region is set to **{region}**.", ephemeral=True)
    await audit_log.log_event(
        interaction.client,
        title="🌍 Region set",
        color=discord.Color.blue(),
        fields=[
            ("Member", f"{member.mention} (`{member.id}`)", True),
            ("Region", region, True),
        ],
    )


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
            await _apply_region(interaction, region)
        return callback


class RegionPanelView(discord.ui.View):
    """Persistent panel with the Set My Region button."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Set My Region", style=discord.ButtonStyle.primary,
                       emoji="🌍", custom_id="vel_region_set")
    async def set_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🌍 Pick your region (EU or NA) — it's just a tag, it doesn't decide your retinue.",
            view=_RegionSelectView(), ephemeral=True)
