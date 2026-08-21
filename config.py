"""
Central config — all IDs and constants live here.

2026-08 military restructure: detachments are now combat-role based. Two active
main retinues on the points ladder — STORMBREAKERS (close combat, internal EU/NA
split via the region tags) and THUNDERHOOVES (cavalry, temporarily incl. archers)
— plus BREAKNECKS (future archery, role exists but inactive). Specialised
retinues, top→bottom: STORMGUARD → THE BLACK STAGS (elite; SG prospects) →
KNIGHTS OF THE STORM. The Court runs alongside; several court ranks are DUAL
(held together with a military posting).

The points auto-ladder is UNCHANGED (Levy → Soldier → Footman → Veteran Footman
→ Man-at-Arms). What changed: new Levys are NOT auto-sorted into a detachment —
they're placed by hand after a Basic Levy Training (see cogs/events.py), and the
command/NCO ranks above the ladder are new (Squire is specialised, not NCO).
"""

# ── Guild ──────────────────────────────────────────────────────────────────
GUILD_ID = 1488659967870238822

# ── Admin / gate roles ─────────────────────────────────────────────────────
ROLE_BOT_ADMIN  = 1501355218611343470  # "Bot Perms"
ROLE_HIGHBORN   = 1488659968096862332  # "Blood of the Storms"

# ── Titles (cosmetic; sit above the bot and are managed by hand) ───────────
TITLE_ROLE_IDS = {
    "Lord of Storm's End": 1488659968096862335,
    "Lady of Storm's End": 1488659968096862334,
    "Heir of Storm's End": 1488659968096862333,
}

# High Command hierarchy (highest -> lowest). A member's High Command standing
# is their HIGHEST of these roles. Council of Storm's End and above = High
# Command.
HIGH_COMMAND_ROLE_IDS = {
    "Lord of Storm's End":    1488659968096862335,
    "Lady of Storm's End":    1488659968096862334,
    "Heir of Storm's End":    1488659968096862333,
    "Blood of the Storms":    1488659968096862332,  # == ROLE_HIGHBORN
    "Council of Storm's End": 1488659968096862330,
}

# Roles that count as "Highborn": Blood of the Storms and ABOVE.
HIGHBORN_ROLE_IDS = {
    1488659968096862335,  # Lord of Storm's End
    1488659968096862334,  # Lady of Storm's End
    1488659968096862333,  # Heir of Storm's End
    1488659968096862332,  # Blood of the Storms
}

# ── Known channel IDs ──────────────────────────────────────────────────────
CHANNEL_POINTS_REVIEW    = 1499773406982439003
CHANNEL_ABANDONMENT_LOG  = 1499797990859079892
# Audit log: every slash command run + every automated bot action is posted here.
CHANNEL_COMMAND_LOG      = 1488659976791527426
CHANNEL_DISCHARGE_REVIEW = 1512498089653436426
# Channel where the persistent "Request Discharge" button panel is posted.
CHANNEL_DISCHARGE_PANEL  = 1512684353828683786

# LOA (Leave of Absence) — mirrors discharge: members press a button in the
# request channel, the review embed posts to the approval channel.
CHANNEL_LOA_PANEL  = 1536688129220681830  # where the "Request LOA" button panel lives
CHANNEL_LOA_REVIEW = 1536688227589685320  # where LOA requests post for approval

# Weekly training schedule — the public embed the bot posts once and keeps
# up to date in place. Wipes to a placeholder every Monday 00:00 UK time.
CHANNEL_SCHEDULE = 1488659970198343757

# Promotions — the bot congratulates + pings a member here whenever they climb
# the auto ladder (Levy → … → Man-at-Arms). Doubles as a promotion log.
CHANNEL_PROMOTIONS = 1537381403782811748

# ── Weekly reports (inactivity, digest, leaderboard) ───────────────────────
HOUSE_LEAD_DM_ID = 897916113499877398   # DM'd the weekly inactivity report + digest
INACTIVITY_DAYS  = 14                    # no logged attendance in this many days = inactive

# ── Strikes ────────────────────────────────────────────────────────────────
STRIKE_EXPIRY_DAYS = 7
STRIKE_DEMOTE      = 3
STRIKE_REMOVE      = 5

# Enlistment / Diplomatic application panel + review
CHANNEL_ENLISTMENT_PANEL  = 1499769147033260184   # where the buttons message lives
CHANNEL_ENLISTMENT_REVIEW = 1499769319855231062   # where applications post for review

# ── Status / membership roles ──────────────────────────────────────────────
ROLE_ENVOY           = 1488659967924895931  # granted on approved Envoy application
ROLE_VERIFIED        = 1488659967924895929  # granted on ANY approved application; kept on discharge
ROLE_UNVERIFIED      = 1488659967924895928  # granted when a member joins; removed on enlistment
ROLE_VISITOR         = 1488659967924895932  # granted on discharge (civilian standing)
ROLE_HOUSE_BARATHEON = 1488659967979290797  # house membership; granted on military enlistment
ROLE_LOA             = 1536689146083672174  # granted on approved LOA; removed when they return

# Court of Storm's End membership role — AUTO-granted by role hygiene to anyone
# holding a court rank, removed when they hold none.
ROLE_COURT = 1525947287803662521

# Station separator role — AUTO-granted by role hygiene to anyone holding a
# military station rank (Corporal → Marshal). Independent of the Military
# Command access separator.
ROLE_STATION = 1522247670331342949

# ── Region tag roles (EU / NA) ─────────────────────────────────────────────
# Region is now a blanket tag independent of detachment (the close-combat retinue
# keeps its regional split via these). Asked at enlistment; granted, never sorts.
REGION_ROLE_IDS = {
    "EU": 1540431156992937984,
    "NA": 1540431192203984997,
}
REGION_CHOICES = ["EU", "NA"]

# Military-command ACCESS roles (one per retinue) — distributed BY HAND; they
# alone trigger the Military Command separator. Hygiene never grants/removes them.
DETACHMENT_COMMAND_ROLE_IDS = {
    "Stormbreakers":        1515481526895378504,
    "Thunderhooves":        1540429088408215574,
    "Breaknecks":           1540429120738168882,
    "The Black Stags":      1515481460688289862,
    "Stormguard":           1488659967941808131,
    "Knights of the Storm": 1488659967941808130,
}
MILITARY_COMMAND_ROLE_IDS = set(DETACHMENT_COMMAND_ROLE_IDS.values())

# Banner shown on the enlistment panel.
ENLISTMENT_BANNER_URL = "https://i.ibb.co/Wvg22HKX/Banner.png"

# ── Retinue (detachment) roles ─────────────────────────────────────────────
# Main combat retinues use the points ladder. Specialised retinues + Court are
# appointment-based. High Command has no single retinue role.
COMPANY_ROLE_IDS = {
    "Stormbreakers":        1540427573375406232,   # close combat (main)
    "Thunderhooves":        1540426846703976468,   # cavalry, incl. archers for now (main)
    "Breaknecks":           1540426994196545559,   # future archery (inactive)
    "The Black Stags":      1540427514210554096,   # elite retinue (SG prospects)
    "Stormguard":           1522250233306681434,
    "Knights of the Storm": 1488659968067371083,
    "Court":                1525947287803662521,   # == ROLE_COURT
}

# Main combat detachments (the auto points-ladder ones).
MAIN_COMBAT_DETACHMENTS = ["Stormbreakers", "Thunderhooves", "Breaknecks"]
# Retinues a Levy can be placed into after Basic Levy Training (active mains).
PLACEMENT_DETACHMENTS = ["Stormbreakers", "Thunderhooves"]

# ── Rank role IDs ──────────────────────────────────────────────────────────
RANK_ROLE_IDS = {
    # Auto points ladder (main combat retinues)
    "Levy":            1488659967979290801,
    "Soldier":         1488659967979290802,
    "Footman":         1488659967979290803,
    "Veteran Footman": 1488659968033951871,
    "Man-at-Arms":     1488659967979290804,

    # Military stations / command (appointed, house-wide) — lowest → highest
    "Corporal":       1488659967979290805,
    "SGT at Arms":    1540425172513726464,
    "Knight Banneret": 1540424980465189006,
    "Lieutenant":     1488659968067371086,
    "Captain":        1488659968096862329,
    "Commander":      1540424892506447992,
    "Marshal":        1530245399003267124,

    # Specialised retinue ranks (appointed)
    "Squire":                    1522250075756171355,
    "Guardsman":                 1488659968067371084,
    "Knight":                    1488659968054792385,
    "Stormguard Lord Commander": 1488659968054792390,

    # Court ranks (appointed) — lowest → highest
    "Clerk":                  1488659968054792383,
    "Emissary":               1526653081192894756,
    "Handmaiden":             1540425645656506468,
    "Cupbearer":              1526653118526394389,
    "Secretary of the Court": 1540424099644309594,
    "Quartermaster":          1540425552631173232,
    "Chancellor":             1540425482825244802,

    # High Command
    "Council of Storm's End": 1488659968096862330,
    "Blood of the Storms":    1488659968096862332,
    "Heir of Storm's End":    1488659968096862333,
    "Lady of Storm's End":    1488659968096862334,
    "Lord of Storm's End":    1488659968096862335,
}

# Ranks per detachment, lowest → highest. Used to (a) detect a member's rank
# within a detachment and (b) as the cleanup list when role_service swaps rank
# roles. Main combat retinues carry the auto ladder + the appointed chain; the
# elite retinue is appointment-only.
_MAIN_COMBAT_RANKS = [
    "Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms",
    "Corporal", "SGT at Arms", "Knight Banneret", "Lieutenant", "Captain",
    "Commander", "Marshal",
]
DETACHMENT_RANKS = {
    "Stormbreakers":        list(_MAIN_COMBAT_RANKS),
    "Thunderhooves":        list(_MAIN_COMBAT_RANKS),
    "Breaknecks":           list(_MAIN_COMBAT_RANKS),
    "The Black Stags":      ["Knight Banneret", "Lieutenant", "Captain"],
    "Stormguard":           ["Squire", "Guardsman", "Lieutenant", "Stormguard Lord Commander"],
    "Knights of the Storm": ["Squire", "Knight", "Captain"],
    "Court":                ["Clerk", "Emissary", "Handmaiden", "Cupbearer",
                             "Secretary of the Court", "Quartermaster", "Chancellor"],
    "High Command":         ["Council of Storm's End", "Blood of the Storms",
                             "Heir of Storm's End", "Lady of Storm's End", "Lord of Storm's End"],
}

# Alias kept for role_service, which strips a detachment's rank roles on a swap.
COMPANY_RANKS = DETACHMENT_RANKS

# The five point-earning ladder ranks (auto ladder).
FLEET_RANKS = ["Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms"]
FLEET_RANK_ROLE_IDS = {RANK_ROLE_IDS[r] for r in FLEET_RANKS}

# Military station ranks: holders need no ladder rank (role hygiene strips it).
MILITARY_STATION_RANKS = ["Corporal", "SGT at Arms", "Knight Banneret",
                          "Lieutenant", "Captain", "Commander", "Marshal"]
# Court ranks.
COURT_STATION_RANKS = ["Clerk", "Emissary", "Handmaiden", "Cupbearer",
                       "Secretary of the Court", "Quartermaster", "Chancellor"]
STATION_ROLE_IDS       = {RANK_ROLE_IDS[r] for r in MILITARY_STATION_RANKS}
COURT_STATION_ROLE_IDS = {RANK_ROLE_IDS[r] for r in COURT_STATION_RANKS}

# DUAL court ranks — held ALONGSIDE a military posting (member keeps their
# retinue row). The rest are court-only. Assumption pending confirmation.
COURT_DUAL_RANKS      = {"Clerk", "Cupbearer", "Handmaiden", "Secretary of the Court"}
COURT_EXCLUSIVE_RANKS = {"Emissary", "Quartermaster", "Chancellor"}

# Officer/manual ranks: never auto-promoted, protected from /purge auto-discharge.
OFFICER_RANKS = (
    set(MILITARY_STATION_RANKS)
    | set(COURT_STATION_RANKS)
    | {"Stormguard Lord Commander"}
)

# Purge: protected from auto-discharge but explicitly flagged for a manual decision.
PURGE_FLAG_RANKS = {"Knight", "Guardsman", "Squire"}

# /event hosts: stations + court + Lord Commander + High Command (+ Bot Admin).
EVENT_HOST_ROLE_IDS = (
    set(STATION_ROLE_IDS) | set(COURT_STATION_ROLE_IDS)
    | {RANK_ROLE_IDS["Stormguard Lord Commander"]}
    | set(HIGH_COMMAND_ROLE_IDS.values())
)

# /log_event — the Court logs attendance. Court ranks/role + High Command (+ Admin).
EVENT_LOGGER_ROLE_IDS = (
    set(COURT_STATION_ROLE_IDS) | {ROLE_COURT} | set(HIGH_COMMAND_ROLE_IDS.values())
)

# Command = Council of Storm's End and above (extra High Command roster row).
COMMAND_ROLE_IDS = set(HIGH_COMMAND_ROLE_IDS.values())

# Roles permitted to Accept/Decline enlistment & envoy applications.
ENLISTMENT_REVIEWER_ROLE_IDS = set(HIGH_COMMAND_ROLE_IDS.values()) | {
    RANK_ROLE_IDS["Marshal"],
    RANK_ROLE_IDS["Commander"],
    RANK_ROLE_IDS["Captain"],
    RANK_ROLE_IDS["Lieutenant"],
    RANK_ROLE_IDS["Secretary of the Court"],
    RANK_ROLE_IDS["Chancellor"],
    ROLE_BOT_ADMIN,
}

# ── Command permission tiers ────────────────────────────────────────────────
#   RULER   — destructive / irreversible (bulk wipes, migrations, mass role pass).
#   ADMIN   — every non-destructive command.
#   OFFICER — everyday roster / military commands (the retinue command roles).
#   LOGGER  — /log_event (the Court).
RULER_ROLE_IDS = {
    HIGH_COMMAND_ROLE_IDS["Heir of Storm's End"],
    HIGH_COMMAND_ROLE_IDS["Lady of Storm's End"],
    HIGH_COMMAND_ROLE_IDS["Lord of Storm's End"],
}

ADMIN_ROLE_IDS = {
    ROLE_BOT_ADMIN,
    HIGH_COMMAND_ROLE_IDS["Blood of the Storms"],
    HIGH_COMMAND_ROLE_IDS["Council of Storm's End"],
} | RULER_ROLE_IDS

# Officer tier: the retinue command access roles. ADMIN added by util.is_officer.
OFFICER_ROLE_IDS = set(MILITARY_COMMAND_ROLE_IDS)

# Logger tier: the Court role. ADMIN added by util.is_event_logger.
LOGGER_ROLE_IDS = {ROLE_COURT}

# Roster Status value written to a member's rows while they are on leave.
LOA_STATUS = "LOA"

# ── Separator (divider) roles ──────────────────────────────────────────────
# One separator per section of the Discord role list. Role hygiene grants each
# member the separators for the sections they hold a role in. Those above the
# bot's top role are skipped automatically by role_service.
SEPARATOR_HIGH_COMMAND     = 1488659968096862331
SEPARATOR_UPPER_COURT      = 1540428119494631514
SEPARATOR_MILITARY_COMMAND = 1488659967941808135
SEPARATOR_COURT            = 1525946634674896906
SEPARATOR_STATION          = 1522247670331342949  # == ROLE_STATION
SEPARATOR_RANK             = 1488659968067371078
SEPARATOR_RETINUE          = 1522249886781804604
SEPARATOR_STATUS           = 1488659967979290798

# Upper court = the senior court ranks that live above the bot with High Command.
UPPER_COURT_ROLE_IDS = {
    RANK_ROLE_IDS["Chancellor"],
    RANK_ROLE_IDS["Quartermaster"],
    RANK_ROLE_IDS["Secretary of the Court"],
    RANK_ROLE_IDS["Cupbearer"],
    RANK_ROLE_IDS["Handmaiden"],
}
# Junior court = the ranks under the Court separator.
LOWER_COURT_ROLE_IDS = {
    RANK_ROLE_IDS["Emissary"],
    RANK_ROLE_IDS["Clerk"],
}

STATUS_ROLE_IDS = {
    ROLE_HOUSE_BARATHEON,
    1526080693480849429,   # House Dondarrion of Blackhaven
    1518346655227969707,   # House Connington of Griffins Roost
    1488659967979290799,   # Sworn Vassal
    1488659967924895930,   # Genre Staff
    ROLE_ENVOY,            # Envoy
    ROLE_VISITOR,          # Visitor
    ROLE_LOA,              # LOA
    1488659967941808136,   # Bots
    *REGION_ROLE_IDS.values(),
}

# separator role id -> set of role ids whose presence earns that separator.
SEPARATOR_TRIGGERS = {
    SEPARATOR_MILITARY_COMMAND: set(MILITARY_COMMAND_ROLE_IDS),
    SEPARATOR_UPPER_COURT: set(UPPER_COURT_ROLE_IDS),
    SEPARATOR_COURT: {ROLE_COURT} | set(LOWER_COURT_ROLE_IDS),
    SEPARATOR_STATION: set(STATION_ROLE_IDS),
    SEPARATOR_RANK: set(FLEET_RANK_ROLE_IDS) | {
        RANK_ROLE_IDS["Squire"], RANK_ROLE_IDS["Knight"], RANK_ROLE_IDS["Guardsman"],
    },
    SEPARATOR_RETINUE: {
        COMPANY_ROLE_IDS[d] for d in
        ("Stormbreakers", "Thunderhooves", "Breaknecks", "The Black Stags",
         "Stormguard", "Knights of the Storm")
    },
    SEPARATOR_STATUS: set(STATUS_ROLE_IDS),
}

# ── Event types and base point values ──────────────────────────────────────
EVENT_TYPES = {
    "Basic Levy Training": 0,
    "House-wide Training": 5,
    "Retinue Training":    5,
    "Joint Event":         5,
    "PR":                  5,
}

# The event whose approval ticks the Basic Levy Training checkbox (and triggers
# the post-training placement prompt).
BASIC_LEVY_EVENT = "Basic Levy Training"
BASIC_LEVY_FIELD = "Basic Levy Training"  # Notion checkbox column

EVENT_COUNTER_FIELDS = {
    "House-wide Training": "Combat Trainings",
    "Retinue Training":    "Combat Trainings",
    "Joint Event":         "Joints",
    "PR":                  "PRs",
}

# ── Sync worker interval (seconds) ─────────────────────────────────────────
SYNC_INTERVAL_SECONDS = 600  # 10 minutes

# Master kill-switch for the periodic Discord→Notion reconciliation. Kept False
# through the restructure so it never auto-reconciles legacy roles mid-migration.
SYNC_ENABLED = False

# ── Optional: custom points emoji ──────────────────────────────────────────
POINTS_EMOJI = None

# ── House Relations ────────────────────────────────────────────────────────
NOTION_RELATIONS_DB_ID = "e8ed443de41e42f4bdcf190940864c37"
NOTION_MILITARY_TRACKING_DB_ID = "8823df60b95383ba96b481c3b1c302e9"
RELATIONS_LOGO_URL = "https://i.ibb.co/Wvg22HKX/Banner.png"
RELATION_EMOJI = {"Allied": "🟩", "Neutral": "⬜", "Enemy": "🟥"}
RELATION_REGION_ORDER = [
    "Crownlands", "Westerlands", "Riverlands", "The North", "Iron Isles",
    "The Reach", "Dorne", "Stormlands", "The Vale",
]

# ── Nicknames ──────────────────────────────────────────────────────────────
NICKNAME_MAX = 32  # Discord limit
NICKNAME_RANK_SHORT = {
    "Stormguard Lord Commander": "Lord Commander",
    "Secretary of the Court":    "Secretary",
    "Knight Banneret":           "Banneret",
}
