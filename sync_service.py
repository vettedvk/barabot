"""
sync_service.py — Discord→Notion reconciliation (the heart of the bot).

Discord roles are the source of truth. The bot reads a member's roles and makes
the Notion roster match, WITHOUT ever changing Discord roles. Both the manual
/sync command and the periodic worker call reconcile().

Model (Option A — one roster row per thing a member belongs to):
  • A member gets one row per DETACHMENT they hold a role for (Black Stags,
    Thunderhooves, Stormguard, Knights of the Storm, Court). Knights of the
    Storm members keep their main retinue, so two rows is their norm;
    Stormguard and Court members hold only their own row.
  • Command members (Council of Storm's End and ABOVE) additionally get a
    "High Command" row carrying their council rank.
  • Officers (Corporal and above) are manually ranked and don't earn points —
    the sync still mirrors their rank from Discord, it just never recomputes it.

reconcile() therefore, per member:
  • absent from the guild  → archive ALL their active rows + log it (abandoned).
  • present                → make their set of active rows match the set of
    detachments/command implied by their roles: create missing rows (points
    seeded to the rank's minimum so the points engine won't demote them),
    update a row whose rank drifted, and archive rows for detachments they no
    longer belong to.
"""

import asyncio
import logging
from datetime import datetime

import discord

import audit_log
import config
import notion_service as ns
import role_service
from rank_engine import min_stats_for_rank

log = logging.getLogger(__name__)

# Rank assigned when a member holds a detachment role but no rank role within it.
STARTING_RANK = {
    "Stormbreakers":        "Levy",
    "Thunderhooves":        "Levy",
    "The Black Stags":      "Knight Banneret",
    "Stormguard":           "Squire",
    "Knights of the Storm": "Squire",
    "Court":                "Clerk",
    "High Command":         "Council of Storm's End",
}

# Order used when one "primary" detachment must be picked (import / display).
_PRIORITY = {"Stormbreakers": 0, "Thunderhooves": 1,
             "The Black Stags": 3, "Stormguard": 4, "Knights of the Storm": 5,
             "Court": 6, "High Command": 7}

_DETACHMENTS = ("Stormbreakers", "Thunderhooves", "The Black Stags",
                "Stormguard", "Knights of the Storm", "Court")


def lorename_from_nick(nick: str) -> str:
    """
    Derive a lorename from a Discord nickname formatted '{rank}, {forename
    surname}' — drops everything up to and including the first comma; if
    there's no comma, the whole nickname is the lorename. (Same derivation
    /import_roster used to build the roster.)
    """
    nick = (nick or "").strip()
    if "," in nick:
        return nick.split(",", 1)[1].strip()
    return nick


def is_command(member: discord.Member) -> bool:
    """True if the member is Council of Storm's End or above (gets a High Command row)."""
    return any(r.id in config.COMMAND_ROLE_IDS for r in member.roles)


def _highest_rank_in(member_role_ids: set, guild: discord.Guild, rank_names: list[str]):
    """
    Return the highest-position rank role (from rank_names) the member holds, or
    None if they hold none. None means "Discord gives no rank signal for this
    detachment" — e.g. a detachment head whose standing is a council title, not a
    rank role — and the caller must NOT clobber an existing manual rank.
    """
    held = [
        (name, guild.get_role(config.RANK_ROLE_IDS[name]).position)
        for name in rank_names
        if config.RANK_ROLE_IDS.get(name) in member_role_ids
        and guild.get_role(config.RANK_ROLE_IDS[name])
    ]
    return max(held, key=lambda x: x[1])[0] if held else None


def derive_detachment_rows(member: discord.Member, guild: discord.Guild) -> list[tuple[str, str | None]]:
    """
    Return every (detachment, rank) the member should have a roster row for —
    one per detachment role held, plus a High Command row if they're command.
    `rank` is None when the member holds the detachment role but no rank role in
    it (sync then preserves whatever rank is already in Notion).
    """
    ids = {r.id for r in member.roles}
    rows: list[tuple[str, str | None]] = []
    for det in _DETACHMENTS:
        rid = config.COMPANY_ROLE_IDS.get(det)
        if rid and rid in ids:
            rows.append((det, _highest_rank_in(ids, guild, config.DETACHMENT_RANKS[det])))
    if is_command(member):
        council = _highest_rank_in(ids, guild, config.DETACHMENT_RANKS["High Command"]) or "Council of Storm's End"
        rows.append(("High Command", council))
    return rows


def derive_detachment_and_rank(member: discord.Member, guild: discord.Guild):
    """Single 'primary' (detachment, rank) — used by /import_roster and display."""
    rows = derive_detachment_rows(member, guild)
    if not rows:
        return None, None
    rows.sort(key=lambda dr: _PRIORITY.get(dr[0], 9))
    det, rank = rows[0]
    return det, (rank or STARTING_RANK.get(det, "Levy"))


def _enlist_date(props: dict) -> datetime | None:
    """Read an existing 'Date Enlisted' so created/transferred rows keep it."""
    start = (props.get("Date Enlisted", {}).get("date") or {}).get("start")
    try:
        return datetime.fromisoformat(start) if start else None
    except ValueError:
        return None


async def reconcile(guild: discord.Guild, bot: discord.Client) -> dict:
    """One full Discord→Notion pass. Returns a summary of counts.

    summary["stale_station"] lists members whose Notion row still carries a
    station/court rank whose Discord role they no longer hold — sync
    deliberately never clobbers manual ranks, so these need a human decision
    (change the Discord rank role, or a hand edit in Notion)."""
    summary = {"created": 0, "rank_updated": 0, "archived": 0, "abandoned": 0,
               "skipped": 0, "errors": 0, "lorename_updated": 0, "stale_station": []}

    pages = await ns.get_all_active_members()
    by_uid: dict[str, list] = {}
    for page in pages:
        stats = ns.extract_member_stats(page["properties"])
        uid = stats["discord_user_id"]
        if uid:
            by_uid.setdefault(uid, []).append((page, stats))
        else:
            summary["skipped"] += 1

    for uid, rows in by_uid.items():
        try:
            member = guild.get_member(int(uid))

            # Abandoned: every active row for a member who has left the guild.
            if member is None:
                for page, _ in rows:
                    await ns.archive_member(page["id"], "Abandoned")
                    await asyncio.sleep(0.34)
                summary["abandoned"] += 1
                await _log_abandoned(bot, uid, rows[0][1], rows[0][0]["id"])
                continue

            # Flag rows whose station/court rank no longer matches a held role —
            # sync preserves manual ranks, so it will never fix these itself.
            # The page_id rides along so /sync can offer to clear the rank.
            member_role_ids = {r.id for r in member.roles}
            for row_page, row_stats in rows:
                if row_stats["rank"] in config.OFFICER_RANKS:
                    rid = config.RANK_ROLE_IDS.get(row_stats["rank"])
                    if rid and rid not in member_role_ids:
                        summary["stale_station"].append({
                            "page_id": row_page["id"],
                            "label": f"{member} — {row_stats['detachment'] or '—'} / {row_stats['rank']}",
                            "text": (
                                f"{member} (`{member.id}`) — {row_stats['detachment'] or '—'} "
                                f"row says **{row_stats['rank']}** but they no longer hold that role"
                            ),
                        })

            desired = derive_detachment_rows(member, guild)
            if not desired:
                summary["skipped"] += 1  # holds no recognised roles — leave their rows alone
                continue

            desired_by_det = dict(desired)
            existing_by_det: dict[str, list] = {}
            for page, stats in rows:
                existing_by_det.setdefault(stats["detachment"], []).append((page, stats))

            identity = rows[0][1]
            enlisted = _enlist_date(rows[0][0]["properties"])
            changed = False

            # 0) Lorename check — the server nickname (minus any "{rank}, "
            #    prefix) is authoritative, same derivation as /import_roster.
            #    Members with NO server nickname are skipped so a bare Discord
            #    username never overwrites a real lore name.
            derived_lore = lorename_from_nick(member.nick) if member.nick else ""
            if derived_lore and derived_lore != identity["lorename"]:
                for row_page, _rs in rows:
                    await ns.update_roster_identity(row_page["id"], lorename=derived_lore)
                    await asyncio.sleep(0.34)
                identity = dict(identity, lorename=derived_lore)
                summary["lorename_updated"] += 1
                changed = True

            # 1) Archive rows for detachments the member no longer belongs to.
            for det, plist in existing_by_det.items():
                if det not in desired_by_det:
                    for page, _ in plist:
                        await ns.archive_page(page["id"])
                        summary["archived"] += 1
                        changed = True
                        await asyncio.sleep(0.34)

            # 2) Ensure each desired detachment has one row at the right rank.
            for det, rank in desired:
                plist = existing_by_det.get(det)
                if plist:
                    page, stats = plist[0]
                    # rank is None when Discord gives no rank role for this
                    # detachment (e.g. a detachment head whose standing is a
                    # council title) — leave the manually-set Notion rank alone.
                    if rank is not None and stats["rank"] != rank:
                        await ns.set_member_rank(page["id"], rank)
                        # A hand-edited Discord role that bumps a member up the
                        # ladder is a promotion too — congratulate them.
                        await role_service.announce_promotion(member, rank, stats["rank"])
                        summary["rank_updated"] += 1
                        changed = True
                        await asyncio.sleep(0.34)
                    continue

                # Missing row — create it (seed points to the rank minimum).
                # Fall back to the detachment's starting rank only on creation.
                create_rank = rank or STARTING_RANK.get(det, "Levy")
                seed = min_stats_for_rank(det, create_rank)
                await ns.create_imported_member(
                    roblox_username=identity["roblox_username"],
                    roblox_id=identity["roblox_id"],
                    lorename=identity["lorename"],
                    discord_username=str(member),
                    discord_user_id=uid,
                    detachment=det,
                    rank=create_rank,
                    points=seed["points"],
                    combat_trainings=seed["combat_trainings"],
                    joints=seed["joints"],
                    prs=seed["prs"],
                    basic_levy=seed.get("basic_levy", False),
                    date_enlisted=enlisted,
                )
                summary["created"] += 1
                changed = True
                await asyncio.sleep(0.34)

            if changed:
                await audit_log.log_event(
                    bot, title="⚙️ Roster synced from Discord", color=discord.Color.teal(),
                    fields=[
                        ("Member", f"{member.mention} (`{member.id}`)", True),
                        ("Now holds", (", ".join(f"{d} / {r or 'manual rank'}" for d, r in desired))[:1024], False),
                    ],
                )

        except Exception as exc:
            summary["errors"] += 1
            log.error("reconcile: error for uid %s: %s", uid, exc)

    return summary


async def reconcile_member(guild: discord.Guild, bot: discord.Client,
                           member: discord.Member) -> dict:
    """
    Discord-authority upsert for ONE member — called from on_member_update when a
    member's rank/detachment roles change. Discord is the source of truth for
    rank and detachment: this makes the member's Notion rows match their current
    roles.

      • No roster entry at all → create one from their Discord ID (identity is
        minimal — lorename from their nickname, blank Roblox — so the Saturday
        missing-field sweep will prompt them to fill the rest in).
      • Rank drifted on a detachment they still hold → update it (and announce a
        genuine ladder promotion).
      • A detachment they no longer hold a role for → archive that row.

    Never DMs — bulk role changes shouldn't spam members; missing fields are
    chased once a week by the Saturday sweep. Returns a small summary dict.
    """
    summary = {"created": 0, "rank_updated": 0, "archived": 0, "lorename_updated": 0, "errors": 0}
    uid = str(member.id)

    desired = derive_detachment_rows(member, guild)
    pages = await ns.get_members_by_discord_id(uid)
    rows = [(p, ns.extract_member_stats(p["properties"])) for p in pages]

    # No recognised roles held: don't touch anything. A fully-stripped role set
    # is more likely a transient mid-edit state than an intentional wipe, and
    # discharge has its own path. Leave existing rows for a human/the sweep.
    if not desired:
        return summary

    desired_by_det = dict(desired)
    existing_by_det: dict[str, list] = {}
    for page, stats in rows:
        existing_by_det.setdefault(stats["detachment"], []).append((page, stats))

    if rows:
        identity = rows[0][1]
        enlisted = _enlist_date(rows[0][0]["properties"])
    else:
        # Brand-new manual entry: seed identity from Discord (blank Roblox — the
        # Saturday sweep will ask the member to complete it).
        identity = {
            "roblox_username": "", "roblox_id": "",
            "lorename": lorename_from_nick(member.nick) if member.nick else "",
        }
        enlisted = None

    try:
        # 0) Lorename check — the server nickname (minus any "{rank}, " prefix)
        #    is authoritative. Push it to EVERY row so no entry keeps a stale
        #    name. Members with no nickname are skipped so a bare Discord
        #    username never overwrites a real lore name.
        derived_lore = lorename_from_nick(member.nick) if member.nick else ""
        if derived_lore and derived_lore != identity["lorename"]:
            for row_page, _rs in rows:
                await ns.update_roster_identity(row_page["id"], lorename=derived_lore)
                await asyncio.sleep(0.34)
            identity = dict(identity, lorename=derived_lore)
            summary["lorename_updated"] += 1

        # 1) Archive rows for detachments the member no longer belongs to.
        for det, plist in existing_by_det.items():
            if det and det not in desired_by_det:
                for page, _ in plist:
                    await ns.archive_page(page["id"])
                    summary["archived"] += 1
                    await asyncio.sleep(0.34)

        # 2) Ensure each desired detachment has one row at the right rank.
        for det, rank in desired:
            plist = existing_by_det.get(det)
            if plist:
                page, stats = plist[0]
                # rank is None when Discord gives no rank role for this
                # detachment — leave the manually-set Notion rank alone.
                if rank is not None and stats["rank"] != rank:
                    await ns.set_member_rank(page["id"], rank)
                    await role_service.announce_promotion(member, rank, stats["rank"])
                    summary["rank_updated"] += 1
                    await asyncio.sleep(0.34)
                continue

            # Missing row — create it. Per-rank points model: a manually-ranked
            # member starts their current rank fresh at 0 in-rank points.
            create_rank = rank or STARTING_RANK.get(det, "Levy")
            await ns.create_imported_member(
                roblox_username=identity["roblox_username"],
                roblox_id=identity["roblox_id"],
                lorename=identity["lorename"],
                discord_username=str(member),
                discord_user_id=uid,
                detachment=det,
                rank=create_rank,
                points=0,
                basic_levy=(create_rank != "Levy"),
                date_enlisted=enlisted,
            )
            summary["created"] += 1
            await asyncio.sleep(0.34)

        if (summary["created"] or summary["rank_updated"] or summary["archived"]
                or summary["lorename_updated"]):
            await audit_log.log_event(
                bot, title="⚙️ Roster synced from Discord (live)", color=discord.Color.teal(),
                fields=[
                    ("Member", f"{member.mention} (`{member.id}`)", True),
                    ("Now holds",
                     (", ".join(f"{d} / {r or 'manual rank'}" for d, r in desired))[:1024], False),
                    ("Changes",
                     f"created {summary['created']}, rank {summary['rank_updated']}, "
                     f"archived {summary['archived']}, lorename {summary['lorename_updated']}", True),
                ],
            )
    except Exception as exc:
        summary["errors"] += 1
        log.error("reconcile_member: error for %s: %s", uid, exc)

    return summary


async def _log_abandoned(bot, uid: str, stats: dict, page_id: str) -> None:
    """Post the 'Member Missing From Server' embed for an abandoned post."""
    channel = bot.get_channel(config.CHANNEL_ABANDONMENT_LOG)
    if channel is None:
        return
    embed = discord.Embed(title="⚠️ Member Missing From Server (caught by sync)",
                          color=discord.Color.dark_red())
    embed.add_field(name="User ID", value=f"`{uid}`", inline=True)
    embed.add_field(name="Lore Name", value=stats.get("lorename") or "—", inline=True)
    embed.add_field(name="Action", value="All active rows marked **Abandoned** and archived.", inline=False)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
