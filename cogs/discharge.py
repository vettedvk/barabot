"""
Discharge cog — posts the persistent discharge request panel and handles the
on_member_remove abandonment detection.

Discharge is no longer a slash command; members use the panel button
(see views/discharge_panel.py). This cog provides the admin command to
(re)post that panel.
"""

import discord
from discord import app_commands
from discord.ext import commands

import audit_log
import config
import notion_service as ns
import role_service
import util
from views.discharge_panel import DischargePanelView


def _is_admin(interaction: discord.Interaction) -> bool:
    return util.is_admin(interaction.user)


class DischargeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /setup_discharge_panel ───────────────────────────────────────────

    @app_commands.command(
        name="setup_discharge_panel",
        description="[Admin] Post the persistent Discharge Request panel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def setup_discharge_panel(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if config.CHANNEL_DISCHARGE_PANEL == 0:
            await interaction.followup.send(
                "❌ Discharge panel channel not configured (set CHANNEL_DISCHARGE_PANEL).",
                ephemeral=True,
            )
            return

        channel = self.bot.get_channel(config.CHANNEL_DISCHARGE_PANEL)
        if channel is None:
            await interaction.followup.send(
                "❌ Discharge panel channel not found (check CHANNEL_DISCHARGE_PANEL).",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="House Baratheon — Discharge",
            description=(
                "Wish to step down from service? Press **Request Discharge** below "
                "and provide an optional reason. Your request will be sent to the "
                "command staff for review."
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Any issues? Contact an officer for assistance.")

        await channel.send(embed=embed, view=DischargePanelView())
        await interaction.followup.send(
            f"✅ Discharge panel posted in {channel.mention}.", ephemeral=True
        )

    # ── Abandonment detection ────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.guild.id != config.GUILD_ID:
            return

        pages = await ns.get_members_by_discord_id(str(member.id))
        active = [p for p in pages
                  if ns.extract_member_stats(p["properties"])["status"] == "Active"]
        if not active:
            return  # not rostered, or already discharged/abandoned

        # Auto-archive EVERY active row as Abandoned (specialised-detachment
        # members hold several).
        stats = ns.extract_member_stats(active[0]["properties"])
        for page in active:
            await ns.archive_member(page["id"], "Abandoned")

        await audit_log.log_event(
            self.bot,
            title="📤 Member left — auto-archived",
            color=discord.Color.dark_red(),
            fields=[
                ("Member", f"{member} (`{member.id}`)", True),
                ("Action", f"{len(active)} Notion record(s) set to Abandoned", True),
                ("Roblox", f"{stats['roblox_username'] or '—'} (`{stats['roblox_id'] or '—'}`)", False),
            ],
        )

        log_channel = member.guild.get_channel(config.CHANNEL_ABANDONMENT_LOG)
        if log_channel:
            embed = discord.Embed(
                title="⚠️ Member Missing From Server",
                color=discord.Color.dark_red(),
            )
            embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=False)
            embed.add_field(name="Guild",     value=f"{member.guild.name} (`{member.guild.id}`)", inline=True)
            embed.add_field(name="Notion Status", value="Abandoned (auto-archived)", inline=True)
            embed.add_field(name="Action",    value=f"{len(active)} roster page(s) archived in Notion.", inline=False)
            await log_channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(DischargeCog(bot))
