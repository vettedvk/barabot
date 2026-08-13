"""
Reports cog — weekly automated command reporting, run once every Monday.

  • Inactivity report — active members with no logged event attendance in the
    last config.INACTIVITY_DAYS days (new members excused).
  • Command digest — a one-glance summary of the week (enlistments, discharges,
    LOAs, events, promotions, current inactivity).
  • Leaderboard — top members by points/trainings EARNED THIS WEEK, posted in
    the advancement channel.

The inactivity report and digest post to the action/command log, ping Blood of
the Storms, and DM the house lead. Everything is derived from the existing
Notion logs (Event Log, Discharge/LOA/Advancement logs) — no snapshots.
"""

import logging
from datetime import datetime, time as dtime, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

import config
import notion_service as ns

log = logging.getLogger(__name__)

UK_TZ = ZoneInfo("Europe/London")


class ReportsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.weekly_reports.start()

    def cog_unload(self):
        self.weekly_reports.cancel()

    # ── delivery ─────────────────────────────────────────────────────────

    async def _deliver_to_command(self, embed: discord.Embed):
        """Post to the action log (pinging Blood of the Storms) + DM the lead."""
        channel = self.bot.get_channel(config.CHANNEL_COMMAND_LOG)
        if channel is not None:
            try:
                await channel.send(
                    content=f"<@&{config.ROLE_HIGHBORN}>",
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
            except discord.HTTPException:
                pass
        try:
            lead = await self.bot.fetch_user(config.HOUSE_LEAD_DM_ID)
            await lead.send(embed=embed)
        except discord.HTTPException:
            pass

    # ── data ─────────────────────────────────────────────────────────────

    async def _inactive_members(self) -> list[dict]:
        recent = await ns.get_recent_log("NOTION_EVENT_LOG_DB_ID", config.INACTIVITY_DAYS)
        active_uids = {ns.event_log_points(p)[0] for p in recent}

        now = datetime.now(timezone.utc)
        out, seen = [], set()
        for page in await ns.get_all_active_members():
            s = ns.extract_member_stats(page["properties"])
            uid = s["discord_user_id"]
            if not uid or uid in seen:
                continue
            seen.add(uid)
            if uid in active_uids:
                continue
            # Excuse members enlisted within the inactivity window.
            if s.get("date_enlisted"):
                try:
                    enl = datetime.fromisoformat(s["date_enlisted"])
                    if enl.tzinfo is None:
                        enl = enl.replace(tzinfo=timezone.utc)
                    if (now - enl).days < config.INACTIVITY_DAYS:
                        continue
                except ValueError:
                    pass
            out.append(s)
        return out

    # ── the three reports ────────────────────────────────────────────────

    async def _post_inactivity(self, inactive: list[dict]):
        embed = discord.Embed(
            title=f"😴 Inactivity Report — {config.INACTIVITY_DAYS}+ days",
            color=discord.Color.dark_red(),
        )
        if not inactive:
            embed.description = "Everyone's been active this fortnight. 🎉"
        else:
            lines = []
            for s in inactive[:40]:
                lines.append(f"• <@{s['discord_user_id']}> — {s['detachment'] or '—'} / {s['rank'] or '—'}")
            embed.description = "\n".join(lines)
            if len(inactive) > 40:
                embed.description += f"\n…and {len(inactive) - 40} more."
            embed.set_footer(text=f"{len(inactive)} member(s) with no logged attendance")
        await self._deliver_to_command(embed)

    async def _post_digest(self, inactive_count: int):
        enlist_7 = 0
        now = datetime.now(timezone.utc)
        seen = set()
        for page in await ns.get_all_active_members():
            s = ns.extract_member_stats(page["properties"])
            uid = s["discord_user_id"]
            if not uid or uid in seen:
                continue
            seen.add(uid)
            if s.get("date_enlisted"):
                try:
                    enl = datetime.fromisoformat(s["date_enlisted"])
                    if enl.tzinfo is None:
                        enl = enl.replace(tzinfo=timezone.utc)
                    if (now - enl).days < 7:
                        enlist_7 += 1
                except ValueError:
                    pass

        discharges = await ns.get_recent_log("NOTION_DISCHARGE_LOG_DB_ID", 7)
        loas = await ns.get_recent_log("NOTION_LOA_LOG_DB_ID", 7)
        events = await ns.get_recent_log("NOTION_EVENT_LOG_DB_ID", 7)
        advances = await ns.get_recent_log("NOTION_ADVANCEMENT_LOG_DB_ID", 7)

        def _approved(rows):
            return sum(1 for p in rows
                       if ((p["properties"].get("Status", {}) or {}).get("select") or {}).get("name") == "Approved")

        distinct_events = len({(p["properties"].get("RequestID", {}) or {}).get("number") for p in events}
                              - {None})
        promotions = sum(1 for p in advances
                         if ((p["properties"].get("Type", {}) or {}).get("select") or {}).get("name") == "Promotion")

        embed = discord.Embed(
            title="📊 Weekly Command Digest",
            description="Activity across House Baratheon over the last 7 days.",
            color=discord.Color.dark_gold(),
        )
        embed.add_field(name="🪖 New enlistments", value=str(enlist_7), inline=True)
        embed.add_field(name="⚔️ Promotions", value=str(promotions), inline=True)
        embed.add_field(name="📤 Discharges", value=str(_approved(discharges)), inline=True)
        embed.add_field(name="🌙 LOAs approved", value=str(_approved(loas)), inline=True)
        embed.add_field(name="📋 Events run", value=str(distinct_events), inline=True)
        embed.add_field(name="✅ Attendance credits", value=str(len(events)), inline=True)
        embed.add_field(name="😴 Currently inactive", value=str(inactive_count), inline=True)
        await self._deliver_to_command(embed)

    async def _post_leaderboard(self):
        channel = self.bot.get_channel(config.CHANNEL_PROMOTIONS)
        if channel is None:
            return
        events = await ns.get_recent_log("NOTION_EVENT_LOG_DB_ID", 7)
        points: dict[str, int] = {}
        trainings: dict[str, int] = {}
        for p in events:
            member, pts, _etype = ns.event_log_points(p)
            if not member:
                continue
            points[member] = points.get(member, 0) + pts
            trainings[member] = trainings.get(member, 0) + 1

        embed = discord.Embed(
            title="🏆 Weekly Leaderboard — earned this week",
            color=discord.Color.gold(),
        )
        if not points:
            embed.description = "No points were earned this week — get to training! ⚔️"
        else:
            top = sorted(points.items(), key=lambda kv: kv[1], reverse=True)[:10]
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, (uid, pts) in enumerate(top):
                badge = medals[i] if i < 3 else f"`{i + 1}.`"
                lines.append(f"{badge} <@{uid}> — **{pts}** pts · {trainings.get(uid, 0)} training(s)")
            embed.description = "\n".join(lines)
        embed.set_footer(text="Points earned in the last 7 days")
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    # ── weekly trigger (Mondays) ─────────────────────────────────────────

    @tasks.loop(time=dtime(hour=16, minute=0, tzinfo=timezone.utc))
    async def weekly_reports(self):
        try:
            # Only on Mondays (UK week boundary).
            if datetime.now(UK_TZ).weekday() != 0:
                return
            inactive = await self._inactive_members()
            await self._post_inactivity(inactive)
            await self._post_digest(len(inactive))
            await self._post_leaderboard()
            log.info("Weekly reports posted (%d inactive).", len(inactive))
        except Exception as exc:
            log.warning("weekly_reports skipped: %s", exc)

    @weekly_reports.before_loop
    async def _before_weekly(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ReportsCog(bot))
