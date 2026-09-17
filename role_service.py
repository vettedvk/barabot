"""
Discord role service — translates rank/company names to role IDs and applies them.
"""

import time

import discord
import config


# ── Loop-guard for Discord-authority sync ────────────────────────────────────
# When the BOT changes a member's roles (a promotion, a placement, a discharge),
# Discord fires on_member_update — which the Discord→Notion authority listener
# also watches. Notion is always written BEFORE the role edit, so a re-sync would
# be a harmless no-op, but we still suppress it to avoid the redundant Notion
# round-trip and any double promotion announcement. Callers that edit roles mark
# the member here; the listener skips members marked within the window.
_recent_bot_edits: dict[int, float] = {}
_SUPPRESS_WINDOW_SECONDS = 30.0


def mark_bot_edit(member_id: int) -> None:
    """Record that the bot just edited this member's roles (loop-guard)."""
    _recent_bot_edits[member_id] = time.monotonic()


def was_bot_edit(member_id: int) -> bool:
    """True if the bot edited this member's roles within the suppress window."""
    ts = _recent_bot_edits.get(member_id)
    if ts is None:
        return False
    if time.monotonic() - ts > _SUPPRESS_WINDOW_SECONDS:
        _recent_bot_edits.pop(member_id, None)
        return False
    return True


async def set_nickname(member: discord.Member, rank: str, lorename: str) -> None:
    """
    Set the member's nickname to '{rank}, {lorename}' (best-effort). Long ranks
    use their short form (config.NICKNAME_RANK_SHORT) so the lore name isn't
    truncated by Discord's 32-char cap.
    """
    if not lorename:
        return
    display_rank = config.NICKNAME_RANK_SHORT.get(rank, rank)
    nick = f"{display_rank}, {lorename}"[: config.NICKNAME_MAX]
    try:
        await member.edit(nick=nick, reason="Bot rank/lore nickname update")
    except discord.Forbidden:
        pass  # bot lacks Manage Nicknames or member is higher in hierarchy
    except discord.HTTPException:
        pass


async def add_house_membership_roles(member: discord.Member) -> None:
    """Grant the House Baratheon membership role on military enlistment
    (best-effort; the section separators are handled by role hygiene)."""
    guild = member.guild
    role = guild.get_role(config.ROLE_HOUSE_BARATHEON)
    if role and role not in member.roles and role < guild.me.top_role and not role.managed:
        await member.add_roles(role, reason="House Baratheon membership")


async def apply_rank_and_company(
    member: discord.Member,
    company: str,
    new_rank: str,
    old_rank: str | None = None,
    old_company: str | None = None,
    lorename: str | None = None,
) -> dict:
    """
    Swap company role and rank role on a guild member.
    Removes old roles before adding new ones to avoid stacking.
    If lorename is provided, also updates the nickname to '{rank}, {lorename}'.
    Returns {"added": [role names], "removed": [role names]} describing the
    actual change (both empty on a no-op), for audit logging by callers.
    """
    mark_bot_edit(member.id)  # loop-guard: this is a bot-initiated role edit
    to_remove: list[discord.Role] = []
    to_add:    list[discord.Role] = []

    guild = member.guild

    # Company role swap
    if old_company and old_company != company:
        old_company_role_id = config.COMPANY_ROLE_IDS.get(old_company)
        if old_company_role_id:
            r = guild.get_role(old_company_role_id)
            if r:
                to_remove.append(r)

    new_company_role_id = config.COMPANY_ROLE_IDS.get(company)
    if new_company_role_id:
        r = guild.get_role(new_company_role_id)
        if r and r not in member.roles:
            to_add.append(r)

    # Rank role swap — remove all ranks belonging to the (old) company
    company_for_cleanup = old_company or company
    for rank_name in config.COMPANY_RANKS.get(company_for_cleanup, []):
        role_id = config.RANK_ROLE_IDS.get(rank_name)
        if role_id:
            r = guild.get_role(role_id)
            if r and r in member.roles:
                to_remove.append(r)

    new_rank_role_id = config.RANK_ROLE_IDS.get(new_rank)
    if new_rank_role_id:
        r = guild.get_role(new_rank_role_id)
        if r:
            to_add.append(r)

    # Never remove a role we're also about to (re-)add. The rank cleanup loop
    # above strips every rank role for the company — which includes the member's
    # CURRENT rank, the very role new_rank re-adds. Without this filter, every
    # periodic sync would strip that role and immediately re-grant it, causing a
    # constant add/remove flicker for any member that gets reconciled.
    add_ids = {r.id for r in to_add}
    to_remove = [r for r in to_remove if r.id not in add_ids]

    # Filter out roles the bot can't manage (above its top role or managed by
    # an integration) so a single un-assignable role — e.g. a High Command role
    # sitting above the bot — doesn't abort the whole update. Notion stays the
    # source of truth; the Discord role is simply left to manual management.
    bot_top = guild.me.top_role
    to_remove = [r for r in to_remove if r < bot_top and not r.managed]
    to_add    = [r for r in to_add    if r < bot_top and not r.managed and r not in member.roles]

    if to_remove:
        await member.remove_roles(*to_remove, reason="Bot rank/company update")
    if to_add:
        await member.add_roles(*to_add, reason="Bot rank/company update")

    if lorename is not None:
        await set_nickname(member, new_rank, lorename)

    # Congratulate the member if this was a climb up the auto ladder. Best-effort
    # and gated to real increases, so company moves / demotions stay quiet.
    await announce_promotion(member, new_rank, old_rank)

    # Report what actually changed so automated callers (the sync worker) can
    # log meaningful actions and skip no-op reconciliations.
    return {
        "added":   [r.name for r in to_add],
        "removed": [r.name for r in to_remove],
    }


async def announce_promotion(
    member: discord.Member,
    new_rank: str,
    old_rank: str | None,
) -> None:
    """
    Post a congratulations ping in the promotions channel when a member moves UP
    the auto ladder (Levy → Soldier → Footman → Veteran Footman → Man-at-Arms).

    Only the default ladder ranks are celebrated — stations, Court, specialised
    and High Command ranks are appointments handled elsewhere. Best-effort: it
    only fires on a genuine ladder increase and never raises into the caller, so
    it's safe to call from every rank-change path (bot auto-promotions, the
    manual commands, and the sync worker reconciling a hand-edited Discord role).
    """
    ladder = config.FLEET_RANKS
    if new_rank not in ladder or old_rank not in ladder:
        return
    if ladder.index(new_rank) <= ladder.index(old_rank):
        return  # lateral move, demotion, or no change — nothing to celebrate

    channel_id = getattr(config, "CHANNEL_PROMOTIONS", 0)
    if not channel_id:
        return
    channel = member.guild.get_channel(channel_id)
    if channel is None:
        return

    embed = discord.Embed(
        title="⚔️ Promotion — Ours is the Fury!",
        description=(
            f"Congratulations {member.mention}, you have been promoted to "
            f"**{new_rank}**! Your service to House Baratheon is recognised."
        ),
        color=discord.Color.gold(),
    )
    try:
        await channel.send(
            content=f"🎉 {member.mention}",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
    except discord.HTTPException:
        pass


async def remove_all_rank_and_company_roles(member: discord.Member) -> None:
    """Strip all company and rank roles (used on discharge/abandonment)."""
    mark_bot_edit(member.id)  # loop-guard: bot-initiated role edit
    to_remove: list[discord.Role] = []
    guild = member.guild

    all_managed_ids = set(config.COMPANY_ROLE_IDS.values()) | set(config.RANK_ROLE_IDS.values())
    bot_top = guild.me.top_role
    for role in member.roles:
        if role.id in all_managed_ids and role < bot_top and not role.managed:
            to_remove.append(role)

    if to_remove:
        await member.remove_roles(*to_remove, reason="Bot discharge/abandonment cleanup")


async def apply_discharge_roles(member: discord.Member, lorename: str | None = None) -> None:
    """
    On an accepted discharge: strip all military roles (fleet/detachment, rank,
    the military separators, House Baratheon membership, Envoy) and grant
    Visitor. The member KEEPS Verified, and their nickname becomes just their
    lore name (no rank prefix). Best-effort — skips roles above the bot.
    """
    mark_bot_edit(member.id)  # loop-guard: bot-initiated role edit
    guild = member.guild
    bot_top = guild.me.top_role

    remove_ids = (
        set(config.COMPANY_ROLE_IDS.values())   # retinues + Court
        | set(config.RANK_ROLE_IDS.values())    # ladder + stations + specialised
        | {
            config.SEPARATOR_MILITARY_COMMAND, config.SEPARATOR_UPPER_COURT,
            config.SEPARATOR_COURT, config.SEPARATOR_STATION,
            config.SEPARATOR_RANK, config.SEPARATOR_RETINUE,
        }
        | {config.ROLE_STATION}
        | set(config.MILITARY_COMMAND_ROLE_IDS)
        | {config.ROLE_HOUSE_BARATHEON, config.ROLE_ENVOY}
    )
    to_remove = [
        r for r in member.roles
        if r.id in remove_ids and r < bot_top and not r.managed
    ]
    if to_remove:
        await member.remove_roles(*to_remove, reason="Discharge accepted")

    visitor = guild.get_role(config.ROLE_VISITOR)
    if visitor and visitor not in member.roles and visitor < bot_top and not visitor.managed:
        try:
            await member.add_roles(visitor, reason="Discharge — visitor standing")
        except discord.Forbidden:
            pass

    # Nickname: drop the rank prefix but keep the lore name.
    try:
        await member.edit(nick=(lorename[: config.NICKNAME_MAX] if lorename else None),
                          reason="Discharge — rank prefix removed")
    except (discord.Forbidden, discord.HTTPException):
        pass


def get_rank_role(guild: discord.Guild, rank: str) -> discord.Role | None:
    role_id = config.RANK_ROLE_IDS.get(rank)
    return guild.get_role(role_id) if role_id else None


def get_company_role(guild: discord.Guild, company: str) -> discord.Role | None:
    role_id = config.COMPANY_ROLE_IDS.get(company)
    return guild.get_role(role_id) if role_id else None
