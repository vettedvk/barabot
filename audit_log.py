"""
Audit log — central helper for posting to the command/automation log channel
(config.CHANNEL_COMMAND_LOG). Used by the audit cog (slash-command usage) and by
the bot's automated actions (sync worker, member join/leave handlers).
"""

import logging

import discord

import config

log = logging.getLogger(__name__)


async def log_event(
    client: discord.Client,
    title: str,
    description: str = "",
    *,
    color: discord.Color | None = None,
    fields: list[tuple[str, str, bool]] | None = None,
) -> None:
    """
    Post an embed to the audit log channel. Best-effort: never raises into the
    caller, so logging can never break the action it's recording.
    """
    channel_id = getattr(config, "CHANNEL_COMMAND_LOG", 0)
    if not channel_id:
        return
    channel = client.get_channel(channel_id)
    if channel is None:
        return

    embed = discord.Embed(
        title=title,
        description=description or None,
        color=color or discord.Color.blurple(),
        timestamp=discord.utils.utcnow(),
    )
    for name, value, inline in (fields or []):
        embed.add_field(name=name, value=value[:1024], inline=inline)

    try:
        await channel.send(embed=embed)
    except discord.HTTPException as exc:
        log.warning("audit_log: could not post to log channel: %s", exc)
