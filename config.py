"""
Central config — all IDs and constants live here.

2026-07 house switch: the guild is now HOUSE BARATHEON. Two region-based main
retinues (Black Stags = EU/Middle East, Thunderhooves = NA; Asia chooses), two
specialised retinues (Stormguard — members leave their main retinue; Knights of
the Storm — members KEEP their main retinue), and the Court (Clerk → Emissary →
Secretary; joining moves you out of your retinue). Only Knights may hold
officer stations (Corporal/Lieutenant/Captain).
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
    "Storm Champion":      1488659968054792392,
    "The Stags Seal":      1488659967941808134,
}

# High Command hierarchy (highest -> lowest). A member's High Command standing
# is their HIGHEST of these roles. Council of Storm's End and above = High
# Command. (The Stormguard Lord Commander role also sits in this section of the
# Discord list but is the Stormguard's top RANK — council membership itself is
# conferred by holding Council of Storm's End, given by hand.)
HIGH_COMMAND_ROLE_IDS = {
    "Lord of Storm's End":   1488659968096862335,
    "Lady of Storm's End":   1488659968096862334,
    "Heir of Storm's End":   1488659968096862333,
    "Blood of the Storms":   1488659968096862332,  # == ROLE_HIGHBORN
    "Council of Storm's End": 1488659968096862330,
}

# Roles that count as "Highborn" for highborn-gated commands: Blood of the
# Storms and ABOVE. (Council is High Command but NOT Highborn.)
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
# Inactivity report + command digest post to the action/command log, ping Blood
# of the Storms, and DM the house lead. The leaderboard posts to the advancement
# channel (CHANNEL_PROMOTIONS).
HOUSE_LEAD_DM_ID = 897916113499877398   # DM'd the weekly inactivity report + digest
INACTIVITY_DAYS  = 14                    # no logged attendance in this many days = inactive

# ── Strikes ────────────────────────────────────────────────────────────────
# A strike counts while it's younger than STRIKE_EXPIRY_DAYS. Reaching
# STRIKE_DEMOTE active strikes drops the member one ladder rank; STRIKE_REMOVE
# discharges them.
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

# Court of Storm's End membership role — AUTO-granted by role hygiene to
# anyone holding a court station (Clerk/Emissary/Secretary), removed when the
# station is lost.
ROLE_COURT = 1525947287803662521

# Station role — AUTO-granted by role hygiene to anyone holding a station
# (Corporal/Lieutenant/Captain/Clerk/Emissary/Secretary), removed when they
# hold none. Independent of the Military Command separator.
ROLE_STATION = 1522247670331342949

# Military-command ACCESS roles (Stormguard/Black Stag/Thunderhooves/Knight
# Command) — distributed BY HAND; they alone trigger the Military Command
# separator (stations do NOT — holding a station only grants the Station
# role). Hygiene never grants or removes the access roles themselves.
MILITARY_COMMAND_ROLE_IDS = {
    1488659967941808131,  # Stormguard Command
    1515481460688289862,  # Black Stag Command
    1515481526895378504,  # Thunderhooves Command
    1488659967941808130,  # Knight Command
}

# Banner shown on the enlistment panel (re-uploaded at post time so the link
# doesn't matter long-term).
ENLISTMENT_BANNER_URL = "https://i.ibb.co/Wvg22HKX/Banner.png"

# ── Retinue roles ──────────────────────────────────────────────────────────
# Main retinues are region-based. Stormguard members leave their main retinue;
# Knights of the Storm members KEEP theirs (multi-row); Court members leave
# their retinue for a Court row. High Command has no single role.
COMPANY_ROLE_IDS = {
    "Black Stags":          1515430116501753948,
    "Thunderhooves":        1515430181135716432,
    "Stormguard":           1522250233306681434,
    "Knights of the Storm": 1488659968067371083,
    "Court":                1525947287803662521,  # == ROLE_COURT
}

# Region → retinue auto-sort at enlistment. Asia is absent on purpose: Asian
# members choose their retinue themselves.
REGION_FLEETS = {
    "EU":          "Black Stags",
    "Middle East": "Black Stags",
    "NA":          "Thunderhooves",
}
REGION_CHOICES = ["EU", "NA", "Asia", "Middle East"]

# ── Rank role IDs ──────────────────────────────────────────────────────────
# Squire is SHARED by both specialised retinues; Lieutenant by the main
# retinues and the Stormguard; Captain by the main retinues and the Knights.
RANK_ROLE_IDS = {
    # Retinue ladder (Black Stags & Thunderhooves; auto-promoted by points)
    "Levy":            1488659967979290801,
    "Soldier":         1488659967979290802,
    "Footman":         1488659967979290803,
    "Veteran Footman": 1488659968033951871,
    "Man-at-Arms":     1488659967979290804,

    # Stations (manual; knights only — see role hygiene)
    "Corporal":   1488659967979290805,
    "Lieutenant": 1488659968067371086,
    "Captain":    1488659968096862329,

    # Court stations (manual)
    "Clerk":     1488659968054792383,
    "Emissary":  1526653081192894756,
    "Secretary": 1526653118526394389,

    # Specialised retinue ranks (manual; Stormguard outranks the Knights)
    "Squire":    1522250075756171355,
    "Guardsman": 1488659968067371084,
    "Knight":    1488659968054792385,
    "Stormguard Lord Commander": 1488659968054792390,

    # High Command (same IDs as HIGH_COMMAND_ROLE_IDS)
    "Council of Storm's End": 1488659968096862330,
    "Blood of the Storms":    1488659968096862332,
    "Heir of Storm's End":    1488659968096862333,
    "Lady of Storm's End":    1488659968096862334,
    "Lord of Storm's End":    1488659968096862335,
}

# Ranks per detachment, lowest → highest. Used to (a) detect the rank a member
# holds within a detachment (highest role they have from this list — Discord
# role position decides) and (b) as the cleanup list when role_service swaps
# rank roles. Squire/Knight are included in the MAIN retinues so a Knight of
# the Storm's retinue row shows Squire/Knight rather than their old ladder
# rank; stations still outrank them by role position.
DETACHMENT_RANKS = {
    "Black Stags":   ["Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms",
                      "Squire", "Knight", "Corporal", "Lieutenant", "Captain"],
    "Thunderhooves": ["Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms",
                      "Squire", "Knight", "Corporal", "Lieutenant", "Captain"],
    "Stormguard":    ["Squire", "Guardsman", "Lieutenant", "Stormguard Lord Commander"],
    "Knights of the Storm": ["Squire", "Knight", "Captain"],
    "Court":         ["Clerk", "Emissary", "Secretary"],
    "High Command":  ["Council of Storm's End", "Blood of the Storms", "Heir of Storm's End",
                      "Lady of Storm's End", "Lord of Storm's End"],
}

# Alias kept for role_service, which strips a detachment's rank roles on a swap.
COMPANY_RANKS = DETACHMENT_RANKS

# The five point-earning ladder ranks (auto ladder).
FLEET_RANKS = ["Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms"]
FLEET_RANK_ROLE_IDS = {RANK_ROLE_IDS[r] for r in FLEET_RANKS}

# Station roles: holders need no ladder rank (role hygiene strips it).
MILITARY_STATION_RANKS = ["Corporal", "Lieutenant", "Captain"]
COURT_STATION_RANKS    = ["Clerk", "Emissary", "Secretary"]
STATION_ROLE_IDS       = {RANK_ROLE_IDS[r] for r in MILITARY_STATION_RANKS + COURT_STATION_RANKS}
COURT_STATION_ROLE_IDS = {RANK_ROLE_IDS[r] for r in COURT_STATION_RANKS}

# Officer/manual ranks: never auto-promoted, protected from /purge
# auto-discharge (they go to the manual-review list instead).
OFFICER_RANKS = {
    "Corporal", "Lieutenant", "Captain",
    "Clerk", "Emissary", "Secretary",
    "Stormguard Lord Commander",
}

# Purge: these ranks are protected from auto-discharge but explicitly LISTED
# as needing a manual purge decision.
PURGE_FLAG_RANKS = {"Knight", "Guardsman"}

# /event hosts (explicit set — hierarchy position never gates permissions):
# stations + court + Lord Commander + High Command (+ Bot Admin via is_admin).
EVENT_HOST_ROLE_IDS = (
    {RANK_ROLE_IDS[r] for r in MILITARY_STATION_RANKS + COURT_STATION_RANKS}
    | {RANK_ROLE_IDS["Stormguard Lord Commander"]}
    | set(HIGH_COMMAND_ROLE_IDS.values())
)

# /log_event — the Court logs attendance after each event (points are no
# longer member-requested). Court stations/role + High Command (+ Bot Admin).
EVENT_LOGGER_ROLE_IDS = (
    set(COURT_STATION_ROLE_IDS)
    | {ROLE_COURT}
    | set(HIGH_COMMAND_ROLE_IDS.values())
)

# Command = Council of Storm's End and above. These members get an additional
# "High Command" roster row alongside their detachment row(s).
COMMAND_ROLE_IDS = set(HIGH_COMMAND_ROLE_IDS.values())

# Roles permitted to Accept/Decline enlistment & envoy applications.
ENLISTMENT_REVIEWER_ROLE_IDS = set(HIGH_COMMAND_ROLE_IDS.values()) | {
    RANK_ROLE_IDS["Captain"],
    RANK_ROLE_IDS["Lieutenant"],
    RANK_ROLE_IDS["Clerk"],
    RANK_ROLE_IDS["Emissary"],
    RANK_ROLE_IDS["Secretary"],
    ROLE_BOT_ADMIN,
}

# ── Command permission tiers ────────────────────────────────────────────────
# One place that decides who can run each class of command. Higher tiers can do
# everything the lower tiers can (the util.py predicates layer ADMIN onto the
# officer/logger checks). If a tier "isn't working", it's almost always because
# one of the role IDs below doesn't match the real Discord role.
#
#   RULER   — destructive / irreversible commands (bulk wipes, migrations, the
#             mass role pass). Heir + Lady + Lord of Storm's End only.
#   ADMIN   — every NON-destructive command. Bot Perms + Blood of the Storms +
#             Council of Storm's End, plus the rulers who outrank them.
#   OFFICER — the everyday roster / military commands. The four hand-given
#             Military Command access roles (ADMIN is layered on in util.py).
#   LOGGER  — /log_event only. The Court (ADMIN is layered on in util.py).

RULER_ROLE_IDS = {
    HIGH_COMMAND_ROLE_IDS["Heir of Storm's End"],
    HIGH_COMMAND_ROLE_IDS["Lady of Storm's End"],
    HIGH_COMMAND_ROLE_IDS["Lord of Storm's End"],
}

ADMIN_ROLE_IDS = {
    ROLE_BOT_ADMIN,                               # Bot Perms
    HIGH_COMMAND_ROLE_IDS["Blood of the Storms"],
    HIGH_COMMAND_ROLE_IDS["Council of Storm's End"],
} | RULER_ROLE_IDS

# Officer tier: the four Military Command access roles (Stormguard/Black Stag/
# Thunderhooves/Knight Command). ADMIN is added by util.is_officer.
OFFICER_ROLE_IDS = set(MILITARY_COMMAND_ROLE_IDS)

# Logger tier: the Court role. ADMIN is added by util.is_event_logger.
LOGGER_ROLE_IDS = {ROLE_COURT}

# LOA reviewers: Bot Admins + Officers (Military Command) + the Court. Composed
# from the tiers above by util.is_loa_reviewer, so it needs no separate set.
# Roster Status value written to a member's rows while they are on leave.
LOA_STATUS = "LOA"

# ── Separator (divider) roles ──────────────────────────────────────────────
# Role hygiene grants each member exactly the separators for the sections they
# hold a role in. TITLES and HIGH COMMAND sit above the bot and stay manual.
# UTIL goes to everyone.
SEPARATOR_TITLES           = 1488659968096862336  # manual
SEPARATOR_HIGH_COMMAND     = 1488659968096862331  # manual
SEPARATOR_COURT            = 1525946634674896906
SEPARATOR_MILITARY_COMMAND = 1488659967941808135
SEPARATOR_STORMGUARD       = 1522249886781804604
SEPARATOR_KNIGHTS          = 1522250356762083409
SEPARATOR_RANK             = 1488659968067371078
SEPARATOR_BLACK_STAGS      = 1526397224542797944
SEPARATOR_THUNDERHOOVES    = 1488659968067371085
SEPARATOR_STATUS           = 1488659967979290798
SEPARATOR_UTIL             = 1522252463057670236

STATUS_ROLE_IDS = {
    ROLE_HOUSE_BARATHEON,  # House Baratheon of Storm's End
    1526080693480849429,   # House Dondarrion of Blackhaven
    1518346655227969707,   # House Connington of Griffins Roost
    1488659967979290799,   # Sworn Vassal
    1488659967924895930,   # Genre Staff
    ROLE_ENVOY,            # Envoy
    ROLE_VISITOR,          # Visitor
    1488659967941808136,   # Bots
}

# separator role id -> set of role ids whose presence earns that separator.
# SEPARATOR_UTIL is intentionally absent: it is granted to EVERYONE.
SEPARATOR_TRIGGERS = {
    SEPARATOR_MILITARY_COMMAND: set(MILITARY_COMMAND_ROLE_IDS),
    SEPARATOR_COURT: {ROLE_COURT} | COURT_STATION_ROLE_IDS,
    SEPARATOR_STORMGUARD: {COMPANY_ROLE_IDS["Stormguard"]},
    SEPARATOR_KNIGHTS: {COMPANY_ROLE_IDS["Knights of the Storm"]},
    SEPARATOR_RANK: set(FLEET_RANK_ROLE_IDS) | {
        RANK_ROLE_IDS["Squire"], RANK_ROLE_IDS["Knight"], RANK_ROLE_IDS["Guardsman"],
    },
    SEPARATOR_BLACK_STAGS: {COMPANY_ROLE_IDS["Black Stags"]},
    SEPARATOR_THUNDERHOOVES: {COMPANY_ROLE_IDS["Thunderhooves"]},
    SEPARATOR_STATUS: set(STATUS_ROLE_IDS),
}

# ── Event types and base point values ──────────────────────────────────────
# Basic Levy Training gives no points — attendance itself is the Soldier gate
# (it ticks the "Basic Levy Training" checkbox). Everything else is 5 points.
EVENT_TYPES = {
    "Basic Levy Training": 0,
    "House-wide Training": 5,
    "Retinue Training":    5,
    "Joint Event":         5,
    "PR":                  5,
}

# The event whose approval ticks the Basic Levy Training checkbox.
BASIC_LEVY_EVENT = "Basic Levy Training"
BASIC_LEVY_FIELD = "Basic Levy Training"  # Notion checkbox column

# Notion field names for per-type attendance counters. "Trainings attended"
# for the Footman(3)/Veteran Footman(6) gates = Combat Trainings + Joints +
# PRs. The legacy "Skirmishes" column stays in Notion but is never counted.
EVENT_COUNTER_FIELDS = {
    "House-wide Training": "Combat Trainings",
    "Retinue Training":    "Combat Trainings",
    "Joint Event":         "Joints",
    "PR":                  "PRs",
}

# ── Sync worker interval (seconds) ─────────────────────────────────────────
SYNC_INTERVAL_SECONDS = 600  # 10 minutes

# Master kill-switch for the periodic Discord→Notion reconciliation. Shipped
# False for the Baratheon migration: run /cleanup_roles after deploy, verify,
# then /toggle_sync (and set this True for the next restart).
SYNC_ENABLED = False

# ── Optional: custom points emoji (e.g. "<:points:123456789>")  ────────────
POINTS_EMOJI = None  # <-- fill in if desired

# ── House Relations ────────────────────────────────────────────────────────
# Notion database (must be shared with the bot integration). Not a secret, so
# it lives here rather than in .env so it survives file re-uploads.
NOTION_RELATIONS_DB_ID = "e8ed443de41e42f4bdcf190940864c37"

# Legacy Military Tracking database (must be shared with the bot integration).
# Used only by the one-off /migrate_roster backfill to source Roblox IDs/usernames.
NOTION_MILITARY_TRACKING_DB_ID = "8823df60b95383ba96b481c3b1c302e9"
# Logo shown on the /relations embed.
RELATIONS_LOGO_URL = "https://i.ibb.co/Wvg22HKX/Banner.png"

RELATION_EMOJI = {"Allied": "🟩", "Neutral": "⬜", "Enemy": "🟥"}

# Region display order for the relations embed.
RELATION_REGION_ORDER = [
    "Crownlands", "Westerlands", "Riverlands", "The North", "Iron Isles",
    "The Reach", "Dorne", "Stormlands", "The Vale",
]

# ── Nicknames ──────────────────────────────────────────────────────────────
NICKNAME_MAX = 32  # Discord limit

# Long ranks use a short form in the "{rank}, {lorename}" nickname so lore
# names aren't truncated by Discord's 32-char cap.
NICKNAME_RANK_SHORT = {
    "Stormguard Lord Commander": "Lord Commander",
}
