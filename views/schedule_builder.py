"""
Weekly training schedule — the interactive builder and the shared render/persist
helpers used by both the builder and the cog's weekly-wipe loop.

Design (see cogs/schedule.py):
  • The whole week lives in ONE Notion row as a JSON blob (state dict below).
  • Times are stored as UTC unix seconds and rendered with Discord's dynamic
    <t:UNIX:t> timestamp, so every viewer sees the event in THEIR OWN timezone.
    The builder asks the creator's timezone once so their typed local time can
    be converted to that absolute instant.
  • The public embed is posted once and edited in place forever after; edits in
    the builder auto-apply to it. Every Monday 00:00 UK it resets to a
    placeholder (handled by the cog).

state = {
    "week_start": "YYYY-MM-DD",   # Monday of the UK week this schedule is for
    "tz":         "Europe/London" or None,   # creator's IANA timezone
    "days":       {"0": {"event": str, "unix": int}, ...},  # 0=Mon .. 6=Sun
    "message_id": str or None,    # the posted public embed
    "channel_id": str or None,
}
"""

import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import discord

import config
import notion_service as ns

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]

UK_TZ = "Europe/London"

# Curated timezone dropdown (label -> IANA key). Kept under Discord's 25-option
# cap and skewed to where House members actually are (EU / Middle East / NA).
TZ_CHOICES = [
    ("UK — London (GMT/BST)",        "Europe/London"),
    ("Ireland — Dublin",             "Europe/Dublin"),
    ("Portugal — Lisbon",            "Europe/Lisbon"),
    ("Central Europe — Paris/Berlin", "Europe/Paris"),
    ("Eastern Europe — Athens",      "Europe/Athens"),
    ("Turkey — Istanbul",            "Europe/Istanbul"),
    ("Moscow",                       "Europe/Moscow"),
    ("UAE — Dubai",                  "Asia/Dubai"),
    ("India — Kolkata",              "Asia/Kolkata"),
    ("Singapore / Philippines",      "Asia/Singapore"),
    ("Japan / Korea",                "Asia/Tokyo"),
    ("Australia — Sydney (AEST)",    "Australia/Sydney"),
    ("Australia — Perth (AWST)",     "Australia/Perth"),
    ("New Zealand — Auckland",       "Pacific/Auckland"),
    ("US — Eastern (New York)",      "America/New_York"),
    ("US — Central (Chicago)",       "America/Chicago"),
    ("US — Mountain (Denver)",       "America/Denver"),
    ("US — Arizona (no DST)",        "America/Phoenix"),
    ("US — Pacific (Los Angeles)",   "America/Los_Angeles"),
    ("Brazil — São Paulo",           "America/Sao_Paulo"),
    ("UTC",                          "UTC"),
]
_TZ_LABEL = {key: label for label, key in TZ_CHOICES}


# ── week / time maths ───────────────────────────────────────────────────────

def current_uk_monday() -> date:
    """The date of Monday for the current week, in UK time."""
    now = datetime.now(ZoneInfo(UK_TZ))
    return now.date() - timedelta(days=now.weekday())


def parse_time(text: str):
    """Parse '20:00' / '9:30' (24h) -> (hour, minute), or None if invalid."""
    m = re.fullmatch(r"\s*([01]?\d|2[0-3]):([0-5]\d)\s*", text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def compute_unix(week_start_iso: str, day_index: int, tz: str, hh: int, mm: int) -> int:
    """The event's absolute time as unix seconds: that weekday's date in the
    current week, at the given local time in the creator's timezone."""
    d = date.fromisoformat(week_start_iso) + timedelta(days=day_index)
    local = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(tz))
    return int(local.timestamp())


# ── state helpers ───────────────────────────────────────────────────────────

def new_state() -> dict:
    return {
        "week_start": current_uk_monday().isoformat(),
        "tz": None,
        "days": {},
        "message_id": None,
        "channel_id": None,
    }


def load_state(row: dict | None) -> dict:
    """Parse the Notion row's Data blob into a state dict (blank state if none)."""
    if not row:
        return new_state()
    raw = ns.get_prop_text(row["properties"], "Data")
    if not raw:
        return new_state()
    try:
        state = json.loads(raw)
    except (ValueError, TypeError):
        return new_state()
    # Backfill any missing keys so callers can rely on the full shape.
    base = new_state()
    for key, default in base.items():
        state.setdefault(key, default)
    return state


async def save_state(state: dict) -> None:
    await ns.save_schedule_data(json.dumps(state))


# ── embeds ──────────────────────────────────────────────────────────────────

def render_schedule_embed(state: dict, *, draft: bool) -> discord.Embed:
    week_start = date.fromisoformat(state["week_start"])
    week_end = week_start + timedelta(days=6)

    title = "📅 Weekly Training Schedule" + (" — Draft" if draft else "")
    embed = discord.Embed(title=title, color=discord.Color.gold())

    days = state.get("days", {})
    lines = []
    for i, name in enumerate(WEEKDAYS):
        entry = days.get(str(i))
        if entry and entry.get("event"):
            lines.append(f"**{name}** — {entry['event']} · <t:{entry['unix']}:t>")
        else:
            lines.append(f"**{name}** — *Rest Day*")
    embed.description = "\n".join(lines)

    span = f"Week of {week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"
    if draft:
        tz_label = _TZ_LABEL.get(state.get("tz"), state.get("tz") or "not set")
        status = "Posted (edits apply live)" if state.get("message_id") else "Not posted yet"
        embed.set_footer(text=f"{span} • Your timezone: {tz_label} • {status}")
    else:
        embed.set_footer(text=f"{span} • Times show in your own local timezone")
    return embed


def placeholder_embed() -> discord.Embed:
    return discord.Embed(
        title="📅 Weekly Training Schedule",
        description="**Monday — Rest Day.**\nA new schedule will be posted within 24h.",
        color=discord.Color.gold(),
    )


# ── public message sync ─────────────────────────────────────────────────────

async def sync_public(client: discord.Client, state: dict) -> dict:
    """Post the public schedule embed if it doesn't exist yet, else edit it in
    place. Returns the (possibly updated) state with the message/channel ids."""
    channel = client.get_channel(config.CHANNEL_SCHEDULE)
    if channel is None:
        return state
    embed = render_schedule_embed(state, draft=False)

    msg_id = state.get("message_id")
    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed)
            return state
        except discord.NotFound:
            pass  # message was deleted — fall through and repost
        except discord.HTTPException:
            return state

    msg = await channel.send(embed=embed)
    state["message_id"] = str(msg.id)
    state["channel_id"] = str(channel.id)
    return state


# ── interactive builder ─────────────────────────────────────────────────────

class DayTimeModal(discord.ui.Modal):
    """Popup to set one day's event + time (blank event = Rest Day)."""

    def __init__(self, view: "SchedulerView", day_index: int):
        super().__init__(title=f"Set {WEEKDAYS[day_index]}")
        self.view_ref = view
        self.day_index = day_index

        existing = view.state.get("days", {}).get(str(day_index), {})
        # Prefill the time (converted back to the creator's timezone) so editing
        # a day doesn't force re-typing it.
        time_default = ""
        if existing.get("unix") and view.state.get("tz"):
            local = datetime.fromtimestamp(existing["unix"], ZoneInfo(view.state["tz"]))
            time_default = local.strftime("%H:%M")

        self.event = discord.ui.TextInput(
            label="Event (leave blank for a Rest Day)",
            placeholder="e.g. Retinue Training, Joint w/ House X, Tryouts",
            default=existing.get("event", ""),
            required=False,
            max_length=100,
        )
        self.time = discord.ui.TextInput(
            label="Time (24-hour, HH:MM)",
            placeholder="e.g. 20:00",
            default=time_default,
            required=False,
            max_length=5,
        )
        self.add_item(self.event)
        self.add_item(self.time)

    async def on_submit(self, interaction: discord.Interaction):
        view = self.view_ref
        event = self.event.value.strip()
        time_raw = self.time.value.strip()

        if not event:
            view.state["days"].pop(str(self.day_index), None)  # -> Rest Day
        else:
            parsed = parse_time(time_raw)
            if parsed is None:
                await interaction.response.send_message(
                    "❌ Enter the time as 24-hour **HH:MM** (e.g. `20:00`).",
                    ephemeral=True,
                )
                return
            hh, mm = parsed
            unix = compute_unix(view.state["week_start"], self.day_index, view.state["tz"], hh, mm)
            view.state["days"][str(self.day_index)] = {"event": event, "unix": unix}

        await interaction.response.defer()
        await view.persist_and_sync()
        await view.refresh_draft()


class SchedulerView(discord.ui.View):
    """Ephemeral builder shown to the staff member. State is written through to
    Notion on every change; once the public embed exists, changes also edit it
    live."""

    def __init__(self, state: dict, origin_interaction: discord.Interaction):
        super().__init__(timeout=600)
        self.state = state
        self.origin = origin_interaction
        self.client = origin_interaction.client

    def draft_embed(self) -> discord.Embed:
        return render_schedule_embed(self.state, draft=True)

    async def persist_and_sync(self) -> None:
        await save_state(self.state)
        if self.state.get("message_id"):
            self.state = await sync_public(self.client, self.state)
            await save_state(self.state)

    async def refresh_draft(self) -> None:
        try:
            await self.origin.edit_original_response(embed=self.draft_embed(), view=self)
        except discord.HTTPException:
            pass

    @discord.ui.select(
        placeholder="① Set your timezone",
        row=0,
        options=[discord.SelectOption(label=label, value=key) for label, key in TZ_CHOICES],
    )
    async def tz_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.state["tz"] = select.values[0]
        # Ack + update the UI first (stays inside Discord's 3s window), then persist.
        await interaction.response.edit_message(embed=self.draft_embed(), view=self)
        await self.persist_and_sync()

    @discord.ui.select(
        placeholder="② Pick a day to set an event",
        row=1,
        options=[discord.SelectOption(label=WEEKDAYS[i], value=str(i)) for i in range(7)],
    )
    async def day_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not self.state.get("tz"):
            await interaction.response.send_message(
                "❌ Set your timezone first (menu ①).", ephemeral=True
            )
            return
        await interaction.response.send_modal(DayTimeModal(self, int(select.values[0])))

    @discord.ui.button(label="Post / Update Public Schedule",
                       style=discord.ButtonStyle.success, emoji="📣", row=2)
    async def post_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.state = await sync_public(self.client, self.state)
        await save_state(self.state)
        await interaction.followup.send(
            f"✅ Public schedule posted/updated in <#{config.CHANNEL_SCHEDULE}>.",
            ephemeral=True,
        )
        await self.refresh_draft()

    @discord.ui.button(label="Finish", style=discord.ButtonStyle.secondary, row=2)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="✅ Schedule builder closed — your changes are saved.",
            embed=None, view=None,
        )
        self.stop()
