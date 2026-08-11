"""
Role hygiene — enforces the Baratheon structural rules in real time and via
/cleanup_roles (which doubles as the migration pass):

Rule 1 — stations hold no ladder rank:
  Anyone holding a station (Corporal / Lieutenant / Captain / Clerk /
  Emissary / Secretary) has their retinue-ladder ranks (Levy … Man-at-Arms)
  removed. Knights of the Storm members may hold a ladder rank or not — the
  bot neither grants nor strips theirs.

Rule 2 — derived membership roles:
  • The "Court of Storm's End" role is auto-granted to anyone holding a court
    station (Clerk/Emissary/Secretary) and removed when no station is held.
  • The "Station" role is auto-granted to anyone holding ANY station
    (Corporal/Lieutenant/Captain/Clerk/Emissary/Secretary), removed likewise.
  Stations do NOT imply the Military Command separator — that follows only
  the four hand-given Command access roles.

Rule 3 — separators follow sections:
  Members get exactly the separators for the sections they hold roles in
  (config.SEPARATOR_TRIGGERS); the Util separator goes to everyone. Titles and
  High Command are managed BY HAND, as are the four Command ACCESS roles —
  the bot never grants those.

Report-only checks (surfaced by /cleanup_roles, never auto-fixed):
  • Officers (Corporal/Lieutenant/Captain) who don't hold the Knight rank —
    only knights may be officers (Stormguard members exempt: their Lieutenant
    is the Stormguard's own).
  • Retinue conflicts: Stormguard + a main retinue, Court + a main retinue,
    or both main retinues at once.

All logic is idempotent — once compliant, recomputing yields no changes, so
the bot never fights manual role edits (no coupling, ever).
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import audit_log
import config
import notion_service as ns
import util

log = logging.getLogger(__name__)

_LADDER_IDS = set(config.FLEET_RANK_ROLE_IDS)
_STATION_IDS = set(config.STATION_ROLE_IDS)
_COURT_STATION_IDS = set(config.COURT_STATION_ROLE_IDS)
_MAIN_RETINUE_IDS = {
    config.COMPANY_ROLE_IDS["Black Stags"],
    config.COMPANY_ROLE_IDS["Thunderhooves"],
}
_KNIGHT_ID = config.RANK_ROLE_IDS["Knight"]
_STORMGUARD_ID = config.COMPANY_ROLE_IDS["Stormguard"]
_MIL_STATION_IDS = {config.RANK_ROLE_IDS[r] for r in config.MILITARY_STATION_RANKS}


def compute_changes(member: discord.Member) -> tuple[set[int], set[int], list[str]]:
    """
    Pure rule evaluation. Returns (role ids to add, role ids to remove,
    report-only notes).
    """
    ids = {r.id for r in member.roles}
    add: set[int] = set()
    remove: set[int] = set()
    notes: list[str] = []

    # ── Rule 1: station holders lose ladder ranks ──
    if ids & _STATION_IDS:
        remove |= ids & _LADDER_IDS

    # ── Rule 2: Court membership derives from court stations ──
    if ids & _COURT_STATION_IDS:
        if config.ROLE_COURT not in ids:
            add.add(config.ROLE_COURT)
    elif config.ROLE_COURT in ids:
        remove.add(config.ROLE_COURT)

    # ── Rule 2b: the Station role derives from holding any station ──
    if ids & _STATION_IDS:
        if config.ROLE_STATION not in ids:
            add.add(config.ROLE_STATION)
    elif config.ROLE_STATION in ids:
        remove.add(config.ROLE_STATION)

    # ── Report-only: only knights may be (military) officers ──
    if ids & _MIL_STATION_IDS and _KNIGHT_ID not in ids and _STORMGUARD_ID not in ids:
        notes.append("holds an officer station without the Knight rank")

    # ── Report-only: retinue conflicts ──
    mains = ids & _MAIN_RETINUE_IDS
    if len(mains) > 1:
        notes.append("in BOTH main retinues")
    if _STORMGUARD_ID in ids and mains:
        notes.append("in the Stormguard AND a main retinue")
    if config.ROLE_COURT in ((ids - remove) | add) and mains:
        notes.append("in the Court AND a main retinue")

    # ── Rule 3: separators derive from the post-change role set ──
    effective = (ids - remove) | add
    for sep_id, triggers in config.SEPARATOR_TRIGGERS.items():
        if effective & triggers:
            if sep_id not in ids:
                add.add(sep_id)
        elif sep_id in ids:
            remove.add(sep_id)

    # Util separator: everyone has it.
    if config.SEPARATOR_UTIL not in ids:
        add.add(config.SEPARATOR_UTIL)

    return add, remove, notes


def _assignable(guild: discord.Guild, role_ids: set[int]) -> list[discord.Role]:
    bot_top = guild.me.top_role
    out = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role and role < bot_top and not role.managed:
            out.append(role)
    return out


async def apply_changes(member: discord.Member, add: set[int], remove: set[int], reason: str) -> bool:
    """
    Apply computed changes (best-effort). Returns True if anything changed.
    Adds and removals are combined into ONE role edit per member — Discord
    rate-limits member role updates hard (~10/10s per guild).
    """
    guild = member.guild
    to_add = [r for r in _assignable(guild, add) if r not in member.roles]
    to_remove = [r for r in _assignable(guild, remove) if r in member.roles]
    if not to_add and not to_remove:
        return False
    removed_ids = {r.id for r in to_remove}
    new_roles = [r for r in member.roles if r.id not in removed_ids] + to_add
    try:
        await member.edit(roles=new_roles, reason=reason)
    except discord.HTTPException as exc:
        log.warning("role_hygiene: couldn't update %s: %s", member, exc)
        return False
    return True


class RoleHygieneCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Real-time enforcement ────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id != config.GUILD_ID:
            return
        if {r.id for r in before.roles} == {r.id for r in after.roles}:
            return  # nick/status change, not roles

        add, remove, _ = compute_changes(after)
        if add or remove:
            await apply_changes(after, add, remove, "Role hygiene")

    # ── /cleanup_roles — the full-server (migration) pass ────────────────

    @app_commands.command(
        name="cleanup_roles",
        description="[Ruler] Enforce separators, station & Court rules across the whole server (dry-run first).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(dry_run="Preview only (default). Set to False to apply.")
    async def cleanup_roles(self, interaction: discord.Interaction, dry_run: bool = True):
        if not util.is_ruler(interaction.user):
            await interaction.response.send_message(
                "❌ Restricted to the Heir, Lady, and Lord of Storm's End.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Notion side-check: rows still carrying a station/court rank whose
        # Discord role the member no longer holds (sync never overwrites
        # manual ranks, so these always need a human decision).
        stale_map: dict[str, list[tuple[str, str]]] = {}
        try:
            for page in await ns.get_all_active_members():
                stats = ns.extract_member_stats(page["properties"])
                if stats["discord_user_id"] and stats["rank"] in config.OFFICER_RANKS:
                    stale_map.setdefault(stats["discord_user_id"], []).append(
                        (stats["detachment"], stats["rank"])
                    )
        except Exception as exc:
            log.warning("cleanup_roles: Notion stale-rank check skipped: %s", exc)

        touched = errors = 0
        flagged: list[str] = []
        preview: list[str] = []

        async for member in guild.fetch_members(limit=None):
            try:
                add, remove, notes = compute_changes(member)
                ids = {r.id for r in member.roles}
                for det, rank in stale_map.get(str(member.id), []):
                    rid = config.RANK_ROLE_IDS.get(rank)
                    if rid and rid not in ids:
                        notes = notes + [
                            f"Notion {det or '—'} row says {rank} but they don't hold that role"
                        ]
                for note in notes:
                    flagged.append(f"{member} (`{member.id}`) — {note}")
                if not add and not remove:
                    continue

                touched += 1
                if len(preview) < 30:
                    added_names = ", ".join(
                        r.name for rid in sorted(add) if (r := guild.get_role(rid))
                    )
                    removed_names = ", ".join(
                        r.name for rid in sorted(remove) if (r := guild.get_role(rid))
                    )
                    parts = []
                    if added_names:
                        parts.append(f"+[{added_names}]")
                    if removed_names:
                        parts.append(f"−[{removed_names}]")
                    preview.append(f"• {member.display_name}: " + " ".join(parts))

                if not dry_run:
                    await apply_changes(member, add, remove, "/cleanup_roles")
                    # One role edit per second stays inside Discord's per-guild
                    # member-update budget without tripping the rate limiter.
                    await asyncio.sleep(1.0)
            except Exception as exc:
                errors += 1
                log.error("cleanup_roles: failed for %s: %s", member, exc)

        mode = "🔎 DRY RUN — nothing changed" if dry_run else "✅ Cleanup applied"
        msg = (
            f"**{mode}**\n"
            f"Members needing changes: **{touched}**\n"
            f"Errors: **{errors}**"
        )
        if preview:
            msg += "\n\n__Preview (first 30):__\n" + "\n".join(preview)
        if dry_run:
            msg += "\n\nRun `/cleanup_roles dry_run:False` to apply."

        # Long runs can outlive the interaction's 15-minute reply window — fall
        # back to the audit-log channel so the report is never lost.
        async def _report(text: str):
            try:
                await interaction.followup.send(text, ephemeral=True)
            except discord.HTTPException:
                await audit_log.log_event(
                    self.bot, title="🧽 /cleanup_roles report",
                    description=text[:4000], color=discord.Color.dark_gold(),
                )

        await _report(msg[:1990])

        if flagged:
            chunk = (
                f"⚠️ **{len(flagged)} structural issue(s) to resolve by hand** "
                "(the bot reports these but never auto-fixes them):\n"
            )
            for line in flagged:
                if len(chunk) + len(line) + 3 > 1900:
                    await _report(chunk)
                    chunk = ""
                chunk += f"\n• {line}"
            if chunk.strip():
                await _report(chunk)

        if not dry_run:
            await audit_log.log_event(
                self.bot,
                title="🧽 /cleanup_roles executed",
                color=discord.Color.dark_gold(),
                fields=[
                    ("Admin", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                    ("Members changed", str(touched), True),
                    ("Flagged for review", str(len(flagged)), True),
                ],
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleHygieneCog(bot))
