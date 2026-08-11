"""
Audit cog — logs every slash command a user runs to the audit channel
(config.CHANNEL_COMMAND_LOG). Automated bot actions are logged from their own
handlers via audit_log.log_event.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

import audit_log

log = logging.getLogger(__name__)


def _format_value(value) -> str:
    """Render a command option value readably for the log."""
    if isinstance(value, (discord.Member, discord.User)):
        return f"{value.mention} (`{value.id}`)"
    if isinstance(value, discord.Role):
        return f"@{value.name}"
    if isinstance(value, (discord.abc.GuildChannel, discord.Thread)):
        return f"#{value.name}"
    text = str(value)
    return text[:200] if text else "—"


def _format_options(interaction: discord.Interaction) -> str:
    params = vars(getattr(interaction, "namespace", object())) or {}
    if not params:
        return "—"
    return "\n".join(f"`{name}`: {_format_value(val)}" for name, val in params.items())


class AuditCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: app_commands.Command | app_commands.ContextMenu,
    ):
        # Only log true slash commands (context menus have no options namespace).
        name = getattr(command, "qualified_name", getattr(command, "name", "unknown"))
        channel = interaction.channel
        channel_str = f"{channel.mention}" if hasattr(channel, "mention") else "DM"

        await audit_log.log_event(
            self.bot,
            title=f"/{name}",
            color=discord.Color.greyple(),
            fields=[
                ("User", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Channel", channel_str, True),
                ("Options", _format_options(interaction), False),
            ],
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AuditCog(bot))
