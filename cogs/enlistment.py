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
            value="Press **Begin Enlistment** below. Once you send in your submission, be patient for review.",
            inline=False,
        )
        embed.add_field(
            name="Diplomatic Entry",
            value="Press **Envoy Application** below. Once you send in your submission, be patient for review.",
            inline=False,
        )
        embed.set_footer(text="Any issues? Contact an officer for assistance.")

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


async def setup(bot: commands.Bot):
    await bot.add_cog(EnlistmentCog(bot))
