"""
Events cog:
  /event      — Military Command / Court / High Command announce a retinue (or
                House-wide) event by DMing everyone in it.
  /log_event  — the Court logs an event AFTER it happens: pick the event type,
                paste the attendees, and every attendee's Notion row gets the
                points, the attendance counter (or Basic Levy checkbox), a
                Days Served refresh, and an auto-promotion where earned.
                Replaces the old member-requested points flow.
"""

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

import audit_log
import config
import notion_service as ns
import role_service
import util
from rank_engine import apply_points
from views.placement_panel import PlacementView

log = logging.getLogger(__name__)

# The retinues summoned by a House-wide event (active retinues).
_HOUSE_WIDE = ["Stormbreakers", "Thunderhooves", "The Black Stags",
               "Stormguard", "Knights of the Storm"]

# Attendee parsing: <@123>, <@!123>, or bare 17-20 digit IDs.
_ID_RE = re.compile(r"<@!?(\d{17,20})>|\b(\d{17,20})\b")


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="event", description="Announce a retinue or house-wide event (Military Command+).")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(detachment="Which retinue to summon", title="Event title / description")
    @app_commands.choices(detachment=[
        app_commands.Choice(name="House-wide (everyone)",  value="House-wide"),
        app_commands.Choice(name="Stormbreakers",          value="Stormbreakers"),
        app_commands.Choice(name="Thunderhooves",          value="Thunderhooves"),
        app_commands.Choice(name="The Black Stags",        value="The Black Stags"),
        app_commands.Choice(name="Stormguard",             value="Stormguard"),
        app_commands.Choice(name="Knights of the Storm",   value="Knights of the Storm"),
    ])
    async def event(
        self,
        interaction: discord.Interaction,
        detachment: app_commands.Choice[str],
        title: str,
    ):
        if not util.is_officer(interaction.user):
            await interaction.response.send_message(
                "❌ Only Military Command may start events.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        targets = _HOUSE_WIDE if detachment.value == "House-wide" else [detachment.value]
        members: dict[int, discord.Member] = {}
        for det in targets:
            role_id = config.COMPANY_ROLE_IDS.get(det)
            role = interaction.guild.get_role(role_id) if role_id else None
            if role is None:
                continue
            for m in role.members:
                if not m.bot:
                    members[m.id] = m

        if not members:
            await interaction.followup.send(
                "❌ Couldn't find anyone to summon (check the retinue roles).", ephemeral=True
            )
            return

        scope = "House Baratheon" if detachment.value == "House-wide" else detachment.value
        message = (
            f"⚡ **{scope}** — an event is beginning!\n\n"
            f"**{title}**\n\n"
            f"Report in and stand ready. Ours is the Fury. — *{interaction.user.display_name}*"
        )

        sent = failed = 0
        for member in members.values():
            try:
                await member.send(message)
                sent += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

        await interaction.followup.send(
            f"✅ Event broadcast to **{scope}** — {sent} member(s) DM'd"
            + (f", {failed} couldn't be reached." if failed else "."),
            ephemeral=True,
        )

    # ── /log_event — the Court records attendance after an event ─────────

    @app_commands.command(
        name="log_event",
        description="[Court] Log an event's attendees — points/attendance/promotions go straight to Notion.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        event_type="What kind of event was it?",
        attendees="Everyone who attended — paste their @mentions (or IDs), separated by spaces",
        host="Who hosted the event",
        co_host="Who co-hosted (optional)",
        supervisor="Who supervised (optional)",
    )
    @app_commands.choices(event_type=[
        app_commands.Choice(name=f"{name} ({pts} pts)" if pts else f"{name} (attendance only)",
                            value=name)
        for name, pts in config.EVENT_TYPES.items()
    ])
    async def log_event(
        self,
        interaction: discord.Interaction,
        event_type: app_commands.Choice[str],
        attendees: str,
        host: discord.Member,
        co_host: discord.Member = None,
        supervisor: discord.Member = None,
    ):
        if not util.is_event_logger(interaction.user):
            await interaction.response.send_message("❌ Court members only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Parse unique attendee IDs in the order given.
        ids: list[int] = []
        for m in _ID_RE.finditer(attendees):
            uid = int(m.group(1) or m.group(2))
            if uid not in ids:
                ids.append(uid)
        if not ids:
            await interaction.followup.send(
                "❌ No attendees found — mention them (`@name`) or paste their IDs.",
                ephemeral=True,
            )
            return

        etype = event_type.value
        points = config.EVENT_TYPES.get(etype, 0)
        # The Event Log's single Host column carries all three staffing slots.
        host_name = str(host)
        if co_host:
            host_name += f" (co-host: {co_host})"
        if supervisor:
            host_name += f" (supervisor: {supervisor})"
        try:
            request_id = await ns.get_next_request_id()
        except Exception:
            request_id = 0  # event-log bookkeeping is best-effort

        logged: list[str] = []
        promoted: list[str] = []
        not_in_guild: list[str] = []
        no_roster: list[str] = []
        placement_candidates: list[tuple[str, str]] = []  # unsorted Levys after Basic Levy
        errors = 0

        for uid in ids:
            member = guild.get_member(uid)
            if member is None:
                not_in_guild.append(f"`{uid}`")
                continue
            try:
                page = await ns.get_fleet_member_by_discord_id(str(uid))
                if page is None:
                    no_roster.append(str(member))
                    continue
                props = page["properties"]
                stats = ns.extract_member_stats(props)
                company = stats["detachment"]

                # Per-rank points: 'Event Points' is points earned SINCE the last
                # promotion. Add this event's points; every RANK_STEP climbs one
                # auto-ladder rank (Soldier→…→Man-at-Arms), carrying the remainder.
                # Levy→Soldier is placement-driven (below), not points; manual and
                # station ranks just bank points.
                new_rank, new_points, promos = apply_points(
                    company, stats["rank"], stats["points"], points,
                    step=config.RANK_STEP,
                )
                await ns.apply_event_result(
                    page_id=page["id"], current_props=props,
                    new_points=new_points, event_type=etype, new_rank=new_rank,
                )
                await asyncio.sleep(0.34)
                if request_id:  # best-effort paper trail in the Event Log DB
                    try:
                        await ns.create_event_log_entry(
                            discord_user_id=str(uid), event_type=etype, points=points,
                            host=host_name, proof_link="", request_id=request_id,
                            status="Logged", approved_by=str(interaction.user),
                        )
                        request_id += 1
                        await asyncio.sleep(0.34)
                    except Exception as exc:
                        log.warning("log_event: event-log entry failed for %s: %s", uid, exc)

                logged.append(str(member))
                # Unsorted Levy who just did their Basic Levy Training → offer
                # the host a placement control at the end.
                if etype == config.BASIC_LEVY_EVENT and not company:
                    placement_candidates.append((str(uid), str(member)))
                if promos:
                    await role_service.apply_rank_and_company(
                        member, company, new_rank,
                        old_rank=stats["rank"], lorename=stats["lorename"],
                    )
                    promoted.append(f"{member} → **{new_rank}**")
                    try:
                        await member.send(
                            f"⚡ Your attendance at **{etype}** was logged — you've been "
                            f"promoted to **{new_rank}**! Ours is the Fury."
                        )
                    except discord.HTTPException:
                        pass
            except Exception as exc:
                errors += 1
                log.error("log_event: failed for %s: %s", uid, exc)

        staffing = f"host: {host}"
        if co_host:
            staffing += f", co-host: {co_host}"
        if supervisor:
            staffing += f", supervisor: {supervisor}"
        msg = (
            f"✅ **{etype}** logged ({staffing}).\n"
            f"Attendees credited: **{len(logged)}**"
            + (f" (+{points} pts each)" if points else " (Basic Levy Training ticked)")
            + f"\nPromotions: **{len(promoted)}**"
            + (f"\nErrors: **{errors}**" if errors else "")
        )
        if promoted:
            msg += "\n\n__Promoted:__\n" + "\n".join(f"• {p}" for p in promoted)
        if no_roster:
            msg += ("\n\n⚠️ __Not in the roster (nothing credited):__\n"
                    + ", ".join(no_roster))
        if not_in_guild:
            msg += "\n\n⚠️ __Unknown IDs (not in the server):__ " + ", ".join(not_in_guild)
        await interaction.followup.send(msg[:1990], ephemeral=True)

        # Basic Levy Training → post an in-channel placement control so the host
        # can sort each unsorted attendee into a retinue (they become Soldier).
        if placement_candidates and interaction.channel is not None:
            view = PlacementView(interaction.user.id, placement_candidates)
            try:
                await interaction.channel.send(
                    content=f"{interaction.user.mention} — place your new recruits into a retinue:",
                    embed=view.embed(), view=view,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException as exc:
                log.warning("log_event: couldn't post placement view: %s", exc)

        await audit_log.log_event(
            self.bot,
            title=f"📋 Event logged — {etype}",
            color=discord.Color.dark_gold(),
            fields=[
                ("Logged by", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Host", str(host), True),
                ("Co-host / Supervisor",
                 f"{co_host or '—'} / {supervisor or '—'}", True),
                ("Credited / Promoted", f"{len(logged)} / {len(promoted)}", True),
                ("Attendees", (", ".join(logged) or "—")[:1024], False),
            ],
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
