"""
Roster rebuild (one-off) — /rebuild_roster.

Builds the active roster (NOTION_ROSTER_DB_ID) straight from Discord: every member
holding recognised rank/detachment roles gets one row per detachment (rank,
region, lore name from their nickname, Discord ID/username), then each member's
Roblox username + ID are cross-referenced from the PREVIOUS roster
(NOTION_ROSTER_XREF_DB_ID) and filled in.

Deterministic + re-runnable: members already present (matched by Discord ID) are
skipped, so it can be run again safely. Dry-run by default.

Ruler-gated (Heir/Lady/Lord) since it's a bulk data operation.
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import notion_service as ns
import role_service
import sync_service
import util

log = logging.getLogger(__name__)


def _region_of(member: discord.Member) -> str:
    ids = {r.id for r in member.roles}
    for name, rid in config.REGION_ROLE_IDS.items():
        if rid in ids:
            return name
    return ""


class MigrateV2Cog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="rebuild_roster",
        description="[Ruler] Import everyone from Discord into the roster; backfill Roblox from the previous DB.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(dry_run="Preview only (default). Set False to actually write to Notion.")
    async def rebuild_roster(self, interaction: discord.Interaction, dry_run: bool = True):
        if not util.is_ruler(interaction.user):
            await interaction.response.send_message(
                "❌ Heir / Lady / Lord of Storm's End only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Roblox identities from the previous roster, keyed by Discord ID.
        xref = await ns.get_xref_roblox_map()
        # Skip anyone already in the (new) roster so re-runs are safe.
        existing = await ns.get_roster_v2_discord_ids()

        created = skipped = errors = no_roblox = 0
        members = seen = 0
        preview: list[str] = []

        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue
            rows = sync_service.derive_detachment_rows(member, guild)
            if not rows:
                continue  # holds no recognised rank/detachment roles
            members += 1
            uid = str(member.id)
            if uid in existing:
                skipped += 1
                continue

            region = _region_of(member)
            info = xref.get(uid, {})
            lorename = (sync_service.lorename_from_nick(member.nick) if member.nick
                        else "") or info.get("lorename", "")
            roblox_username = info.get("roblox_username", "")
            roblox_id = info.get("roblox_id", "")
            if not (roblox_username or roblox_id):
                no_roblox += 1

            if dry_run:
                if len(preview) < 30:
                    postings = ", ".join(
                        f"{d}/{r or sync_service.STARTING_RANK.get(d, 'Levy')}" for d, r in rows)
                    rb = f" • Roblox: {roblox_username or '—'}" if (roblox_username or roblox_id) else " • Roblox: (none)"
                    preview.append(f"• {member.display_name}: {postings}{rb}")
                created += 1
                continue

            try:
                for det, rank in rows:
                    create_rank = rank or sync_service.STARTING_RANK.get(det, "Levy")
                    await ns.create_imported_member(
                        roblox_username=roblox_username,
                        roblox_id=roblox_id,
                        lorename=lorename,
                        discord_username=str(member),
                        discord_user_id=uid,
                        detachment=det,
                        rank=create_rank,
                        points=0,
                        basic_levy=(create_rank != "Levy"),
                        date_enlisted=member.joined_at,
                        region=region,
                    )
                    await asyncio.sleep(0.34)  # stay under Notion's rate limit
                created += 1
            except Exception as exc:
                errors += 1
                log.error("rebuild_roster failed for %s: %s", uid, exc)

        mode = "🔎 DRY RUN — nothing written" if dry_run else "✅ Rebuild complete"
        msg = (
            f"**{mode}**\n"
            f"• Discord members with roster roles: **{members}**\n"
            f"• {'Would create' if dry_run else 'Created'}: **{created}**\n"
            f"• Skipped (already in roster): **{skipped}**\n"
            f"• No Roblox match in previous DB: **{no_roblox}**"
            + (f"\n• Errors: **{errors}** (see logs)" if errors else "")
        )
        if preview:
            msg += "\n\n__Preview (first 30):__\n" + "\n".join(preview)
        if dry_run:
            msg += "\n\nRun `/rebuild_roster dry_run:False` to write it."
        await interaction.followup.send(msg[:1990], ephemeral=True)

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
