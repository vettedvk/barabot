"""
Weekly report — a pure-Discord digest of enlistments and promotions.

Two parts, no external storage:

  • Promotion listener: when a member GAINS a higher rank role by hand in Discord,
    the bot posts a promotion embed to CHANNEL_PROMOTIONS. Bot-initiated role
    edits and first-time rank grants (enlistment) are ignored — only a climb from
    an existing rank counts.

  • Weekly digest: every Monday (and on demand via /weekly_report) the bot scans
    the last 7 days of the enlistment-review and promotions channels and posts a
    summary to the command log, also DMing the house lead. Everything is read
    back out of Discord itself, so nothing needs to be persisted.
"""

import logging
from datetime import datetime, time as dtime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import role_service
import util

log = logging.getLogger(__name__)

# Global low → high rank ordering, used only to decide whether a role change was
# a promotion (the member's highest-ranked role moved up). Names map to
# config.RANK_ROLE_IDS; anything not listed is ignored.
RANK_ORDER = [
    "Levy", "Soldier", "Footman", "Veteran Footman", "Man-at-Arms",
    "Squire", "Guardsman", "Knight",
    "Corporal", "SGT at Arms", "Knight Banneret", "Lieutenant", "Captain",
    "Commander", "Marshal", "Stormguard Lord Commander",
    "Clerk", "Emissary", "Handmaiden", "Cupbearer",
    "Secretary of the Court", "Quartermaster", "Chancellor",
    "Council of Storm's End", "Blood of the Storms",
    "Heir of Storm's End", "Lady of Storm's End", "Lord of Storm's End",
]
# rank role id -> (index, name)
_RANK_BY_ID = {
    config.RANK_ROLE_IDS[name]: (i, name)
    for i, name in enumerate(RANK_ORDER)
    if name in config.RANK_ROLE_IDS
}


def _best_rank(role_ids: set[int]) -> tuple[int, str] | None:
    """Highest (index, name) among the rank roles held, or None."""
    ranks = [_RANK_BY_ID[rid] for rid in role_ids if rid in _RANK_BY_ID]
    return max(ranks, key=lambda x: x[0]) if ranks else None


class WeeklyReportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.weekly_loop.start()

    def cog_unload(self):
        self.weekly_loop.cancel()

    # ── Promotion detection (manual rank changes) ────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id != config.GUILD_ID or after.bot:
            return
        # Skip the bot's own role edits (enlistment grants etc.).
        if role_service.was_bot_edit(after.id):
            return

        before_best = _best_rank({r.id for r in before.roles})
        after_best = _best_rank({r.id for r in after.roles})
        # A promotion is a climb from an EXISTING rank to a higher one. A first
        # rank (enlistment) has no "before" and isn't announced.
        if not before_best or not after_best:
            return
        if after_best[0] <= before_best[0]:
            return

        await self._announce_promotion(after, before_best[1], after_best[1])

    async def _announce_promotion(self, member: discord.Member, old_rank: str, new_rank: str):
        channel = member.guild.get_channel(getattr(config, "CHANNEL_PROMOTIONS", 0))
        if channel is None:
            return
        embed = discord.Embed(
            title="⚔️ Promotion — Ours is the Fury!",
            description=(
                f"Congratulations {member.mention}, you have been promoted from "
                f"**{old_rank}** to **{new_rank}**! Your service to House Baratheon is recognised."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        try:
            await channel.send(
                content=f"🎉 {member.mention}",
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.HTTPException:
            pass

    # ── Weekly digest ────────────────────────────────────────────────────────
    @tasks.loop(time=dtime(hour=17, minute=0, tzinfo=timezone.utc))
    async def weekly_loop(self):
        # Fires daily at 17:00 UTC; only acts on Monday.
        if datetime.now(timezone.utc).weekday() != 0:
            return
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild:
            await self._post_report(guild, target=None)

    @weekly_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def _gather(self, guild: discord.Guild, days: int = 7):
        """Return (enlistments, promotions) — each a list of one-line strings —
        scanned from the review and promotions channels over the last `days`."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        enlistments: list[str] = []
        promotions: list[str] = []

        review = guild.get_channel(getattr(config, "CHANNEL_ENLISTMENT_REVIEW", 0))
        if review is not None:
            try:
                async for msg in review.history(limit=500, after=cutoff):
                    if not msg.embeds:
                        continue
                    embed = msg.embeds[0]
                    approved = any((f.name or "").startswith("✅ Approved") for f in embed.fields)
                    if not approved:
                        continue
                    fields = {f.name: f.value for f in embed.fields}
                    kind = "Military"
                    title = (embed.title or "").lower()
                    if "envoy" in title or "diplomatic" in title:
                        kind = "Envoy"
                    elif (fields.get("Type", "") or "").strip().lower() == "court":
                        kind = "Court"
                    who = fields.get("Applicant", "").split("(")[0].strip() or "—"
                    enlistments.append(f"{who} — {kind}")
            except discord.HTTPException as exc:
                log.warning("weekly_report: review scan failed: %s", exc)

        promo = guild.get_channel(getattr(config, "CHANNEL_PROMOTIONS", 0))
        if promo is not None:
            try:
                async for msg in promo.history(limit=500, after=cutoff):
                    if not msg.embeds:
                        continue
                    if "promotion" not in (msg.embeds[0].title or "").lower():
                        continue
                    desc = msg.embeds[0].description or ""
                    promotions.append(desc.replace("Congratulations ", "").strip()[:200])
            except discord.HTTPException as exc:
                log.warning("weekly_report: promotions scan failed: %s", exc)

        return enlistments, promotions

    async def _post_report(self, guild: discord.Guild, target: discord.Interaction | None):
        enlistments, promotions = await self._gather(guild)

        embed = discord.Embed(
            title="📅 Weekly Report — House Baratheon",
            description=f"Activity over the last 7 days (as of <t:{int(datetime.now(timezone.utc).timestamp())}:D>).",
            color=discord.Color.dark_gold(),
            timestamp=discord.utils.utcnow(),
        )
        enl_body = "\n".join(f"• {e}" for e in enlistments[:40]) or "— none —"
        promo_body = "\n".join(f"• {p}" for p in promotions[:40]) or "— none —"
        embed.add_field(name=f"📜 Enlistments ({len(enlistments)})", value=enl_body[:1024], inline=False)
        embed.add_field(name=f"⚔️ Promotions ({len(promotions)})", value=promo_body[:1024], inline=False)

        log_channel = guild.get_channel(getattr(config, "CHANNEL_COMMAND_LOG", 0))
        if log_channel is not None:
            try:
                await log_channel.send(embed=embed)
            except discord.HTTPException:
                pass

        lead_id = getattr(config, "HOUSE_LEAD_DM_ID", 0)
        if lead_id:
            lead = guild.get_member(lead_id) or self.bot.get_user(lead_id)
            if lead is not None:
                try:
                    await lead.send(embed=embed)
                except discord.HTTPException:
                    pass

        if target is not None:
            await target.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="weekly_report",
                          description="[Admin] Post the weekly enlistments & promotions digest now.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def weekly_report(self, interaction: discord.Interaction):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._post_report(interaction.guild, target=interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(WeeklyReportCog(bot))
