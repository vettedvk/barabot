"""
Trials panel — persistent embed + button per requestable assessment (posted by
/setup_trials_panel). Only the two officer assessments are requestable —
Corporal and Lieutenant — and ONLY Knights may request them (the Knight Trial
itself and the Stormguard tryouts are invitation-run by their commands).

Clicking a button:
  1. checks the member meets the handbook criteria (Corporal: holds Knight;
     Lieutenant: serving Corporal) and belongs to a main retinue,
  2. pulls their Roblox username + roster standing from Notion, and
  3. creates a PRIVATE ticket channel — visible only to the requester, the
     hosts (Captain+), High Command, Bot Admin, and the bot — in the same
     category as the panel, pinging the hosts inside it.

Hosts close the ticket with the button in the channel; a transcript is DMed to
everyone who wrote in it and archived to the audit-log channel.

PERSISTENT: panel buttons use fixed custom_ids ("vel_trial_<key>"); the close
button uses "vel_trial_close". Register TrialRequestView per trial plus one
TrialTicketCloseView at startup (see bot.py).
"""

import io
import logging
import re
import time

import discord

import audit_log
import config
import notion_service as ns
import util

log = logging.getLogger(__name__)

# Per-user per-trial cooldown so the button can't be spammed (in-memory;
# resets on restart, which is fine for an anti-spam guard).
_COOLDOWN_SECONDS = 3600
_last_request: dict[tuple[int, str], float] = {}

_MAIN_RETINUES = ("Black Stags", "Thunderhooves")


# ── Trial definitions (handbook) ────────────────────────────────────────────
TRIALS: dict[str, dict] = {
    "corporal": {
        "name": "Corporal Assessment",
        "emoji": "⚔️",
        "color": discord.Color.dark_gold(),
        "target": "Corporal",
        "requirements": (
            "• **Achieved Knighthood**\n"
            "• Available consistently for at least **2 days per week** to host"
        ),
        "hosted_by": "a Captain+ of your retinue",
        "hosts": ["Captain"],
    },
    "lieutenant": {
        "name": "Lieutenant Assessment",
        "emoji": "🎖️",
        "color": discord.Color.gold(),
        "target": "Lieutenant",
        "requirements": (
            "• Served as **Corporal** for **3 weeks** minimum\n"
            "• Available consistently for at least **3 days per week** to host"
        ),
        "hosted_by": "a Captain+ of your retinue",
        "hosts": ["Captain"],
    },
}


# ── Helpers ─────────────────────────────────────────────────────────────────

def _holds(member: discord.Member, rank_name: str) -> bool:
    rid = config.RANK_ROLE_IDS.get(rank_name)
    return rid is not None and any(r.id == rid for r in member.roles)


def _retinue_of(member: discord.Member) -> str | None:
    for retinue in _MAIN_RETINUES:
        if any(r.id == config.COMPANY_ROLE_IDS[retinue] for r in member.roles):
            return retinue
    return None


def _check_eligibility(member: discord.Member, key: str, retinue: str | None) -> str | None:
    """Return a human-readable failure reason, or None if eligible."""
    if retinue is None:
        return ("You hold no retinue role — set your region on the retinue-sorting "
                "panel first, then request again.")
    if key == "corporal":
        if not _holds(member, "Knight"):
            return "Only **Knights** may request a Corporal Assessment — achieve Knighthood first."
    elif key == "lieutenant":
        if not _holds(member, "Corporal"):
            return "You must be a serving **Corporal** to request a Lieutenant Assessment."
    return None


def _station_count(guild: discord.Guild, key: str, retinue: str | None) -> str:
    """Advisory head-count for the target station within the requester's retinue."""
    target = TRIALS[key]["target"]
    role = guild.get_role(config.RANK_ROLE_IDS.get(target, 0))
    if role is None:
        return "—"
    members = role.members
    if retinue:
        retinue_role = guild.get_role(config.COMPANY_ROLE_IDS[retinue])
        if retinue_role:
            members = [m for m in members if retinue_role in m.roles]
    cap = "/3" if key == "lieutenant" else ""
    return f"{len(members)}{cap} {target}s in the {retinue}" if retinue else f"{len(members)} {target}s"


def _host_roles(guild: discord.Guild, key: str) -> list[discord.Role]:
    roles = []
    for name in TRIALS[key]["hosts"]:
        rid = config.RANK_ROLE_IDS.get(name)
        role = guild.get_role(rid) if rid else None
        if role:
            roles.append(role)
    return roles


def _access_roles(guild: discord.Guild, key: str) -> list[discord.Role]:
    """Everyone allowed into the ticket: hosts + Lord Commander + High Command + Bot Admin."""
    ids = {r.id for r in _host_roles(guild, key)}
    ids.add(config.RANK_ROLE_IDS["Stormguard Lord Commander"])
    ids |= set(config.HIGH_COMMAND_ROLE_IDS.values())
    ids.add(config.ROLE_BOT_ADMIN)
    return [role for rid in ids if (role := guild.get_role(rid))]


def build_trial_embed(key: str) -> discord.Embed:
    """The static panel embed for one trial (used by /setup_trials_panel)."""
    t = TRIALS[key]
    embed = discord.Embed(
        title=f"{t['emoji']} {t['name']}",
        description=(
            f"**Requirements**\n{t['requirements']}\n\n"
            f"**Hosted by:** {t['hosted_by']}"
        ),
        color=t["color"],
    )
    embed.set_footer(text="Press the button below to request this assessment — "
                          "a private channel opens with your hosts.")
    return embed


def _ticket_tag(key: str, user_id: int) -> str:
    return f"trial:{key}:{user_id}"


def _find_open_ticket(guild: discord.Guild, key: str, user_id: int) -> discord.TextChannel | None:
    tag = _ticket_tag(key, user_id)
    return next((c for c in guild.text_channels if c.topic and tag in c.topic), None)


def _channel_name(key: str, member: discord.Member) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", member.display_name.lower()).strip("-") or "member"
    return f"{key}-assessment-{base}"[:90]


# ── Request handling ────────────────────────────────────────────────────────

async def handle_trial_request(interaction: discord.Interaction, key: str) -> None:
    member: discord.Member = interaction.user
    guild = member.guild
    t = TRIALS[key]

    # One open ticket per member per trial.
    existing = _find_open_ticket(guild, key, member.id)
    if existing:
        await interaction.response.send_message(
            f"ℹ️ You already have an open ticket for this: {existing.mention}",
            ephemeral=True,
        )
        return

    # Cooldown (anti-spam)
    now = time.monotonic()
    last = _last_request.get((member.id, key), 0.0)
    if now - last < _COOLDOWN_SECONDS:
        minutes = int((_COOLDOWN_SECONDS - (now - last)) // 60) + 1
        await interaction.response.send_message(
            f"⏳ You already requested this recently — try again in ~{minutes} min.",
            ephemeral=True,
        )
        return

    retinue = _retinue_of(member)
    reason = _check_eligibility(member, key, retinue)
    if reason:
        await interaction.response.send_message(f"❌ {reason}", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    # Roblox username + roster positions from Notion (best-effort).
    roblox = ""
    positions: list[str] = []
    try:
        pages = await ns.get_members_by_discord_id(str(member.id))
        for page in pages:
            stats = ns.extract_member_stats(page["properties"])
            roblox = roblox or stats["roblox_username"]
            if stats["detachment"]:
                positions.append(f"{stats['detachment']} / {stats['rank'] or '—'}")
    except Exception as exc:
        log.warning("trials: Notion lookup failed for %s: %s", member, exc)

    # Create the private ticket channel in the panel's category.
    hosts = _host_roles(guild, key)
    overwrites: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True
        ),
        member: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
    }
    for role in _access_roles(guild, key):
        overwrites[role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    try:
        channel = await guild.create_text_channel(
            name=_channel_name(key, member),
            category=interaction.channel.category,
            overwrites=overwrites,
            topic=f"{t['name']} for {member} • {_ticket_tag(key, member.id)}",
            reason=f"{t['name']} requested by {member}",
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I couldn't create the ticket channel — I need the **Manage Channels** "
            "permission. Contact an admin.",
            ephemeral=True,
        )
        return
    except discord.HTTPException as exc:
        log.error("trials: channel creation failed for %s: %s", member, exc)
        await interaction.followup.send(
            "❌ Couldn't create the ticket channel — contact an admin.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"{t['emoji']} {t['name']} — Requested",
        color=t["color"],
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Requester", value=f"{member.mention} (`{member.id}`)", inline=False)
    embed.add_field(name="Roblox Username", value=roblox or "*(not on file)*", inline=True)
    if retinue:
        embed.add_field(name="Retinue", value=retinue, inline=True)
    embed.add_field(name="Current Standing", value="\n".join(positions) or "—", inline=False)
    embed.add_field(name="Requirements", value=t["requirements"], inline=False)
    embed.add_field(name="Head-count (advisory)", value=_station_count(guild, key, retinue), inline=True)
    embed.set_footer(text="Hosts: arrange the assessment here, then close the ticket.")

    await channel.send(
        content=" ".join(r.mention for r in hosts) + f" — {member.mention}",
        embed=embed,
        view=TrialTicketCloseView(),
        allowed_mentions=discord.AllowedMentions(roles=True, users=True),
    )
    _last_request[(member.id, key)] = now

    await interaction.followup.send(
        f"✅ Ticket opened: {channel.mention} — your hosts have been notified there.",
        ephemeral=True,
    )
    await audit_log.log_event(
        interaction.client,
        title=f"{t['emoji']} Assessment ticket opened — {t['name']}",
        color=t["color"],
        fields=[
            ("Member", f"{member.mention} (`{member.id}`)", True),
            ("Retinue", retinue or "—", True),
            ("Channel", channel.mention, True),
        ],
    )


class TrialTicketCloseView(discord.ui.View):
    """Persistent Close button posted inside each ticket channel."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="vel_trial_close",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Hosts/oversight only (event-host set = stations, court, LC, High
        # Command, or Bot Admin) — the requester can't close their own ticket.
        allowed = (
            util.is_admin(interaction.user)
            or util.has_any_role(interaction.user, config.EVENT_HOST_ROLE_IDS)
        )
        if not allowed:
            await interaction.response.send_message(
                "❌ Only the hosting ranks may close a ticket.", ephemeral=True
            )
            return

        channel = interaction.channel
        await interaction.response.send_message("🔒 Closing this ticket — sending transcripts…")

        # Build a plain-text transcript of the whole channel (oldest first) and
        # collect every human who wrote in it.
        lines = [
            f"Transcript — #{channel.name}",
            f"Topic: {channel.topic or '—'}",
            f"Closed by {interaction.user} on "
            f"{discord.utils.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            "─" * 40,
        ]
        participants: set[discord.abc.User] = set()
        try:
            async for msg in channel.history(limit=None, oldest_first=True):
                stamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
                content = msg.content or ""
                if msg.embeds:
                    embeds = ", ".join(e.title or "untitled" for e in msg.embeds)
                    content = (content + " " if content else "") + f"[embed: {embeds}]"
                if msg.attachments:
                    content += " " + " ".join(a.url for a in msg.attachments)
                lines.append(f"[{stamp}] {msg.author}: {content}")
                if not msg.author.bot:
                    participants.add(msg.author)
        except discord.HTTPException as exc:
            log.warning("trials: couldn't read history of %s: %s", channel, exc)

        transcript = "\n".join(lines).encode("utf-8")
        filename = f"{channel.name}-transcript.txt"

        # DM the transcript to everyone who sent a message in the ticket.
        for user in participants:
            try:
                await user.send(
                    f"📄 Transcript of the closed assessment ticket **#{channel.name}**:",
                    file=discord.File(io.BytesIO(transcript), filename=filename),
                )
            except discord.HTTPException:
                pass  # DMs closed or user left — best-effort

        # Keep a permanent copy in the audit-log channel.
        log_channel = interaction.client.get_channel(config.CHANNEL_COMMAND_LOG)
        if log_channel:
            try:
                await log_channel.send(
                    f"🔒 Assessment ticket **#{channel.name}** closed by {interaction.user.mention} — "
                    f"transcript DMed to {len(participants)} participant(s).",
                    file=discord.File(io.BytesIO(transcript), filename=filename),
                )
            except discord.HTTPException as exc:
                log.warning("trials: couldn't post transcript to log channel: %s", exc)

        try:
            await channel.delete(reason=f"Assessment ticket closed by {interaction.user}")
        except discord.HTTPException as exc:
            log.warning("trials: couldn't delete ticket channel %s: %s", channel, exc)


class TrialRequestView(discord.ui.View):
    """One persistent button for one trial. Register one instance per trial."""

    def __init__(self, trial_key: str):
        super().__init__(timeout=None)
        self.trial_key = trial_key
        t = TRIALS[trial_key]
        button = discord.ui.Button(
            label=f"Request {t['name']}",
            emoji=t["emoji"],
            style=discord.ButtonStyle.primary,
            custom_id=f"vel_trial_{trial_key}",
        )
        button.callback = self._request
        self.add_item(button)

    async def _request(self, interaction: discord.Interaction):
        await handle_trial_request(interaction, self.trial_key)
