"""
util.py — small cross-cutting helpers shared by every cog and view.

Before this module existed, each review view and command cog carried its own
copy of "is this user an admin?", "pull the Discord ID out of this embed",
"disable the buttons and stamp who actioned it", etc. Centralising them here
means there is exactly ONE definition of each, so a fix or tweak lands
everywhere at once.

Three groups of helpers live here:
  1. Permission predicates — who is allowed to run or approve a given action.
  2. Review-embed parsing — recover an action's context from the message embed
     so persistent buttons keep working after a bot restart (the embed is the
     only state we have; nothing is held in memory).
  3. Best-effort single-role grant/removal.
"""

import re

import discord

import config


# ── 1. Permission predicates ────────────────────────────────────────────────
# Each takes the interacting member and returns True if they qualify. They read
# from the role-ID sets in config so permissions are configured in one place.

def has_any_role(user: discord.abc.User, role_ids) -> bool:
    """True if `user` holds at least one of `role_ids` (any iterable of IDs)."""
    wanted = set(role_ids)
    return any(r.id in wanted for r in getattr(user, "roles", ()))


def is_ruler(user: discord.abc.User) -> bool:
    """
    Heir / Lady / Lord of Storm's End — the destructive-command tier (bulk
    wipes, migrations, the mass role pass). The narrowest gate.
    """
    return has_any_role(user, config.RULER_ROLE_IDS)


def is_admin(user: discord.abc.User) -> bool:
    """
    Full administrative tier — every NON-destructive command. Bot Perms, Blood
    of the Storms, Council of Storm's End, and the rulers above them
    (config.ADMIN_ROLE_IDS). Destructive commands use is_ruler instead.
    """
    return has_any_role(user, config.ADMIN_ROLE_IDS)


def is_reviewer(user: discord.abc.User) -> bool:
    """Command staff who may approve enlistment / envoy / introduction requests."""
    return has_any_role(user, config.ENLISTMENT_REVIEWER_ROLE_IDS | config.ADMIN_ROLE_IDS)


def is_officer(member: discord.Member) -> bool:
    """
    Military Command access roles (or full admin) — gates the everyday roster /
    military commands and /event. An explicit role set, so the display
    hierarchy never constrains permissions.
    """
    return is_admin(member) or has_any_role(member, config.OFFICER_ROLE_IDS)


def is_event_logger(member: discord.Member) -> bool:
    """The Court (or full admin) — gates /log_event."""
    return is_admin(member) or has_any_role(member, config.LOGGER_ROLE_IDS)


def is_loa_reviewer(member: discord.Member) -> bool:
    """
    Who may approve/deny LOA requests: Bot Admins, Military Command officers, and
    the Court. is_officer and is_event_logger each already layer ADMIN on, so
    their union covers all three tiers.
    """
    return is_officer(member) or is_event_logger(member)


# ── 2. Review-embed parsing ───────────────────────────────────────────────────
# Review messages double as the bot's persistent state. When a button is
# clicked we rebuild context from the embed instead of from memory.

# Discord IDs are embedded in field values as `123456789012345678`.
_ID_RE = re.compile(r"`(\d+)`")
# Notion page IDs are stored in the embed footer as 'ref:<uuid>'.
_REF_RE = re.compile(r"ref:([0-9a-fA-F\-]{32,36})")


def embed_field(embed: discord.Embed, name: str) -> str | None:
    """Return the value of the embed field called `name`, or None if absent."""
    return next((f.value for f in embed.fields if f.name == name), None)


def id_in_field(embed: discord.Embed, name: str) -> int | None:
    """Extract the Discord ID written as `12345` inside the named field."""
    match = _ID_RE.search(embed_field(embed, name) or "")
    return int(match.group(1)) if match else None


def ref_in_footer(embed: discord.Embed) -> str | None:
    """Extract the Notion page id stored as 'ref:<uuid>' in the embed footer."""
    footer = embed.footer.text if embed.footer else ""
    match = _REF_RE.search(footer or "")
    return match.group(1) if match else None


async def finalize_review(
    interaction: discord.Interaction,
    view: discord.ui.View,
    *,
    color: discord.Color,
    label: str,
) -> None:
    """
    Close out a review message: disable its buttons, recolour the embed, and
    append a field naming who actioned it (e.g. "✅ Approved by @user").
    """
    for child in view.children:
        child.disabled = True
    embed = interaction.message.embeds[0]
    embed.color = color
    embed.add_field(name=label, value=interaction.user.mention, inline=False)
    await interaction.message.edit(embed=embed, view=view)


# ── 3. Best-effort role changes ───────────────────────────────────────────────
# "Best-effort" = never raise into the caller. A role the bot can't manage
# (above its own top role, or integration-managed) is simply skipped, so one
# un-assignable role can't abort the surrounding flow.

async def grant_role(member: discord.Member, role_id: int, reason: str) -> None:
    """Add a single role by ID if the member doesn't already have it."""
    role = member.guild.get_role(role_id)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason=reason)
        except discord.HTTPException:
            pass


async def remove_role(member: discord.Member, role_id: int, reason: str) -> None:
    """Remove a single role by ID if the member currently has it."""
    role = member.guild.get_role(role_id)
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason=reason)
        except discord.HTTPException:
            pass
