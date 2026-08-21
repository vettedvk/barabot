"""
Rank engine — pure logic, no Discord/Notion I/O.

compute_rank(...) returns the retinue-ladder rank a member has EARNED given
their stats. Stations (Corporal+), court and specialised-retinue ranks are
manually appointed and never auto-computed.

Handbook gates (cumulative — each tier requires all lower tiers too):
  Levy             0 pts
  Soldier          attended a Basic Levy Training (no points involved)
  Footman          15 pts + attended 3 trainings
  Veteran Footman  30 pts + attended 6 trainings, at least one a Joint or PR
  Man-at-Arms      >30 pts (i.e. 31+) + 17 days in the house

"Trainings attended" = every point-earning event: Combat Trainings + Joints +
PRs. The Basic Levy Training checkbox does not add to that count.

IMPORTANT (grandfather rule): the engine only says what a member has EARNED.
Callers must never demote a member who already holds a higher ladder rank —
manually granted ranks are respected until manually removed. Use
never_demote() at every call site.
"""

from typing import Optional


# Auto-promotion ladders (index 0 = starting rank). Companies not listed here
# use fully manual ranks and are never auto-computed.
AUTO_LADDERS = {
    "Stormbreakers": ["Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms"],
    "Thunderhooves": ["Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms"],
    "Breaknecks":    ["Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms"],
}

# Minimum stats that justify sitting at each ladder tier — used to seed
# imported members so the points engine agrees with their rank. Tenure can't
# be seeded (it derives from Date Enlisted / Days Served).
AUTO_TIER_MIN_STATS = [
    dict(points=0,  combat_trainings=0, joints=0, prs=0, basic_levy=False),  # 0 Levy
    dict(points=0,  combat_trainings=0, joints=0, prs=0, basic_levy=True),   # 1 Soldier
    dict(points=15, combat_trainings=3, joints=0, prs=0, basic_levy=True),   # 2 Footman
    dict(points=30, combat_trainings=5, joints=1, prs=0, basic_levy=True),   # 3 Veteran Footman
    dict(points=31, combat_trainings=5, joints=1, prs=0, basic_levy=True),   # 4 Man-at-Arms
]

MAN_AT_ARMS_TENURE_DAYS = 17


def compute_rank(
    company: str,
    points: int,
    combat_trainings: int = 0,
    joints: int = 0,
    prs: int = 0,
    basic_levy: bool = False,
    tenure_days: float = 0,
) -> Optional[str]:
    """
    Return the highest EARNED ladder rank for the given retinue and stats.
    Returns None for companies with fully manual ranks (Stormguard, Knights of
    the Storm, Court, High Command) — the caller keeps the current rank.
    """
    ladder = AUTO_LADDERS.get(company)
    if not ladder:
        return None

    trainings = combat_trainings + joints + prs
    tier = 0  # Levy — always earned

    # Tier 1 — Soldier: attended a Basic Levy Training
    if basic_levy:
        tier = 1

    # Tier 2 — Footman: 15 pts + 3 trainings
    if tier >= 1 and points >= 15 and trainings >= 3:
        tier = 2

    # Tier 3 — Veteran Footman: 30 pts + 6 trainings incl. a Joint or PR
    if tier >= 2 and points >= 30 and trainings >= 6 and (joints + prs) >= 1:
        tier = 3

    # Tier 4 — Man-at-Arms: >30 pts + 17 days in the house
    if tier >= 3 and points >= 31 and tenure_days >= MAN_AT_ARMS_TENURE_DAYS:
        tier = 4

    return ladder[tier]


def never_demote(company: str, current_rank: str, computed_rank: Optional[str]) -> str:
    """
    Grandfather rule: a rank, once held, is only ever removed manually. Returns
    the higher of current vs computed on the ladder; any non-ladder current
    rank (stations, specialised, blank-but-manual) always wins.
    """
    ladder = AUTO_LADDERS.get(company)
    if not ladder or computed_rank is None:
        return current_rank or (computed_rank or "")
    if current_rank not in ladder:
        # Manual/station rank (or unknown) — never replaced by the engine.
        return current_rank if current_rank else computed_rank
    if ladder.index(computed_rank) > ladder.index(current_rank):
        return computed_rank
    return current_rank


def min_stats_for_rank(company: str, rank: str) -> dict:
    """
    Minimum points/attendances that justify holding `rank` in `company`.
    For manual companies and station ranks there is no requirement, so all
    zeros are returned. Used to seed imported members.
    """
    ladder = AUTO_LADDERS.get(company)
    if ladder and rank in ladder:
        return dict(AUTO_TIER_MIN_STATS[ladder.index(rank)])
    return dict(points=0, combat_trainings=0, joints=0, prs=0, basic_levy=False)


def is_leadership_rank(rank: str) -> bool:
    """Manually appointed ranks — never touched by the points engine."""
    return rank not in AUTO_LADDERS.get("Stormbreakers", [])


def next_rank_progress(
    company: str,
    current_rank: str,
    points: int,
    combat_trainings: int = 0,
    joints: int = 0,
    prs: int = 0,
    basic_levy: bool = False,
    tenure_days: float = 0,
) -> Optional[dict]:
    """
    Describe what a member still needs for their NEXT ladder rank.

    Returns None for members not on an auto ladder (their rank is appointed).
    Otherwise returns {"next_rank": str|None, "requirements": [(label, have,
    need, met), ...]}; next_rank is None when they're already at Man-at-Arms.
    """
    ladder = AUTO_LADDERS.get(company)
    if not ladder or current_rank not in ladder:
        return None
    cur = ladder.index(current_rank)
    if cur >= len(ladder) - 1:
        return {"next_rank": None, "requirements": []}

    nxt = cur + 1
    trainings = combat_trainings + joints + prs
    reqs: list[tuple] = []
    if nxt == 1:      # → Soldier
        reqs.append(("Attend a Basic Levy Training", "yes" if basic_levy else "no", "yes", basic_levy))
    elif nxt == 2:    # → Footman
        reqs.append(("Event points", points, 15, points >= 15))
        reqs.append(("Trainings attended", trainings, 3, trainings >= 3))
    elif nxt == 3:    # → Veteran Footman
        reqs.append(("Event points", points, 30, points >= 30))
        reqs.append(("Trainings attended", trainings, 6, trainings >= 6))
        reqs.append(("Joints or PRs", joints + prs, 1, (joints + prs) >= 1))
    elif nxt == 4:    # → Man-at-Arms
        reqs.append(("Event points", points, 31, points >= 31))
        reqs.append(("Days in the house", int(tenure_days), MAN_AT_ARMS_TENURE_DAYS,
                     tenure_days >= MAN_AT_ARMS_TENURE_DAYS))
    return {"next_rank": ladder[nxt], "requirements": reqs}
