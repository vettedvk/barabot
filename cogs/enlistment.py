"""
Enlistment cog — posts the persistent enlistment/diplomatic panel.

Enlistment is no longer a slash command; members use the panel buttons
(see views/enlistment_panel.py). This cog only provides the admin command
to (re)post that panel.
"""

import logging

import discord
import httpx
from discord import app_commands
from discord.ext import commands

import audit_log
import config
import util
from views.enlistment_panel import EnlistmentPanelView
from views.envoy_panel import EnvoyPanelView
from views.court_panel import CourtPanelView

log = logging.getLogger(__name__)


def _is_admin(interaction: discord.Interaction) -> bool:
    return util.is_admin(interaction.user)


class EnlistmentCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != config.GUILD_ID:
            return
        role = member.guild.get_role(config.ROLE_UNVERIFIED)
        if role:
            try:
                await member.add_roles(role, reason="Joined the server")
                await audit_log.log_event(
                    self.bot,
                    title="📥 Member joined",
                    color=discord.Color.green(),
                    fields=[
                        ("Member", f"{member.mention} (`{member.id}`)", True),
                        ("Action", f"Granted @{role.name}", True),
                    ],
                )
            except discord.Forbidden:
                log.warning("Couldn't add join role to %s (check hierarchy/permissions).", member)

    @app_commands.command(
        name="setup_enlist_panel",
        description="[Admin] Post the enlistment / diplomatic entry panel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def setup_enlist_panel(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        channel = self.bot.get_channel(config.CHANNEL_ENLISTMENT_PANEL)
        if channel is None:
            await interaction.followup.send(
                "❌ Enlistment panel channel not found (check CHANNEL_ENLISTMENT_PANEL).",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="House Baratheon — Ours is the Fury",
            color=discord.Color.dark_gold(),
        )
        embed.add_field(
            name="Military Enlistment",
            value="Press **Begin Enlistment** below, pick your region, and fill in the form. "
                  "Once you send in your submission, be patient for review.",
            inline=False,
        )
        embed.set_footer(text="Envoy and Court entry have their own panels. Any issues? Contact an officer.")

        # Re-upload the banner so the hosted link doesn't matter long-term.
        file = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(config.ENLISTMENT_BANNER_URL)
                resp.raise_for_status()
            import io
            file = discord.File(io.BytesIO(resp.content), filename="banner.png")
            embed.set_image(url="attachment://banner.png")
        except Exception as exc:
            log.warning("Could not download banner, falling back to direct URL: %s", exc)
            embed.set_image(url=config.ENLISTMENT_BANNER_URL)

        if file:
            await channel.send(embed=embed, file=file, view=EnlistmentPanelView())
        else:
            await channel.send(embed=embed, view=EnlistmentPanelView())

        await interaction.followup.send(
            f"✅ Enlistment panel posted in {channel.mention}.", ephemeral=True
        )

    @app_commands.command(
        name="setup_envoy_panel",
        description="[Admin] Post the Envoy (diplomatic entry) panel in this channel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def setup_envoy_panel(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🕊️ House Baratheon — Diplomatic Envoys",
            description=(
                "Representing another house or allegiance? Press **Envoy Application** below.\n\n"
                "Name the real Game of Thrones house or allegiance you speak for (e.g. House Stark, "
                "the Faith of the Seven, the Night's Watch)."
            ),
            color=discord.Color.teal(),
        )
        embed.set_footer(text="Once you send in your submission, be patient for review.")
        await interaction.channel.send(embed=embed, view=EnvoyPanelView())
        await interaction.response.send_message(
            f"✅ Envoy panel posted in {interaction.channel.mention}.", ephemeral=True)

    @app_commands.command(
        name="setup_court_panel",
        description="[Admin] Post the Court of Storm's End application panel in this channel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def setup_court_panel(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        embed = discord.Embed(
            title="⚖️ Court of Storm's End — Applications",
            description=(
                "Seeking a place in the Court? Press **Court Application** below to confirm your "
                "identity and sit the written test. Approved applicants join the Court as a **Clerk**."
            ),
            color=discord.Color.purple(),
        )
        embed.set_footer(text="Once you send in your submission, be patient for review.")
        await interaction.channel.send(embed=embed, view=CourtPanelView())
        await interaction.response.send_message(
            f"✅ Court panel posted in {interaction.channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EnlistmentCog(bot))
