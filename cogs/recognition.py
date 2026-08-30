"""
Recognition cog:
  /myprogress [member] — show a member's progress toward their next ladder rank.
  Service-milestone announcements — a daily pass that congratulates members in
  the advancement channel (config.CHANNEL_PROMOTIONS) when their tenure hits a
  milestone (100 days, then each year of service).

Only the auto ladder (Levy → … → Man-at-Arms) has "progress"; appointed ranks
(stations, Court, specialised, High Command) are set by hand.
"""

import logging
from datetime import time as dtime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import notion_service as ns
import util
from rank_engine import AUTO_LADDERS

log = logging.getLogger(__name__)

# Tenure milestones announced in the advancement channel.
MILESTONE_100 = 100


def _milestone_label(days: int) -> str | None:
    if days == MILESTONE_100:
        return "100 days of service"
    if days > 0 and days % 365 == 0:
        years = days // 365
        return f"{years} year{'s' if years > 1 else ''} of service"
    return None


class RecognitionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.milestone_check.start()

    def cog_unload(self):
        self.milestone_check.cancel()

    # ── /myprogress ──────────────────────────────────────────────────────

    @app_commands.command(
        name="myprogress",
        description="See how close you are to your next rank.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="(Officers) check another member instead of yourself")
    async def myprogress(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        if member is not None and member != interaction.user and not util.is_officer(interaction.user):
            await interaction.response.send_message(
                "❌ You can only check your own progress.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        page = await ns.get_fleet_member_by_discord_id(str(target.id))
        if page is None:
            await interaction.followup.send(
                "❌ No retinue roster record found — this only applies to main combat "
                "retinue members on the points ladder.", ephemeral=True)
            return

        stats = ns.extract_member_stats(page["properties"])
        company, rank, pts = stats["detachment"], stats["rank"], stats["points"]
        ladder = AUTO_LADDERS.get(company)

        who = "You are" if target == interaction.user else f"{target.mention} is"

        # Appointed ranks (stations, Court, specialised, High Command) don't
        # progress on points.
        if not ladder or rank not in ladder:
            await interaction.followup.send(
                f"ℹ️ {who} on an appointed rank (**{rank or '—'}** in "
                f"**{company or '—'}**) — no points progression.", ephemeral=True)
            return

        idx = ladder.index(rank)
        # Levy → Soldier is placement-driven, not points.
        if idx == 0:
            await interaction.followup.send(
                f"🪖 {who} a **Levy** — attend a **Basic Levy Training** and you'll be "
                f"placed into a retinue as a **Soldier**. Ours is the Fury!", ephemeral=True)
            return
        # Man-at-Arms is the ladder ceiling; Corporal and above are appointed.
        if idx >= len(ladder) - 1:
            await interaction.followup.send(
                f"🏆 {who} at the top of the ladder — **Man-at-Arms**. Ours is the Fury!",
                ephemeral=True)
            return

        step = config.RANK_STEP
        have = max(0, min(pts, step))
        next_rank = ladder[idx + 1]
        bar = "🟦" * have + "⬜" * (step - have)

        embed = discord.Embed(
            title=f"⚔️ Progress to {next_rank}",
            description=f"{bar}\n**{have} / {step}** event points",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"{company} • current rank: {rank}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── daily service-milestone pass ─────────────────────────────────────

    @tasks.loop(time=dtime(hour=17, minute=0, tzinfo=timezone.utc))
    async def milestone_check(self):
        try:
            await self._milestone_check_once()
        except Exception as exc:
            log.warning("milestone_check skipped: %s", exc)

    async def _milestone_check_once(self):
        channel = self.bot.get_channel(config.CHANNEL_PROMOTIONS)
        guild = self.bot.get_guild(config.GUILD_ID)
        if channel is None or guild is None:
            return

        pages = await ns.get_all_active_members()
        seen: set[str] = set()
        for page in pages:
            stats = ns.extract_member_stats(page["properties"])
            uid = stats["discord_user_id"]
            if not uid or uid in seen:
                continue
            seen.add(uid)

            label = _milestone_label(int(ns.tenure_days(stats)))
            if not label:
                continue
            gm = guild.get_member(int(uid)) if uid.isdigit() else None
            if gm is None:
                continue

            embed = discord.Embed(
                title="🎖️ Service Milestone",
                description=(
                    f"Congratulations {gm.mention} on **{label}** to House Baratheon! "
                    f"Your loyalty does not go unnoticed. Ours is the Fury."
                ),
                color=discord.Color.gold(),
            )
            try:
                await channel.send(
                    content=gm.mention,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            except discord.HTTPException:
                pass
            try:
                await ns.log_advancement(uid, "", "Milestone", detail=label)
            except Exception:
                pass

    @milestone_check.before_loop
    async def _before_milestone(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(RecognitionCog(bot))
