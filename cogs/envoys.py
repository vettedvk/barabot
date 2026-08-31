"""
Envoys cog — the diplomatic-envoy log and management.

  /envoys          — show how many active envoys each house has (the counts log).
  /remove_envoy    — remove an envoy: archive their Envoys-DB row (freeing a house
                     cap slot) and strip the Envoy role.

Envoys are added through the Envoy panel (views/envoy_panel.py); every house is
capped at config.ENVOY_CAP active envoys except config.ENVOY_EXEMPT_HOUSES.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import audit_log
import config
import notion_service as ns
import util

log = logging.getLogger(__name__)


class EnvoysCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="envoys", description="[Officer] Show active envoy counts per house.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def envoys(self, interaction: discord.Interaction):
        if not util.is_officer(interaction.user):
            await interaction.response.send_message("❌ Officers only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        rows = await ns.get_active_envoys()
        if not rows:
            await interaction.followup.send(
                "No active envoys on record. (If this looks wrong, check NOTION_ENVOY_DB_ID is set "
                "and the Envoys DB is shared with the bot's Notion integration.)", ephemeral=True)
            return

        # Group by normalized house, keep a display name per house.
        by_house: dict[str, dict] = {}
        for p in rows:
            disp, key = ns.normalize_house(ns.get_prop_text(p["properties"], "House"))
            entry = by_house.setdefault(key, {"display": disp or key, "members": []})
            name = ns.get_prop_text(p["properties"], "Discord Username") or \
                ns.get_prop_text(p["properties"], "Envoy") or "—"
            entry["members"].append(name)

        lines = []
        for key in sorted(by_house, key=lambda k: (-len(by_house[k]["members"]), k)):
            info = by_house[key]
            n = len(info["members"])
            exempt = key in config.ENVOY_EXEMPT_HOUSES
            cap = "∞" if exempt else str(config.ENVOY_CAP)
            flag = " ⚠️ full" if not exempt and n >= config.ENVOY_CAP else ""
            lines.append(f"**{info['display']}** — {n}/{cap}{flag}\n   {', '.join(info['members'])}")

        embed = discord.Embed(
            title="🕊️ Active Envoys by House",
            description="\n".join(lines)[:4000],
            color=discord.Color.teal(),
        )
        embed.set_footer(text=f"Total: {len(rows)} envoy(s) • cap {config.ENVOY_CAP}/house (Arryn exempt)")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="remove_envoy", description="[Officer] Remove an envoy (archive their record + strip the role).")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="The envoy to remove")
    async def remove_envoy(self, interaction: discord.Interaction, member: discord.Member):
        if not util.is_officer(interaction.user):
            await interaction.response.send_message("❌ Officers only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        row = await ns.get_active_envoy_by_discord_id(str(member.id))
        house = ns.normalize_house(ns.get_prop_text(row["properties"], "House"))[0] if row else ""
        if row:
            try:
                await ns.remove_envoy(row["id"])
            except Exception as exc:
                log.error("remove_envoy: failed to archive %s: %s", row.get("id"), exc)

        # Strip the Envoy role regardless (handles envoys not in the DB too).
        await util.remove_role(member, config.ROLE_ENVOY, "Envoy removed")

        if not row:
            await interaction.followup.send(
                f"✅ Stripped the Envoy role from {member.mention}. "
                "(No active Envoys-DB record was found for them.)", ephemeral=True)
        else:
            await interaction.followup.send(
                f"✅ Removed {member.mention} as an envoy of **{house or '—'}** "
                "(record archived, role stripped).", ephemeral=True)

        await audit_log.log_event(
            self.bot,
            title="🕊️ Envoy removed",
            color=discord.Color.orange(),
            fields=[
                ("Officer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Envoy", f"{member.mention} (`{member.id}`)", True),
                ("House", house or "—", True),
            ],
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EnvoysCog(bot))
