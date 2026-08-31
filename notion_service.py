"""
Notion service — all Notion I/O goes through this module.
Notion is the single source of truth.
"""

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from notion_client import AsyncClient

import config
import roster_cache


_notion: Optional[AsyncClient] = None

# Cache of the roster DB's select options (name -> last fetch). Keyed by property
# name; refreshed at most every _SCHEMA_TTL seconds so autocomplete stays cheap.
_schema_cache: dict[str, tuple[float, list[str]]] = {}
_SCHEMA_TTL = 300.0


async def get_select_options(property_name: str, force: bool = False) -> list[str]:
    """Return the option names of a select property on the roster DB (cached)."""
    now = time.time()
    cached = _schema_cache.get(property_name)
    if cached and not force and now - cached[0] < _SCHEMA_TTL:
        return cached[1]
    nc = get_client()
    db = await nc.databases.retrieve(database_id=os.environ["NOTION_ROSTER_DB_ID"])
    prop = db.get("properties", {}).get(property_name, {}) or {}
    options = [o["name"] for o in (prop.get("select", {}) or {}).get("options", [])]
    _schema_cache[property_name] = (now, options)
    return options


def get_client() -> AsyncClient:
    """Return the lazily-created shared Notion client (one per process)."""
    global _notion
    if _notion is None:
        _notion = AsyncClient(auth=os.environ["NOTION_TOKEN"])
    return _notion


async def _query_all(database_id: str, query_filter: dict | None = None, sorts: list | None = None) -> list[dict]:
    """
    Return EVERY page in a database, transparently following Notion's pagination
    cursor. This is the single implementation behind all the get_all_* helpers
    below (which previously each carried their own identical while-loop).
    """
    nc = get_client()
    results: list[dict] = []
    cursor = None
    while True:
        kwargs: dict = {"database_id": database_id}
        if query_filter:
            kwargs["filter"] = query_filter
        if sorts:
            kwargs["sorts"] = sorts
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = await nc.databases.query(**kwargs)
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            return results
        cursor = resp.get("next_cursor")


def _roster_db() -> str:
    return os.environ["NOTION_ROSTER_DB_ID"]


async def _update_and_invalidate(page_id: str, properties: dict, *, archived: bool | None = None) -> None:
    """Write a roster page and drop it from the hot layer (write-through by
    invalidation) so the next read refetches fresh from Notion. Every roster
    write goes through here so no update path can leave the cache stale."""
    nc = get_client()
    kwargs: dict = {"page_id": page_id, "properties": properties}
    if archived is not None:
        kwargs["archived"] = archived
    await nc.pages.update(**kwargs)
    roster_cache.invalidate_page(page_id)


# ── Roster helpers ─────────────────────────────────────────────────────────

async def get_page(page_id: str) -> dict:
    """Retrieve a single Notion page by ID (used to recover review data after restart)."""
    nc = get_client()
    return await nc.pages.retrieve(page_id=page_id)


async def get_member_by_discord_id(discord_id: str) -> Optional[dict]:
    """Return the first matching roster page dict, or None."""
    nc = get_client()
    resp = await nc.databases.query(
        database_id=os.environ["NOTION_ROSTER_DB_ID"],
        filter={
            "property": "Discord User ID",
            "rich_text": {"equals": str(discord_id)},
        },
    )
    results = resp.get("results", [])
    return results[0] if results else None


async def get_members_by_discord_id(discord_id: str) -> list[dict]:
    """Return ALL (non-archived) roster pages for a Discord ID — a member may
    hold several (e.g. command staff across multiple detachments).

    Served from the in-memory hot layer when warm; a miss (or a member with no
    rows — empty results are never cached) falls through to Notion and warms it."""
    uid = str(discord_id)
    cached = roster_cache.get(uid)
    if cached is not None:
        return cached
    pages = await _query_all(
        _roster_db(),
        {"property": "Discord User ID", "rich_text": {"equals": uid}},
    )
    roster_cache.put(uid, pages)
    return pages


async def refresh_roster_cache() -> int:
    """Rebuild the roster hot layer from a fresh Notion snapshot (all non-archived
    rows, grouped by Discord ID). Picks up rows added/edited directly in Notion.
    Returns the number of members cached."""
    by_uid: dict[str, list[dict]] = {}
    for page in await _query_all(_roster_db()):
        uid = _get_text(page["properties"], "Discord User ID")
        if uid:
            by_uid.setdefault(uid, []).append(page)
    roster_cache.replace_all(by_uid)
    return len(by_uid)


async def get_fleet_member_by_discord_id(discord_id: str) -> Optional[dict]:
    """
    Return the member's MAIN-RETINUE roster row (Black Stags/Thunderhooves)
    when they have one, else their first row, else None. Event points and the
    auto rank ladder live on main-retinue rows, so point-granting flows target
    this row — Stormguard/Knights/Court rows carry manual ranks.
    """
    pages = await get_members_by_discord_id(str(discord_id))
    if not pages:
        return None
    for page in pages:
        det = ((page["properties"].get("Detachment", {}) or {}).get("select") or {}).get("name", "")
        if det in config.MAIN_COMBAT_DETACHMENTS:
            return page
    return pages[0]


async def create_member(
    roblox_username: str,
    roblox_id: str,
    lorename: str,
    discord_username: str,
    discord_user_id: str,
    detachment: str = "",
    rank: str = "Levy",
) -> dict:
    """Create a new roster page for a new enlistee (0 pts, starting rank Levy).
    A blank detachment means an unsorted Levy — placed after Basic Levy Training."""
    nc = get_client()
    props = {
        "Username":          _title(roblox_username),
        "Roblox ID":         _text(roblox_id),
        "Lorename":          _text(lorename),
        "Discord Username":  _text(discord_username),
        "Discord User ID":   _text(str(discord_user_id)),
        "Rank":              _select(rank),
        "Event Points":      _number(0),
        "Combat Trainings":  _number(0),
        "Joints":            _number(0),
        "Skirmishes":        _number(0),
        "PRs":               _number(0),
        "Status":            _select("Active"),
        "Date Enlisted":     _date(datetime.now(timezone.utc)),
        config.BASIC_LEVY_FIELD: _checkbox(False),
        "Days Served":       _number(0),
    }
    if detachment:
        props["Detachment"] = _select(detachment)
    page = await nc.pages.create(
        parent={"database_id": os.environ["NOTION_ROSTER_DB_ID"]}, properties=props)
    roster_cache.invalidate_uid(str(discord_user_id))
    return page


async def apply_approved_points(
    page_id: str,
    current_props: dict,
    added_points: int,
    event_type: str,
    new_rank: str,
) -> None:
    """
    Add points, increment the correct attendance counter (or tick the Basic
    Levy Training checkbox), refresh Days Served, and set rank.
    current_props: the raw Notion properties dict from the member page.
    """
    nc = get_client()

    old_points = _get_number(current_props, "Event Points")
    new_points = old_points + added_points

    props: dict = {
        "Event Points": _number(new_points),
        "Rank":         _select(new_rank),
        "Days Served":  _number(days_served_value(current_props)),
    }
    if event_type == config.BASIC_LEVY_EVENT:
        props[config.BASIC_LEVY_FIELD] = _checkbox(True)
    else:
        counter_field = config.EVENT_COUNTER_FIELDS.get(event_type)
        if counter_field:
            old_count = _get_number(current_props, counter_field)
            props[counter_field] = _number(old_count + 1)

    await _update_and_invalidate(page_id, props)


async def apply_event_result(
    page_id: str,
    current_props: dict,
    new_points: int,
    event_type: str,
    new_rank: str,
) -> None:
    """
    Per-rank points model. Unlike apply_approved_points (which ADDED to a
    cumulative career total), this SETS 'Event Points' to `new_points` — the
    in-rank remainder after any promotions the caller already resolved — and
    sets the (possibly promoted) rank. Still increments the attendance counter
    (or ticks the Basic Levy Training checkbox) and refreshes Days Served.
    """
    nc = get_client()
    props: dict = {
        "Event Points": _number(max(0, new_points)),
        "Rank":         _select(new_rank),
        "Days Served":  _number(days_served_value(current_props)),
    }
    if event_type == config.BASIC_LEVY_EVENT:
        props[config.BASIC_LEVY_FIELD] = _checkbox(True)
    else:
        counter_field = config.EVENT_COUNTER_FIELDS.get(event_type)
        if counter_field:
            old_count = _get_number(current_props, counter_field)
            props[counter_field] = _number(old_count + 1)
    await _update_and_invalidate(page_id, props)


async def set_member_rank(page_id: str, rank: str) -> None:
    await _update_and_invalidate(page_id, {"Rank": _select(rank)})


async def clear_member_rank(page_id: str) -> None:
    """Empty a roster row's Rank select — used when an admin confirms that a
    stale station rank (role no longer held in Discord) should be removed."""
    await _update_and_invalidate(page_id, {"Rank": {"select": None}})


async def set_member_company(page_id: str, company: str, rank: str,
                             reset_points: bool = False) -> None:
    props = {
        "Detachment": _select(company),
        "Rank":       _select(rank),
    }
    # Per-rank points: on placement (Levy → Soldier) the member starts their new
    # rank fresh, so any points banked as an unsorted Levy are cleared.
    if reset_points:
        props["Event Points"] = _number(0)
    await _update_and_invalidate(page_id, props)


async def archive_member(page_id: str, status: str) -> None:
    """Mark member Abandoned/Discharged and archive the Notion page."""
    await _update_and_invalidate(page_id, {"Status": _select(status)}, archived=True)


async def discharge_member(page_id: str) -> None:
    await archive_member(page_id, "Discharged")


async def set_member_status(page_id: str, status: str) -> None:
    """
    Set a roster row's Status select WITHOUT archiving the page. Used for LOA
    (member goes on leave, then back to Active) — unlike archive_member, which
    is for permanent Discharged/Abandoned exits.
    """
    await _update_and_invalidate(page_id, {"Status": _select(status)})


async def set_member_loa(page_id: str, until: date) -> None:
    """Put a roster row on LOA and stamp its auto-expiry date."""
    await _update_and_invalidate(page_id, {
        "Status": _select(config.LOA_STATUS),
        "LOA Until": {"date": {"start": until.isoformat()}},
    })


async def get_members_on_loa() -> list[dict]:
    """Every roster row currently marked LOA (not archived)."""
    return await _query_all(_roster_db(), {"property": "Status", "select": {"equals": config.LOA_STATUS}})


def member_loa_until(props: dict) -> Optional[date]:
    """Parse a row's 'LOA Until' date, or None if unset/invalid."""
    start = (props.get("LOA Until", {}).get("date") or {}).get("start")
    if not start:
        return None
    try:
        return date.fromisoformat(start[:10])
    except ValueError:
        return None


async def restore_member_from_loa(page_id: str) -> None:
    """Return a row to Active and clear its LOA expiry date."""
    await _update_and_invalidate(page_id, {
        "Status": _select("Active"),
        "LOA Until": {"date": None},
    })


async def reactivate_member(
    page_id: str,
    new_discord_username: str,
    detachment: str = "",
    rank: str = "Levy",
) -> None:
    """Unarchive and reset a prior member for re-enlistment. A blank detachment
    leaves them unsorted (placed after Basic Levy Training)."""
    nc = get_client()
    props = {
        "Status":           _select("Active"),
        "Discord Username": _text(new_discord_username),
        "Event Points":     _number(0),
        "Combat Trainings": _number(0),
        "Joints":           _number(0),
        "Skirmishes":       _number(0),
        "PRs":              _number(0),
        "Rank":             _select(rank),
        "Date Enlisted":    _date(datetime.now(timezone.utc)),
        config.BASIC_LEVY_FIELD: _checkbox(False),
        "Days Served":      _number(0),
    }
    props["Detachment"] = _select(detachment) if detachment else {"select": None}
    await _update_and_invalidate(page_id, props, archived=False)


async def get_all_active_members() -> list[dict]:
    """Return all Active roster pages (used by the sync worker)."""
    return await _query_all(_roster_db(), {"property": "Status", "select": {"equals": "Active"}})


async def get_all_roster_pages() -> list[dict]:
    """Return every page in the roster DB, regardless of status (for /clear_roster)."""
    return await _query_all(_roster_db())


# ── Roster V2 migration (new combat-role structure) ─────────────────────────
# One-off: copy the LEGACY roster (NOTION_ROSTER_LEGACY_DB_ID) into the now-active
# roster (NOTION_ROSTER_DB_ID = V2), one row per member, WITHOUT a detachment.

async def get_legacy_roster_pages() -> list[dict]:
    """Every non-archived page in the legacy roster (migration source)."""
    db_id = os.environ.get("NOTION_ROSTER_LEGACY_DB_ID")
    if not db_id:
        return []
    return await _query_all(db_id)


async def get_roster_v2_discord_ids() -> set[str]:
    """Discord IDs already present in the active (V2) roster."""
    ids = set()
    for page in await _query_all(_roster_db()):
        uid = _get_text(page["properties"], "Discord User ID")
        if uid:
            ids.add(uid)
    return ids


async def create_roster_v2_member(
    *, roblox_username: str, roblox_id: str, discord_user_id: str,
    discord_username: str, lorename: str, rank: str, status: str,
    points: int, combat_trainings: int, joints: int,
    prs: int, skirmishes: int, days_served: int, date_enlisted: str,
    basic_levy: bool,
) -> None:
    """Create one UNSORTED member row (no Detachment) in the active roster."""
    db_id = _roster_db()
    nc = get_client()
    props = {
        "Username":         _title(roblox_username or ""),
        "Roblox ID":        _text(roblox_id or ""),
        "Discord User ID":  _text(discord_user_id),
        "Discord Username": _text(discord_username or ""),
        "Lorename":         _text(lorename or ""),
        "Status":           _select(status or "Active"),
        "Event Points":     _number(points),
        "Combat Trainings": _number(combat_trainings),
        "Joints":           _number(joints),
        "PRs":              _number(prs),
        "Skirmishes":       _number(skirmishes),
        "Days Served":      _number(days_served),
        "Basic Levy Training": _checkbox(basic_levy),
    }
    if rank:
        props["Rank"] = _select(rank)
    if date_enlisted:
        props["Date Enlisted"] = {"date": {"start": date_enlisted[:10]}}
    await nc.pages.create(parent={"database_id": db_id}, properties=props)
    roster_cache.invalidate_uid(str(discord_user_id))


async def archive_page(page_id: str) -> None:
    """Archive (trash) a Notion page without altering its properties."""
    await get_client().pages.update(page_id=page_id, archived=True)
    roster_cache.invalidate_page(page_id)


async def get_all_tracking_members() -> list[dict]:
    """Return all rows from the legacy Military Tracking DB (one-off migration)."""
    return await _query_all(config.NOTION_MILITARY_TRACKING_DB_ID)


async def update_roster_identity(
    page_id: str,
    *,
    lorename: str | None = None,
    roblox_id: str | None = None,
    roblox_username: str | None = None,
) -> None:
    """Set any of Lorename / Roblox ID / Username on a roster page (migration use)."""
    props: dict = {}
    if lorename is not None:
        props["Lorename"] = _text(lorename)
    if roblox_id is not None:
        props["Roblox ID"] = _text(roblox_id)
    if roblox_username is not None:
        props["Username"] = _title(roblox_username)
    if props:
        await _update_and_invalidate(page_id, props)


async def get_all_roster_discord_ids() -> set:
    """Return the set of Discord User IDs already present in the roster (any status)."""
    pages = await _query_all(_roster_db())
    return {did for p in pages if (did := _get_text(p["properties"], "Discord User ID"))}


async def create_imported_member(
    roblox_username: str,
    roblox_id: str,
    lorename: str,
    discord_username: str,
    discord_user_id: str,
    detachment: str,
    rank: str,
    points: int = 0,
    combat_trainings: int = 0,
    joints: int = 0,
    skirmishes: int = 0,
    prs: int = 0,
    basic_levy: bool = False,
    date_enlisted: "datetime | None" = None,
) -> dict:
    """
    Create a roster row for a member migrated from the old bot. Event Points and
    per-type attendance counters are seeded to the minimums that justify the
    member's rank (see rank_engine.min_stats_for_rank) so the sync worker won't
    demote them; they default to 0 for manual/leadership ranks.
    date_enlisted is stored as a date with NO time (defaults to today if omitted).
    """
    enlisted = date_enlisted or datetime.now(timezone.utc)
    nc = get_client()
    page = await nc.pages.create(
        parent={"database_id": os.environ["NOTION_ROSTER_DB_ID"]},
        properties={
            "Username":          _title(roblox_username),
            "Roblox ID":         _text(roblox_id),
            "Lorename":          _text(lorename),
            "Discord Username":  _text(discord_username),
            "Discord User ID":   _text(str(discord_user_id)),
            "Detachment":        _select(detachment),
            "Rank":              _select(rank),
            "Event Points":      _number(points),
            "Combat Trainings":  _number(combat_trainings),
            "Joints":            _number(joints),
            "Skirmishes":        _number(skirmishes),
            "PRs":               _number(prs),
            "Status":            _select("Active"),
            "Date Enlisted":     _date_only(enlisted),
            config.BASIC_LEVY_FIELD: _checkbox(basic_levy),
            "Days Served":       _number(max(0, (datetime.now(timezone.utc).date() - enlisted.date()).days)),
        },
    )
    roster_cache.invalidate_uid(str(discord_user_id))
    return page


# ── Event Log helpers ──────────────────────────────────────────────────────

async def get_next_request_id() -> int:
    """Return max existing RequestID + 1."""
    nc = get_client()
    resp = await nc.databases.query(
        database_id=os.environ["NOTION_EVENT_LOG_DB_ID"],
        sorts=[{"property": "RequestID", "direction": "descending"}],
        page_size=1,
    )
    results = resp.get("results", [])
    if not results:
        return 1
    last = results[0]["properties"].get("RequestID", {}).get("number") or 0
    return int(last) + 1


async def create_event_log_entry(
    discord_user_id: str,
    event_type: str,
    points: int,
    host: str,
    proof_link: str,
    request_id: int,
    status: str = "Pending",
    approved_by: str = "",
) -> dict:
    nc = get_client()
    return await nc.pages.create(
        parent={"database_id": os.environ["NOTION_EVENT_LOG_DB_ID"]},
        properties={
            "Member":      _title(discord_user_id),
            "Event Type":  _select(event_type),
            "Points":      _number(points),
            "Host":        _text(host),
            "Proof Link":  _url(proof_link),
            "Status":      _select(status),
            "RequestID":   _number(request_id),
            "Approved By": _text(approved_by),
            "Timestamp":   _date(datetime.now(timezone.utc)),
        },
    )


async def update_event_log_status(page_id: str, status: str, approved_by: str = "") -> None:
    nc = get_client()
    props = {"Status": _select(status)}
    if approved_by:
        props["Approved By"] = _text(approved_by)
    await nc.pages.update(page_id=page_id, properties=props)


# ── Discharge Log helpers ──────────────────────────────────────────────────

async def create_discharge_log_entry(
    discord_user_id: str,
    reason: str,
    status: str = "Pending",
) -> dict:
    nc = get_client()
    return await nc.pages.create(
        parent={"database_id": os.environ["NOTION_DISCHARGE_LOG_DB_ID"]},
        properties={
            "Member":    _title(discord_user_id),
            "Reason":    _text(reason),
            "Status":    _select(status),
            "Timestamp": _date(datetime.now(timezone.utc)),
        },
    )


async def update_discharge_log_status(page_id: str, status: str, decided_by: str = "") -> None:
    nc = get_client()
    props = {"Status": _select(status)}
    if decided_by:
        props["Decided By"] = _text(decided_by)
    await nc.pages.update(page_id=page_id, properties=props)


# ── LOA (Leave of Absence) Log helpers ─────────────────────────────────────
# Best-effort: if NOTION_LOA_LOG_DB_ID isn't configured yet, create returns None
# and the LOA flow simply runs without a Notion paper trail (the review embed is
# still the source of truth for the Approve/Deny buttons).

async def create_loa_log_entry(
    discord_user_id: str,
    reason: str,
    duration: str = "",
    return_note: str = "",
    status: str = "Pending",
) -> Optional[dict]:
    db_id = os.environ.get("NOTION_LOA_LOG_DB_ID")
    if not db_id:
        return None
    nc = get_client()
    return await nc.pages.create(
        parent={"database_id": db_id},
        properties={
            "Member":    _title(discord_user_id),
            "Reason":    _text(reason),
            "Duration":  _text(duration),
            "Return":    _text(return_note),
            "Status":    _select(status),
            "Timestamp": _date(datetime.now(timezone.utc)),
        },
    )


async def update_loa_log_status(page_id: str, status: str, decided_by: str = "") -> None:
    nc = get_client()
    props = {"Status": _select(status)}
    if decided_by:
        props["Decided By"] = _text(decided_by)
    await nc.pages.update(page_id=page_id, properties=props)


# ── Reporting helpers (weekly digest / leaderboard / inactivity) ───────────

def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def get_recent_log(db_env_var: str, days: int) -> list[dict]:
    """Every row of the given log DB with Timestamp within the last `days`.
    Returns [] if the env var isn't configured (best-effort)."""
    db_id = os.environ.get(db_env_var)
    if not db_id:
        return []
    flt = {"property": "Timestamp", "date": {"on_or_after": _iso_days_ago(days)}}
    return await _query_all(db_id, flt)


def event_log_points(page: dict) -> tuple[str, int, str]:
    """(member discord id, points, event type) from an Event Log row."""
    props = page["properties"]
    member = _get_title(props, "Member")
    points = int((props.get("Points", {}) or {}).get("number") or 0)
    etype = ((props.get("Event Type", {}) or {}).get("select") or {}).get("name", "")
    return member, points, etype


async def create_strike(discord_user_id: str, reason: str, issued_by: str) -> Optional[dict]:
    db_id = os.environ.get("NOTION_STRIKES_DB_ID")
    if not db_id:
        return None
    nc = get_client()
    return await nc.pages.create(
        parent={"database_id": db_id},
        properties={
            "Member":    _title(discord_user_id),
            "Reason":    _text(reason),
            "Issued By": _text(issued_by),
            "Timestamp": _date(datetime.now(timezone.utc)),
        },
    )


async def get_active_strikes(discord_user_id: str, days: int) -> list[dict]:
    """Strike rows for a member issued within the last `days` (i.e. still active)."""
    db_id = os.environ.get("NOTION_STRIKES_DB_ID")
    if not db_id:
        return []
    flt = {"and": [
        {"property": "Member", "title": {"equals": discord_user_id}},
        {"property": "Timestamp", "date": {"on_or_after": _iso_days_ago(days)}},
    ]}
    return await _query_all(db_id, flt)


async def clear_active_strikes(discord_user_id: str, days: int) -> int:
    """Archive a member's active strike rows. Returns how many were cleared."""
    rows = await get_active_strikes(discord_user_id, days)
    nc = get_client()
    for page in rows:
        await nc.pages.update(page_id=page["id"], archived=True)
    return len(rows)


async def log_advancement(
    discord_user_id: str,
    rank: str,
    entry_type: str,
    detail: str = "",
) -> Optional[dict]:
    """Record a Promotion/Milestone in the Advancement Log (best-effort)."""
    db_id = os.environ.get("NOTION_ADVANCEMENT_LOG_DB_ID")
    if not db_id:
        return None
    nc = get_client()
    return await nc.pages.create(
        parent={"database_id": db_id},
        properties={
            "Member":    _title(discord_user_id),
            "Rank":      _text(rank),
            "Type":      _select(entry_type),
            "Detail":    _text(detail),
            "Timestamp": _date(datetime.now(timezone.utc)),
        },
    )


# ── Property helpers ───────────────────────────────────────────────────────

def _title(text: str) -> dict:
    return {"title": [{"text": {"content": str(text)}}]}

def _text(text: str) -> dict:
    return {"rich_text": [{"text": {"content": str(text)}}]}

def _select(name: str) -> dict:
    return {"select": {"name": str(name)}}

def _number(value: int | float) -> dict:
    return {"number": value}

def _checkbox(value: bool) -> dict:
    return {"checkbox": value}

def _date(dt: datetime) -> dict:
    return {"date": {"start": dt.isoformat()}}

def _date_only(dt: datetime) -> dict:
    """Notion date with no time component (YYYY-MM-DD)."""
    return {"date": {"start": dt.date().isoformat()}}

def _url(url: str) -> dict:
    return {"url": url if url else None}


def _get_number(props: dict, field: str) -> int:
    val = props.get(field, {}).get("number")
    return int(val) if val is not None else 0


def get_prop_text(props: dict, field: str) -> str:
    """
    Read a property's value as text regardless of its Notion type (title,
    rich_text, number, or select). Used by the migration to read the legacy
    Military Tracking DB without assuming each column's type.
    """
    prop = props.get(field) or {}
    ptype = prop.get("type")
    if ptype == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", [])).strip()
    if ptype == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", [])).strip()
    if ptype == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if ptype == "select":
        return (prop.get("select") or {}).get("name", "") or ""
    return ""


def extract_member_stats(props: dict) -> dict:
    """Pull all rank-relevant stats from a Notion properties dict."""
    return {
        "points":           _get_number(props, "Event Points"),
        "combat_trainings": _get_number(props, "Combat Trainings"),
        "joints":           _get_number(props, "Joints"),
        "skirmishes":       _get_number(props, "Skirmishes"),  # legacy, no longer counted
        "prs":              _get_number(props, "PRs"),
        # Empty selects come back as {"select": None}, so every hop is or-guarded.
        "rank":             (((props.get("Rank") or {}).get("select")) or {}).get("name", ""),
        "detachment":       (((props.get("Detachment") or {}).get("select")) or {}).get("name", ""),
        "status":           (((props.get("Status") or {}).get("select")) or {}).get("name", ""),
        "discord_user_id":  _get_text(props, "Discord User ID"),
        "discord_username": _get_text(props, "Discord Username"),
        "lorename":         _get_text(props, "Lorename"),
        "roblox_username":  _get_title(props, "Username"),
        "roblox_id":        _get_text(props, "Roblox ID"),
        "date_enlisted":    (props.get("Date Enlisted", {}).get("date") or {}).get("start") or "",
        "basic_levy":       bool((props.get(config.BASIC_LEVY_FIELD, {}) or {}).get("checkbox")),
        "days_served":      _get_number(props, "Days Served"),
    }


def tenure_days(props_or_stats: dict) -> float:
    """
    Days served, for the Man-at-Arms 17-day gate. The higher of (a) days since
    the row's Date Enlisted and (b) the manually-editable "Days Served" column
    — so an admin can bump someone's tenure up but never accidentally lower it.
    Accepts either the raw Notion properties dict or an extract_member_stats()
    dict.
    """
    if "Date Enlisted" in props_or_stats or "Days Served" in props_or_stats:  # raw properties
        start = (props_or_stats.get("Date Enlisted", {}).get("date") or {}).get("start") or ""
        column = (props_or_stats.get("Days Served", {}) or {}).get("number") or 0
    else:
        start = props_or_stats.get("date_enlisted") or ""
        column = props_or_stats.get("days_served") or 0
    derived = 0.0
    if start:
        try:
            enlisted = datetime.fromisoformat(start)
            if enlisted.tzinfo is None:
                enlisted = enlisted.replace(tzinfo=timezone.utc)
            derived = max(0.0, (datetime.now(timezone.utc) - enlisted).days)
        except ValueError:
            pass
    return max(derived, float(column))


def days_served_value(props: dict) -> int:
    """The value the bot writes back to the "Days Served" display column."""
    return int(tenure_days(props))


def _get_text(props: dict, field: str) -> str:
    rt = props.get(field, {}).get("rich_text", [])
    return rt[0]["text"]["content"] if rt else ""


def _get_title(props: dict, field: str) -> str:
    t = props.get(field, {}).get("title", [])
    if not t:
        return ""
    return t[0].get("plain_text") or t[0].get("text", {}).get("content", "")
