"""
Roster V2 migration (one-off) — /migrate_roster_v2.

Copies every current member from the legacy roster into the new
"Baratheon Roster V2" database, ONE row per member and WITHOUT a detachment
(unsorted) — they get placed into a retinue manually via Discord afterwards.

Deterministic + re-runnable: members already present in V2 (matched by Discord
ID) are skipped, so it can be run again safely. The live bot keeps using the old
roster until the structure cutover — this only writes to V2.

Ruler-gated (Heir/Lady/Lord) since it's a bulk data operation.
"""

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

import config
import notion_service as ns
import role_service
import util

log = logging.getLogger(__name__)

# Highest → lowest, for collapsing a multi-row member down to their top rank.
_RANK_PRIORITY = [
    "Lord of Storm's End", "Lady of Storm's End", "Heir of Storm's End",
    "Blood of the Storms", "Council of Storm's End",
    "Chancellor", "Quartermaster", "Secretary of the Court",
    "Marshal", "Commander", "Stormguard Lord Commander",
    "Captain", "Lieutenant", "Knight Banneret", "SGT at Arms", "Corporal",
    "Secretary", "Emissary", "Cupbearer", "Handmaiden", "Clerk",
    "Knight", "Guardsman", "Squire",
    "Man-at-Arms", "Veteran Footman", "Footman", "Soldier", "Levy",
]
_RANK_INDEX = {name: i for i, name in enumerate(_RANK_PRIORITY)}


def _top_rank(ranks: list[str]) -> str:
    present = [r for r in ranks if r]
    if not present:
        return ""
    return min(present, key=lambda r: _RANK_INDEX.get(r, 999))


class MigrateV2Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="migrate_roster_v2",
        description="[Ruler] One-off: copy all members into Roster V2, unsorted (no detachment).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def migrate_roster_v2(self, interaction: discord.Interaction):
        if not util.is_ruler(interaction.user):
            await interaction.response.send_message(
                "❌ Heir / Lady / Lord of Storm's End only.", ephemeral=True)
            return
        if not os.environ.get("NOTION_ROSTER_LEGACY_DB_ID"):
            await interaction.response.send_message(
                "❌ Legacy roster not configured (set NOTION_ROSTER_LEGACY_DB_ID).", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        existing = await ns.get_roster_v2_discord_ids()

        # Group every non-archived legacy row (Active + LOA) by Discord ID.
        by_uid: dict[str, list[dict]] = {}
        for page in await ns.get_legacy_roster_pages():
            s = ns.extract_member_stats(page["properties"])
            uid = s["discord_user_id"]
            if uid:
                by_uid.setdefault(uid, []).append(s)

        created = skipped = errors = 0
        for uid, rows in by_uid.items():
            if uid in existing:
                skipped += 1
                continue
            try:
                # Stats live on one row; max across rows captures them cleanly.
                rank = _top_rank([r["rank"] for r in rows])
                if any(r["status"] == "Active" for r in rows):
                    status = "Active"
                elif any(r["status"] == "LOA" for r in rows):
                    status = "LOA"
                else:
                    status = rows[0]["status"] or "Active"
                identity = max(rows, key=lambda r: r["points"])
                dates = [r["date_enlisted"] for r in rows if r["date_enlisted"]]

                await ns.create_roster_v2_member(
                    roblox_username=identity["roblox_username"],
                    roblox_id=identity["roblox_id"],
                    discord_user_id=uid,
                    discord_username=identity["discord_username"],
                    lorename=identity["lorename"],
                    rank=rank,
                    status=status,
                    # Per-rank points model: 'Event Points' now means points earned
                    # SINCE the last promotion, so everyone starts their current
                    # rank fresh at 0 (career total is no longer tracked here).
                    points=0,
                    tidepoints=max(r["tidepoints"] for r in rows),
                    combat_trainings=max(r["combat_trainings"] for r in rows),
                    joints=max(r["joints"] for r in rows),
                    prs=max(r["prs"] for r in rows),
                    skirmishes=max(r["skirmishes"] for r in rows),
                    days_served=max(r["days_served"] for r in rows),
                    date_enlisted=min(dates) if dates else "",
                    basic_levy=any(r["basic_levy"] for r in rows),
                )
                created += 1
                await asyncio.sleep(0.34)  # stay under Notion's rate limit
            except Exception as exc:
                errors += 1
                log.error("migrate_roster_v2 failed for %s: %s", uid, exc)

        await interaction.followup.send(
            f"✅ Roster V2 migration complete.\n"
            f"• Members found: **{len(by_uid)}**\n"
            f"• Created: **{created}**\n"
            f"• Skipped (already present): **{skipped}**"
            + (f"\n• Errors: **{errors}** (see logs)" if errors else "")
            + "\n\nEveryone is **unsorted** (no detachment) — place them into retinues via Discord.",
            ephemeral=True,
        )

    # ── /apply_roster_roles — sync Discord roles FROM the roster ──────────

    @app_commands.command(
        name="apply_roster_roles",
        description="[Ruler] Sync Discord roles from the roster: strip legacy roles, apply rank/detachment.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="Just this member (omit for the whole active roster).",
                           dry_run="Preview only (default). Set False to apply.")
    async def apply_roster_roles(self, interaction: discord.Interaction,
                                 member: discord.Member = None, dry_run: bool = True):
        if not util.is_ruler(interaction.user):
            await interaction.response.send_message(
                "❌ Heir / Lady / Lord of Storm's End only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        by_uid: dict[str, list[dict]] = {}
        for page in await ns.get_all_active_members():
            s = ns.extract_member_stats(page["properties"])
            if s["discord_user_id"]:
                by_uid.setdefault(s["discord_user_id"], []).append(s)

        targets = [str(member.id)] if member else list(by_uid.keys())
        changed = errors = 0
        preview: list[str] = []

        for uid in targets:
            rows = by_uid.get(uid)
            if not rows:
                continue
            gm = guild.get_member(int(uid)) if uid.isdigit() else None
            if gm is None:
                continue
            # Prefer a sorted row (has a detachment); else the unsorted one.
            primary = max(rows, key=lambda r: (1 if r["detachment"] else 0, r["points"]))
            det = primary["detachment"]
            rank = primary["rank"] or "Levy"
            legacy = [r for r in gm.roles if r.id in config.LEGACY_ROLE_IDS]

            if dry_run:
                if len(preview) < 30:
                    tag = f"{det or 'Unsorted'} / {rank}"
                    strip = f" −legacy[{', '.join(r.name for r in legacy)}]" if legacy else ""
                    preview.append(f"• {gm.display_name}: →{tag}{strip}")
                changed += 1
                continue

            try:
                bot_top = guild.me.top_role
                drop = [r for r in legacy if r < bot_top and not r.managed]
                if drop:
                    await gm.remove_roles(*drop, reason="Legacy role cleanup (restructure)")
                await role_service.apply_rank_and_company(gm, det, rank, lorename=primary["lorename"])
                await role_service.add_house_membership_roles(gm)
                changed += 1
                await asyncio.sleep(1.0)  # stay under Discord's member-edit budget
            except Exception as exc:
                errors += 1
                log.error("apply_roster_roles failed for %s: %s", uid, exc)

        mode = "🔎 DRY RUN — nothing changed" if dry_run else "✅ Applied"
        msg = (f"**{mode}**\nMembers to update: **{changed}**"
               + (f"\nErrors: **{errors}**" if errors else ""))
        if preview:
            msg += "\n\n__Preview (first 30):__\n" + "\n".join(preview)
        if dry_run:
            msg += "\n\nRun `/apply_roster_roles dry_run:False` to apply."
        await interaction.followup.send(msg[:1990], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MigrateV2Cog(bot))
