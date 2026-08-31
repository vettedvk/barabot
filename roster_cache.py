"""
roster_cache — an in-memory hot layer over the Notion roster.

Notion stays the durable source of truth; this just caches a member's roster
pages (keyed by Discord User ID) so repeat reads don't re-hit Notion, and a
periodic full refresh picks up rows added or edited directly in Notion.

Safety model (deliberately conservative — a stale roster read is exactly the
kind of bug that makes ranks look wrong, so correctness beats hit-rate):

  • Write-through by invalidation. Every roster WRITE in notion_service drops the
    affected member's cache entry, so the next read refetches from Notion.
  • Short TTL. Each entry also expires after TTL_SECONDS, so even a write path
    that forgot to invalidate self-heals within the window.
  • Empty results are never cached. A member with no rows always hits Notion, so
    a freshly-added (or manually-added) entry is seen immediately — important for
    "already enlisted?" checks and for the Discord-authority upsert.

Everything here is pure in-process state with no external I/O, so it carries no
import of notion_service (which drives it) and can't create a cycle.
"""

import time

# Reads never serve data older than this; the periodic refresh runs more often.
TTL_SECONDS = 300.0

_enabled = True
_by_uid: dict[str, list[dict]] = {}
_stamp: dict[str, float] = {}
_pageid_to_uid: dict[str, str] = {}


def enable(flag: bool) -> None:
    """Turn the cache on/off at runtime; disabling clears it."""
    global _enabled
    _enabled = flag
    if not flag:
        clear()


def is_enabled() -> bool:
    return _enabled


def clear() -> None:
    _by_uid.clear()
    _stamp.clear()
    _pageid_to_uid.clear()


def _drop(uid: str) -> None:
    for pid in [pid for pid, u in _pageid_to_uid.items() if u == uid]:
        _pageid_to_uid.pop(pid, None)
    _by_uid.pop(uid, None)
    _stamp.pop(uid, None)


def get(uid: str) -> list[dict] | None:
    """Return the cached pages for a member, or None on a miss/expiry."""
    if not _enabled or not uid:
        return None
    ts = _stamp.get(uid)
    if ts is None:
        return None
    if time.monotonic() - ts > TTL_SECONDS:
        _drop(uid)
        return None
    return _by_uid.get(uid)


def put(uid: str, pages: list[dict]) -> None:
    """Cache a member's pages. Empty lists are intentionally NOT cached."""
    if not _enabled or not uid or not pages:
        return
    _drop(uid)  # clear any stale reverse mappings first
    _by_uid[uid] = pages
    _stamp[uid] = time.monotonic()
    for p in pages:
        pid = p.get("id")
        if pid:
            _pageid_to_uid[pid] = uid


def invalidate_uid(uid: str) -> None:
    """Drop a member's entry (call after creating/removing their rows)."""
    if _enabled and uid:
        _drop(uid)


def invalidate_page(page_id: str) -> None:
    """Drop the entry owning a page (call after any single-page write)."""
    if not _enabled or not page_id:
        return
    uid = _pageid_to_uid.get(page_id)
    if uid:
        _drop(uid)


def replace_all(pages_by_uid: dict[str, list[dict]]) -> None:
    """Rebuild the whole cache from a fresh Notion snapshot (periodic refresh)."""
    if not _enabled:
        return
    clear()
    now = time.monotonic()
    for uid, pages in pages_by_uid.items():
        if not uid or not pages:
            continue
        _by_uid[uid] = pages
        _stamp[uid] = now
        for p in pages:
            pid = p.get("id")
            if pid:
                _pageid_to_uid[pid] = uid


def stats() -> dict:
    """Small snapshot for a status/diagnostic command."""
    return {"enabled": _enabled, "members": len(_by_uid), "pages": len(_pageid_to_uid)}
