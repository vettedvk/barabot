"""
Admin cog — roster management slash commands: /move_detachment, /set_rank,
/sync, /roster, /force_enlist, /force_discharge, /add_roster_entry,
/remove_roster_entry, /import_roster, /migrate_roster, /purge, and the
panel-setup commands. Discord is the source of truth; /sync mirrors role changes
into Notion (see sync_service).
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)


def _norm_name(s: str) -> str:
    """Normalise a lorename for cross-database matching (case/space/punct-insensitive)."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

import audit_log
import config
import notion_service as ns
import role_service
import sync_service
import util
from rank_engine import min_stats_for_rank
from roblox import validate_roblox_user, RobloxValidationError
from sync_service import STARTING_RANK, derive_detachment_and_rank, lorename_from_nick
from views.self_update_panel import SelfUpdatePanelView


def _is_admin(interaction: discord.Interaction) -> bool:
    return util.is_admin(interaction.user)


def _admin_check():
    """Full-admin tier — every non-destructive command (config.ADMIN_ROLE_IDS)."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def _officer_check():
    """Military Command access roles + full admin — the everyday roster commands."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not util.is_officer(interaction.user):
            await interaction.response.send_message(
                "❌ Military Command and above only.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def _ruler_check():
    """Heir / Lady / Lord of Storm's End only — the destructive commands."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not util.is_ruler(interaction.user):
            await interaction.response.send_message(
                "❌ Restricted to the Heir, Lady, and Lord of Storm's End.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


def _military_role_ids() -> set:
    """Role IDs that indicate someone is enlisted military (company or rank role)."""
    return set(config.COMPANY_ROLE_IDS.values()) | set(config.RANK_ROLE_IDS.values())


def _is_military(member: discord.Member) -> bool:
    ids = _military_role_ids()
    return any(r.id in ids for r in member.roles)


async def rank_autocomplete(interaction: discord.Interaction, current: str):
    """Suggest valid ranks as the admin types (config ranks — these have roles)."""
    cur = current.lower()
    return [
        app_commands.Choice(name=r, value=r)
        for r in config.RANK_ROLE_IDS
        if cur in r.lower()
    ][:25]


async def notion_rank_autocomplete(interaction: discord.Interaction, current: str):
    """Suggest ranks from the Notion roster's Rank options (incl. manually-added
    ones). Falls back to the config ranks if the schema can't be read."""
    try:
        options = await ns.get_select_options("Rank")
    except Exception:
        options = []
    if not options:
        options = list(config.RANK_ROLE_IDS)
    cur = current.lower()
    return [
        app_commands.Choice(name=r, value=r)
        for r in options
        if cur in r.lower()
    ][:25]


async def _dm_chunks(user: discord.abc.User, header: str, lines: list[str]) -> None:
    """DM `user` the lines under `header`, splitting to respect Discord's 2000-char cap."""
    buf = header
    for line in lines:
        if len(buf) + len(line) + 1 > 1900:
            try:
                await user.send(buf)
            except discord.HTTPException:
                return  # DMs closed or rate-limited — give up silently
            buf = ""
        buf += ("\n" if buf else "") + line
    if buf:
        try:
            await user.send(buf)
        except discord.HTTPException:
            pass


async def _dm_code_chunks(user: discord.abc.User, header: str, lines: list[str]) -> None:
    """DM `user` the lines inside ``` code blocks (chunked under the 2000-char cap)."""
    buf: list[str] = []
    size = len(header)
    first = True

    async def flush():
        nonlocal buf, size, first
        if not buf:
            return
        text = (header + "\n" if first else "") + "```\n" + "\n".join(buf) + "\n```"
        first = False
        buf, size = [], 0
        try:
            await user.send(text)
        except discord.HTTPException:
            pass

    for line in lines:
        if size + len(line) + 10 > 1800:
            await flush()
        buf.append(line)
        size += len(line) + 1
    await flush()


class PurgeView(discord.ui.View):
    """
    Paginated review + confirm for /purge. Each candidate is a dict:
        {key, member, page_id, label, roblox_username, roblox_id}
    The admin can page through the list, drop individuals via the select, then
    confirm. Confirming discharges each remaining member in Discord and archives
    their (single) Notion roster entry. Only the invoking admin may interact.
    """

    PAGE = 10

    def __init__(self, author_id: int, candidates: list[dict], message_url: str = ""):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.candidates = candidates
        self.message_url = message_url
        self.page = 0
        self._sync_components()

    @property
    def page_count(self) -> int:
        return max(1, (len(self.candidates) + self.PAGE - 1) // self.PAGE)

    def _page_slice(self) -> list[dict]:
        start = self.page * self.PAGE
        return self.candidates[start:start + self.PAGE]

    def _sync_components(self):
        slice_ = self._page_slice()
        sel = self.remove_user
        if slice_:
            sel.options = [discord.SelectOption(label=c["label"][:100], value=c["key"]) for c in slice_]
            sel.min_values = 1
            sel.max_values = len(slice_)
            sel.disabled = False
        else:
            sel.options = [discord.SelectOption(label="(empty)", value="none")]
            sel.disabled = True
        single_page = self.page_count <= 1
        self.prev_page.disabled = single_page
        self.next_page.disabled = single_page
        self.confirm.disabled = not self.candidates

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="⚠️ Purge — review before confirming", color=discord.Color.dark_red())
        if not self.candidates:
            embed.description = "The discharge list is now empty — nothing to do."
            return embed
        start = self.page * self.PAGE
        lines = [f"`{start + i + 1}.` {c['label']}" for i, c in enumerate(self._page_slice())]
        embed.description = "\n".join(lines)
        embed.set_footer(
            text=f"Page {self.page + 1}/{self.page_count} • "
                 f"{len(self.candidates)} member(s) will be discharged"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the admin who ran /purge can use this.", ephemeral=True
            )
            return False
        return True

    async def _rerender(self, interaction: discord.Interaction):
        self._sync_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="Remove a user from the discharge list…",
        options=[discord.SelectOption(label="(empty)", value="none")],
        row=0,
    )
    async def remove_user(self, interaction: discord.Interaction, select: discord.ui.Select):
        keys = set(select.values)
        self.candidates = [c for c in self.candidates if c["key"] not in keys]
        if self.page >= self.page_count:
            self.page = self.page_count - 1
        await self._rerender(interaction)

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=1)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = (self.page - 1) % self.page_count
        await self._rerender(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = (self.page + 1) % self.page_count
        await self._rerender(interaction)

    @discord.ui.button(label="Confirm Discharge", style=discord.ButtonStyle.danger, emoji="⚠️", row=2)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        targets = list(self.candidates)
        await interaction.response.edit_message(
            content=f"⏳ Discharging **{len(targets)}** member(s)…", embed=None, view=self
        )

        discharged = failed = 0
        manifest: list[str] = []
        discharged_tags: list[str] = []
        for c in targets:
            try:
                await ns.discharge_member(c["page_id"])
                await role_service.apply_discharge_roles(c["member"], lorename=c.get("lorename", ""))
                try:
                    await c["member"].send(
                        "You have been **discharged** from House Baratheon for not "
                        "responding to a required muster. Contact command if you "
                        "believe this was in error."
                    )
                    await asyncio.sleep(1.0)  # avoid the 40003 DM rate limit
                except discord.HTTPException:
                    pass
                discharged += 1
                discharged_tags.append(str(c["member"]))
                manifest.append(
                    f"{c['member']} | {c['roblox_username'] or '(unknown)'} | discharged"
                )
            except Exception as exc:
                failed += 1
                log.error("Purge: failed to discharge %s: %s", c.get("key"), exc)

        summary = f"✅ Purge complete. Discharged **{discharged}** member(s)."
        if failed:
            summary += f" ⚠️ **{failed}** failed (see logs)."
        await interaction.edit_original_response(content=summary, view=self)
        if manifest:
            await _dm_code_chunks(
                interaction.user, f"🗒️ **Purge manifest** — {discharged} discharged:", manifest
            )

        # Permanent record in the audit-log channel.
        fields = [
            ("Purged by", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
            ("Discharged", str(discharged), True),
        ]
        if failed:
            fields.append(("Failed", str(failed), True))
        if self.message_url:
            fields.append(("Muster message", f"[jump]({self.message_url})", True))
        if discharged_tags:
            fields.append(("Members", (", ".join(discharged_tags))[:1024], False))
        await audit_log.log_event(
            interaction.client,
            title="🧹 Purge executed",
            color=discord.Color.dark_red(),
            fields=fields,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="❌ Purge cancelled. No one was discharged.", embed=None, view=self
        )


class StaleRankReviewView(discord.ui.View):
    """
    Transient review for stale station ranks found by /sync: Notion rows whose
    station/court rank's Discord role is no longer held. The admin picks which
    ranks to CLEAR from Notion (the cell is emptied — the member keeps their
    row); anything not cleared stays until fixed by hand or /set_rank.
    Only the invoking admin may act; expires after 600s.
    """

    def __init__(self, author_id: int, entries: list[dict]):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.entries = {e["page_id"]: e for e in entries[:25]}  # select cap
        self.selected: set[str] = set()

        sel = discord.ui.Select(
            placeholder="Select the stale ranks to clear…",
            min_values=1,
            max_values=len(self.entries),
            options=[
                discord.SelectOption(label=e["label"][:100], value=pid)
                for pid, e in self.entries.items()
            ],
            row=0,
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the admin who ran /sync can use this.", ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        self.selected = set(interaction.data["values"])
        await interaction.response.defer()

    @discord.ui.button(label="Clear Selected Ranks", style=discord.ButtonStyle.danger, emoji="🧹", row=1)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected:
            await interaction.response.send_message(
                "❌ Pick at least one entry in the dropdown first.", ephemeral=True
            )
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"⏳ Clearing **{len(self.selected)}** stale rank(s)…", view=self
        )

        cleared, errors, done_labels = 0, 0, []
        for pid in self.selected:
            try:
                await ns.clear_member_rank(pid)
                cleared += 1
                done_labels.append(self.entries[pid]["label"])
                await asyncio.sleep(0.34)
            except Exception as exc:
                errors += 1
                log.error("stale-rank clear failed for %s: %s", pid, exc)

        summary = f"✅ Cleared **{cleared}** stale rank(s)."
        if errors:
            summary += f" ⚠️ **{errors}** failed (see logs)."
        summary += (
            "\nTheir Rank cells are now empty — give them their real rank via "
            "`/set_rank` or a Discord rank role (sync will fill it in)."
        )
        await interaction.edit_original_response(content=summary, view=self)
        if done_labels:
            await audit_log.log_event(
                interaction.client,
                title="🧹 Stale station ranks cleared",
                color=discord.Color.dark_gold(),
                fields=[
                    ("Admin", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                    ("Cleared", "\n".join(done_labels)[:1024], False),
                ],
            )

    @discord.ui.button(label="Keep All", style=discord.ButtonStyle.secondary, row=1)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="ℹ️ Kept as-is. They'll be flagged again on the next /sync.", view=self
        )


class ClearRosterConfirmView(discord.ui.View):
    """
    Transient confirm/cancel for /clear_roster. Archives EVERY page in the
    roster DB. Only the invoking admin may act; expires after 120s.
    """

    def __init__(self, author_id: int, page_ids: list[str]):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.page_ids = page_ids

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the admin who ran /clear_roster can confirm this.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Clear Entire Roster", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"⏳ Clearing **{len(self.page_ids)}** roster row(s)…", embed=None, view=self
        )

        cleared = errors = 0
        for pid in self.page_ids:
            try:
                await ns.archive_page(pid)
                cleared += 1
                await asyncio.sleep(0.34)  # Notion ~3 req/s
            except Exception as exc:
                errors += 1
                log.error("clear_roster: failed to archive %s: %s", pid, exc)

        summary = f"✅ Roster cleared. Archived **{cleared}** row(s)."
        if errors:
            summary += f" ⚠️ **{errors}** failed (see logs)."
        summary += "\nYou can now run `/import_roster dry_run:False` to rebuild it."
        await interaction.edit_original_response(content=summary, view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="❌ Cancelled. The roster was not touched.", embed=None, view=self
        )


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /move_detachment ─────────────────────────────────────────────────

    @app_commands.command(name="move_detachment", description="[Officer] Move a member to a different detachment (optionally set their rank).")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        member="The Discord member",
        company="Target detachment",
        rank="Rank in the new detachment (optional; defaults to that detachment's starting rank)",
    )
    @app_commands.choices(company=[
        app_commands.Choice(name="Black Stags",          value="Black Stags"),
        app_commands.Choice(name="Thunderhooves",        value="Thunderhooves"),
        app_commands.Choice(name="Stormguard",           value="Stormguard"),
        app_commands.Choice(name="Knights of the Storm", value="Knights of the Storm"),
        app_commands.Choice(name="Court",                value="Court"),
        app_commands.Choice(name="High Command",         value="High Command"),
    ])
    @app_commands.autocomplete(rank=rank_autocomplete)
    @_officer_check()
    async def set_company(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        company: app_commands.Choice[str],
        rank: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        # Multi-row members: move their FLEET row when they have one (fleet
        # membership is the "primary" posting); otherwise their first row.
        roster_page = await ns.get_fleet_member_by_discord_id(str(member.id))
        if not roster_page:
            await interaction.followup.send("❌ Member not found in roster.", ephemeral=True)
            return

        props   = roster_page["properties"]
        stats   = ns.extract_member_stats(props)
        old_company = stats["detachment"]
        new_company = company.value

        # Rank: use the one given (validated), else the detachment's starting rank.
        if rank:
            if rank not in config.RANK_ROLE_IDS:
                await interaction.followup.send(
                    f"❌ Unknown rank `{rank}`. Leave blank to use the starting rank.", ephemeral=True
                )
                return
            new_rank = rank
        else:
            new_rank = STARTING_RANK.get(new_company, "Levy")

        if old_company == new_company and stats["rank"] == new_rank:
            await interaction.followup.send(
                f"ℹ️ {member.mention} is already {new_company} / {new_rank}.", ephemeral=True
            )
            return

        await ns.set_member_company(roster_page["id"], new_company, new_rank)
        await role_service.apply_rank_and_company(
            member, new_company, new_rank,
            old_company=old_company, old_rank=stats["rank"], lorename=stats["lorename"]
        )

        await interaction.followup.send(
            f"✅ {member.mention} moved to **{new_company}** at rank **{new_rank}**.",
            ephemeral=True,
        )

    # ── /set_rank ────────────────────────────────────────────────────────

    @app_commands.command(name="set_rank", description="[Officer] Manually set a member's rank.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="The Discord member", rank="Target rank")
    @app_commands.autocomplete(rank=rank_autocomplete)
    @_officer_check()
    async def set_rank(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        rank: str,
    ):
        await interaction.response.defer(ephemeral=True)

        if rank not in config.RANK_ROLE_IDS:
            valid = ", ".join(config.RANK_ROLE_IDS.keys())
            await interaction.followup.send(
                f"❌ Unknown rank `{rank}`. Valid ranks: {valid}", ephemeral=True
            )
            return

        pages = await ns.get_members_by_discord_id(str(member.id))
        if not pages:
            await interaction.followup.send("❌ Member not found in roster.", ephemeral=True)
            return

        # Multi-row members: update the row whose detachment ladder contains
        # this rank (e.g. Guardsman → their Stormguard row), else the first row.
        roster_page, stats = None, None
        for p in pages:
            s = ns.extract_member_stats(p["properties"])
            if rank in config.DETACHMENT_RANKS.get(s["detachment"], []):
                roster_page, stats = p, s
                break
        if roster_page is None:
            roster_page = pages[0]
            stats = ns.extract_member_stats(roster_page["properties"])
        company = stats["detachment"]

        await ns.set_member_rank(roster_page["id"], rank)
        await role_service.apply_rank_and_company(
            member, company, rank, old_rank=stats["rank"], lorename=stats["lorename"]
        )

        await interaction.followup.send(
            f"✅ {member.mention}'s rank set to **{rank}**.", ephemeral=True
        )

    # ── /sync ────────────────────────────────────────────────────────────

    @app_commands.command(
        name="sync",
        description="[Officer] Reconcile manual Discord role changes into Notion (skips High Command).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @_officer_check()
    async def sync(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        s = await sync_service.reconcile(interaction.guild, self.bot)
        stale = s.get("stale_station") or []
        await interaction.followup.send(
            "✅ Sync complete.\n"
            f"Rows created (new/transferred detachment): **{s.get('created', 0)}**\n"
            f"Rank updates: **{s.get('rank_updated', 0)}**\n"
            f"Rows archived (left detachment): **{s.get('archived', 0)}**\n"
            f"Abandoned posts logged: **{s.get('abandoned', 0)}**\n"
            f"Skipped (multi-entry / High Command / no change): **{s.get('skipped', 0)}**\n"
            f"Errors: **{s.get('errors', 0)}**\n"
            f"Lore names updated from nicknames: **{s.get('lorename_updated', 0)}**\n"
            f"Stale station ranks in Notion: **{len(stale)}**",
            ephemeral=True,
        )
        if stale:
            chunk = ("⚠️ **Stale station ranks** — the Notion row still carries a rank whose "
                     "Discord role is gone (sync never overwrites manual ranks):\n")
            for entry in stale:
                line = entry["text"]
                if len(chunk) + len(line) + 3 > 1900:
                    await interaction.followup.send(chunk, ephemeral=True)
                    chunk = ""
                chunk += f"\n• {line}"
            if chunk.strip():
                await interaction.followup.send(chunk, ephemeral=True)

            # Ask what to do: clear the stale ranks, or keep them.
            note = "" if len(stale) <= 25 else f"\n(Showing the first 25 of {len(stale)}.)"
            await interaction.followup.send(
                "Should any of these be **removed**? Pick the ones to clear from Notion "
                f"(the member keeps their row; the Rank cell is emptied):{note}",
                view=StaleRankReviewView(interaction.user.id, stale),
                ephemeral=True,
            )

    # ── /roster ──────────────────────────────────────────────────────────

    @app_commands.command(name="roster", description="View a member's roster record.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="The Discord member (defaults to yourself)")
    async def roster(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer(ephemeral=True)

        target = member or interaction.user
        pages = await ns.get_members_by_discord_id(str(target.id))
        if not pages:
            await interaction.followup.send("❌ No roster record found.", ephemeral=True)
            return

        embed = discord.Embed(title=f"Roster — {target.display_name}", color=discord.Color.blue())

        if len(pages) == 1:
            stats = ns.extract_member_stats(pages[0]["properties"])
            embed.add_field(name="Detachment",   value=stats["detachment"] or "—", inline=True)
            embed.add_field(name="Rank",         value=stats["rank"] or "—",       inline=True)
            embed.add_field(name="Event Points", value=str(stats["points"]),       inline=True)
            embed.add_field(name="Tidepoints",   value=str(stats["tidepoints"]),   inline=True)
            embed.add_field(name="Status",       value=stats["status"] or "—",     inline=True)
            embed.add_field(
                name="Attendance",
                value=(
                    f"Basic Levy: {'✅' if stats['basic_levy'] else '❌'} | "
                    f"Trainings: {stats['combat_trainings']} | "
                    f"Joint: {stats['joints']} | "
                    f"PR: {stats['prs']}"
                ),
                inline=False,
            )
        else:
            # Command members may hold several positions across detachments.
            lines = []
            for p in pages:
                s = ns.extract_member_stats(p["properties"])
                lines.append(
                    f"• **{s['detachment'] or '—'}** — {s['rank'] or '—'} "
                    f"({s['points']} pts, status: {s['status'] or '—'})"
                )
            embed.description = f"Holds **{len(pages)}** positions:"
            embed.add_field(name="Positions", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /self_update ─────────────────────────────────────────────────────

    @app_commands.command(
        name="self_update",
        description="[Admin] Post the 'Update Roblox Info' self-service panel in this channel.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @_admin_check()
    async def self_update(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🪪 Update Your Roblox Info",
            description=(
                "Is your Roblox ID/username missing from the roster? Press the button "
                "below to add it. Your answer is saved automatically (no review) and "
                "applies to all of your roster entries. If it's already on file, contact "
                "an officer to change it."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.channel.send(embed=embed, view=SelfUpdatePanelView())
        await interaction.response.send_message("✅ Panel posted.", ephemeral=True)

    # ── /import_roster ───────────────────────────────────────────────────

    @app_commands.command(
        name="import_roster",
        description="[Ruler] Import members from their Discord roles into Notion.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        dry_run="Preview only (default). Set to False to actually write to Notion."
    )
    @_ruler_check()
    async def import_roster(self, interaction: discord.Interaction, dry_run: bool = True):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        try:
            existing = await ns.get_all_roster_discord_ids()
        except Exception as exc:
            await interaction.followup.send(f"❌ Could not read roster: {exc}", ephemeral=True)
            return

        created = skipped_existing = skipped_noroles = skipped_manual = errors = 0
        preview_lines: list[str] = []

        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue

            detachment, rank = derive_detachment_and_rank(member, guild)
            if not detachment:
                skipped_noroles += 1
                continue
            if str(member.id) in existing:
                skipped_existing += 1
                continue

            # Never auto-import officers (Corporal+) or High Command — their ranks
            # are manually appointed and don't track points. Added by hand via
            # /force_enlist, /set_rank, /move_detachment.
            if detachment == "High Command" or rank in config.OFFICER_RANKS:
                skipped_manual += 1
                if len(preview_lines) < 25:
                    preview_lines.append(f"⏭️ {member.display_name} → {detachment} / {rank} (manual — skipped)")
                continue

            # Seed the points/attendances that justify this rank so the sync
            # worker doesn't immediately demote the imported member.
            seed = min_stats_for_rank(detachment, rank)
            # Lorename comes from the Discord nickname with the rank prefix
            # stripped ("Levy, John Baratheon" -> "John Baratheon"). Roblox fields
            # are left blank — they're backfilled later by /migrate_roster.
            lore = lorename_from_nick(member.display_name)
            joined = member.joined_at  # guild join date (date-only in Notion)

            if dry_run:
                created += 1
                if len(preview_lines) < 25:
                    joined_str = joined.date().isoformat() if joined else "unknown"
                    preview_lines.append(
                        f"• {member.display_name} → {detachment} / {rank}, lore: **{lore}**, joined: {joined_str}"
                    )
                continue

            try:
                await ns.create_imported_member(
                    roblox_username="",   # left blank — backfilled by /migrate_roster
                    roblox_id="",         # left blank — backfilled by /migrate_roster
                    lorename=lore,
                    discord_username=member.name,
                    discord_user_id=str(member.id),
                    detachment=detachment,
                    rank=rank,
                    points=seed["points"],
                    combat_trainings=seed["combat_trainings"],
                    joints=seed["joints"],
                    prs=seed["prs"],
                    basic_levy=seed.get("basic_levy", False),
                    date_enlisted=joined,
                )
                created += 1
                await asyncio.sleep(0.34)  # stay under Notion's ~3 req/s limit
            except Exception as exc:
                errors += 1
                log.error("import_roster: failed for %s: %s", member, exc)

        mode = "🔎 DRY RUN — nothing written" if dry_run else "✅ Import complete"
        verb = "Would create" if dry_run else "Created"
        msg = (
            f"**{mode}**\n"
            f"{verb}: **{created}**\n"
            f"Already in roster (skipped): **{skipped_existing}**\n"
            f"Leadership/High Command (skipped — manual): **{skipped_manual}**\n"
            f"No recognized roles (skipped): **{skipped_noroles}**\n"
            f"Errors: **{errors}**"
        )
        if dry_run and preview_lines:
            extra = created - len(preview_lines)
            preview = "\n".join(preview_lines) + (f"\n…and {extra} more" if extra > 0 else "")
            msg += f"\n\n__Preview:__\n{preview}"
        if dry_run:
            msg += "\n\nRun `/import_roster dry_run:False` to write these to Notion."

        await interaction.followup.send(msg[:1990], ephemeral=True)

    # ── /missingnotionrole ───────────────────────────────────────────────

    @app_commands.command(
        name="missingnotionrole",
        description="[Admin] List military members who are not in the Notion roster.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @_admin_check()
    async def missingnotionrole(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        try:
            existing = await ns.get_all_roster_discord_ids()
        except Exception as exc:
            await interaction.followup.send(f"❌ Could not read roster: {exc}", ephemeral=True)
            return

        mil_ids = _military_role_ids()
        missing = []
        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue
            if any(r.id in mil_ids for r in member.roles) and str(member.id) not in existing:
                missing.append(member)

        if not missing:
            await interaction.followup.send("✅ Every military member is in the Notion roster.", ephemeral=True)
            return

        lines = [f"• {m.mention} (`{m.id}`)" for m in missing]
        header = f"**{len(missing)} military member(s) missing from Notion:**\n"

        # Send in <=2000-char chunks
        chunk = header
        first = True
        for line in lines:
            if len(chunk) + len(line) + 1 > 1900:
                await interaction.followup.send(chunk, ephemeral=True)
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            await interaction.followup.send(chunk, ephemeral=True)

    # ── /purge ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name="purge",
        description="[Ruler] Discharge members (any detachment) who didn't react to a message.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        message_id="ID of the message whose reactions count as 'present'",
        channel="Channel the message is in (defaults to this channel)",
    )
    @_ruler_check()
    async def purge(
        self,
        interaction: discord.Interaction,
        message_id: str,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        try:
            mid = int(message_id.strip())
        except ValueError:
            await interaction.followup.send("❌ That isn't a valid message ID.", ephemeral=True)
            return

        target_channel = channel or interaction.channel
        try:
            message = await target_channel.fetch_message(mid)
        except discord.NotFound:
            await interaction.followup.send(
                "❌ Message not found in that channel. Run /purge in the message's "
                "channel, or pass the `channel` option.",
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I can't read that channel's history.", ephemeral=True
            )
            return

        # Everyone who reacted (any emoji) counts as present.
        reactors: set[int] = set()
        for reaction in message.reactions:
            async for user in reaction.users():
                reactors.add(user.id)

        message_time = message.created_at  # only members who joined BEFORE this count

        try:
            pages = await ns.get_all_active_members()
        except Exception as exc:
            log.error("Purge: Notion fetch failed: %s", exc)
            await interaction.followup.send("❌ Couldn't load the roster from Notion.", ephemeral=True)
            return

        # Group active roster rows by Discord ID (a member may hold several).
        groups: dict[str, list] = {}
        for page in pages:
            stats = ns.extract_member_stats(page["properties"])
            uid = stats["discord_user_id"]
            if uid:
                groups.setdefault(uid, []).append((page, stats))

        ELIGIBLE = {"Black Stags", "Thunderhooves", "Stormguard", "Knights of the Storm", "Court"}
        discharge: list[dict] = []
        review: list[str] = []
        flagged: list[dict] = []  # Knight/Guardsman — protected, but listed for manual purge

        for uid, entries in groups.items():
            member = guild.get_member(int(uid))
            if member is None or member.bot:
                continue
            if member.id in reactors:
                continue
            # Must have joined the server BEFORE the message was posted.
            if member.joined_at is None or member.joined_at >= message_time:
                continue

            if len(entries) > 1:
                dets = ", ".join(sorted({s["detachment"] or "—" for _, s in entries}))
                review.append(f"{member} (`{member.id}`) — {len(entries)} entries: {dets}")
                continue

            page, stats = entries[0]
            rank = stats["rank"]
            det = stats["detachment"]
            if rank in config.OFFICER_RANKS:
                # Single entry but holds an officer/court rank — protect, send to review.
                review.append(f"{member} (`{member.id}`) — {det or '—'} / {rank} (officer)")
                continue
            if rank in config.PURGE_FLAG_RANKS:
                # Knights and Guardsmen are never auto-discharged, but ARE
                # listed so command can purge them by hand.
                flagged.append({
                    "member": member, "rank": rank,
                    "roblox_username": stats["roblox_username"],
                })
                continue
            if det in ELIGIBLE:
                discharge.append({
                    "key": str(member.id),
                    "member": member,
                    "page_id": page["id"],
                    "label": f"{member} — {det} / {rank or '—'}",
                    "roblox_username": stats["roblox_username"],
                    "roblox_id": stats["roblox_id"],
                    "lorename": stats["lorename"],
                })
            # Single entry in High Command / other → left alone.

        if not discharge and not review and not flagged:
            await interaction.followup.send(
                "✅ Nobody qualifies — everyone reacted, joined after the message, "
                "or isn't a single-entry detachment member.",
                ephemeral=True,
            )
            return

        if discharge:
            view = PurgeView(interaction.user.id, discharge, message_url=message.jump_url)
            await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)
        else:
            await interaction.followup.send(
                "✅ No single-entry detachment members need auto-discharging.",
                ephemeral=True,
            )

        # DM the runner the full result as clean code blocks:
        # discord username | roblox username | rank.
        dm_lines = [
            f"{c['member']} | {c['roblox_username'] or '(unknown)'} | (auto-discharge list)"
            for c in discharge
        ] + [
            f"{f['member']} | {f['roblox_username'] or '(unknown)'} | {f['rank']} (needs manual purge)"
            for f in flagged
        ]
        if dm_lines:
            await _dm_code_chunks(
                interaction.user,
                f"🗒️ Purge results — {len(discharge)} auto-discharge candidate(s), "
                f"{len(flagged)} Knight/Guardsman flagged:",
                dm_lines,
            )

        # Knights/Guardsmen: protected but explicitly listed for a manual decision.
        if flagged:
            chunk = (
                f"🛡️ **{len(flagged)} Knight/Guardsman non-reactor(s)** — protected from "
                "auto-discharge, purge by hand if warranted:\n"
            )
            for f in flagged:
                line = f"• {f['member']} — {f['rank']}"
                if len(chunk) + len(line) + 1 > 1900:
                    await interaction.followup.send(chunk, ephemeral=True)
                    chunk = ""
                chunk += ("\n" if chunk else "") + line
            if chunk:
                await interaction.followup.send(chunk, ephemeral=True)

        # Multi-entry / leadership non-reactors: manual-review list (NOT discharged).
        if review:
            chunk = (
                f"🔎 **{len(review)} member(s) need manual review** (multiple roster entries "
                "or leadership — NOT auto-discharged). Use `/force_discharge` if appropriate:\n"
            )
            for line in review:
                if len(chunk) + len(line) + 1 > 1900:
                    await interaction.followup.send(chunk, ephemeral=True)
                    chunk = ""
                chunk += ("\n" if chunk else "") + f"• {line}"
            if chunk:
                await interaction.followup.send(chunk, ephemeral=True)

    # ── /force_enlist ────────────────────────────────────────────────────

    @app_commands.command(
        name="force_enlist",
        description="[Officer] Manually enlist a member (military → retinue/Levy, or as an envoy).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        member="The Discord member to enlist",
        fleet="Which retinue to enlist them into (required for military enlistment).",
        as_envoy="Enlist as a diplomatic Envoy instead of military (no roster row).",
        roblox_username="Their Roblox username (required for military enlistment).",
        roblox_id="Their numeric Roblox ID (required for military enlistment).",
        lorename="Their in-universe lore name (optional).",
    )
    @app_commands.choices(fleet=[
        app_commands.Choice(name="Black Stags (EU / Middle East)", value="Black Stags"),
        app_commands.Choice(name="Thunderhooves (NA)",             value="Thunderhooves"),
    ])
    @_officer_check()
    async def force_enlist(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        fleet: app_commands.Choice[str] = None,
        as_envoy: bool = False,
        roblox_username: str = "",
        roblox_id: str = "",
        lorename: str = "",
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # ── Envoy: Discord roles only, no roster row, no Roblox validation. ──
        if as_envoy:
            await util.grant_role(member, config.ROLE_ENVOY, "Force-enlisted as envoy")
            await util.grant_role(member, config.ROLE_VERIFIED, "Force-enlisted as envoy")
            await util.remove_role(member, config.ROLE_UNVERIFIED, "Enlisted — removing join role")
            try:
                await member.send(
                    "🕊️ You've been granted **diplomatic standing** with House Baratheon as an Envoy."
                )
            except discord.HTTPException:
                pass
            await interaction.followup.send(
                f"✅ {member.mention} enlisted as an **Envoy** (diplomatic; no roster entry).",
                ephemeral=True,
            )
            return

        # ── Military: validate Roblox, then create/reactivate the roster row. ──
        if fleet is None:
            await interaction.followup.send(
                "❌ Military enlistment needs a `fleet` (retinue) — or set `as_envoy: True`.",
                ephemeral=True,
            )
            return
        if not roblox_username or not roblox_id:
            await interaction.followup.send(
                "❌ Military enlistment needs both `roblox_username` and `roblox_id` "
                "(or set `as_envoy: True`).", ephemeral=True
            )
            return
        try:
            roblox = await validate_roblox_user(roblox_id, roblox_username)
        except RobloxValidationError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        fleet_name = fleet.value
        discord_user_id = str(member.id)
        discord_username = str(member)

        existing = await ns.get_member_by_discord_id(discord_user_id)
        if existing:
            if ns.extract_member_stats(existing["properties"])["status"] == "Active":
                await interaction.followup.send(
                    f"❌ {member.mention} is already actively enlisted.", ephemeral=True
                )
                return
            await ns.reactivate_member(existing["id"], discord_username, detachment=fleet_name)
        else:
            await ns.create_member(
                roblox_username=roblox["name"],
                roblox_id=str(roblox["id"]),
                lorename=lorename,
                discord_username=discord_username,
                discord_user_id=discord_user_id,
                detachment=fleet_name,
            )

        await role_service.apply_rank_and_company(
            member, fleet_name, "Levy", lorename=lorename or None
        )
        await role_service.add_house_membership_roles(member)
        await util.grant_role(member, config.ROLE_VERIFIED, "Force-enlisted by admin")
        await util.remove_role(member, config.ROLE_UNVERIFIED, "Force-enlisted — removing join role")
        await util.remove_role(member, config.ROLE_VISITOR, "Force-enlisted — no longer a visitor")

        try:
            await member.send(
                f"⚡ You've been **enlisted** into House Baratheon as **{roblox['name']}**, "
                f"joining the **{fleet_name}** at the rank of **Levy**. Ours is the Fury."
            )
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"✅ Enlisted {member.mention} as **{roblox['name']}** "
            f"(Roblox ID `{roblox['id']}`) — {fleet_name} / Levy.",
            ephemeral=True,
        )

    # ── /force_discharge ─────────────────────────────────────────────────

    @app_commands.command(
        name="force_discharge",
        description="[Officer] Manually discharge an enlisted member.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="The enlisted member to discharge")
    @_officer_check()
    async def force_discharge(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        pages = await ns.get_members_by_discord_id(str(member.id))
        active = [p for p in pages if ns.extract_member_stats(p["properties"])["status"] == "Active"]
        is_envoy = any(r.id == config.ROLE_ENVOY for r in member.roles)

        if not active and not is_envoy:
            await interaction.followup.send(
                f"❌ {member.mention} has no active roster entries and isn't an envoy.", ephemeral=True
            )
            return

        # Discharge EVERY active entry (all detachments) for this member.
        lorename = ns.extract_member_stats(active[0]["properties"])["lorename"] if active else ""
        discharged = 0
        for p in active:
            try:
                await ns.discharge_member(p["id"])
                discharged += 1
                await asyncio.sleep(0.34)
            except Exception as exc:
                log.error("force_discharge: failed to archive %s: %s", p.get("id"), exc)

        # Strips military roles + Envoy, grants Visitor (keeps Verified), and
        # drops the rank prefix from their nickname (lore name kept).
        await role_service.apply_discharge_roles(member, lorename=lorename)

        try:
            await member.send(
                f"You have been **discharged** from House Baratheon by {interaction.user.mention}. "
                "Your service record has been archived. Contact command if you believe this "
                "was in error."
            )
        except discord.HTTPException:
            pass

        if active:
            detail = (f"archived **{discharged}** roster entr"
                      f"{'y' if discharged == 1 else 'ies'} across all detachments")
        else:
            detail = "removed their **Envoy** standing (no roster entry)"
        await interaction.followup.send(
            f"✅ Discharged {member.mention} — {detail}.", ephemeral=True
        )

    # ── /add_roster_entry ────────────────────────────────────────────────

    @app_commands.command(
        name="add_roster_entry",
        description="[Officer] Add a Notion roster entry only (no Discord roles; allows multiple per member).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        member="The Discord member",
        detachment="Detachment for this entry",
        rank="Rank for this entry",
        lorename="Lore name (optional)",
        roblox_username="Roblox username (optional)",
        roblox_id="Roblox ID (optional)",
    )
    @app_commands.choices(detachment=[
        app_commands.Choice(name="Black Stags",          value="Black Stags"),
        app_commands.Choice(name="Thunderhooves",        value="Thunderhooves"),
        app_commands.Choice(name="Stormguard",           value="Stormguard"),
        app_commands.Choice(name="Knights of the Storm", value="Knights of the Storm"),
        app_commands.Choice(name="Court",                value="Court"),
        app_commands.Choice(name="High Command",         value="High Command"),
    ])
    @app_commands.autocomplete(rank=notion_rank_autocomplete)
    @_officer_check()
    async def add_roster_entry(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        detachment: app_commands.Choice[str],
        rank: str,
        lorename: str = "",
        roblox_username: str = "",
        roblox_id: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        valid_ranks = await ns.get_select_options("Rank")
        if valid_ranks and rank not in valid_ranks:
            await interaction.followup.send(
                f"❌ `{rank}` isn't a Rank option in the Notion roster. "
                "Pick one from the autocomplete list.",
                ephemeral=True,
            )
            return

        # Identity (Roblox username/ID + lore name) is REPLICATED from the member's
        # existing roster entry so a second posting stays consistent. If they have
        # no entry yet (shouldn't normally happen), those details must be supplied
        # manually on the command.
        existing = await ns.get_members_by_discord_id(str(member.id))
        if existing:
            src = ns.extract_member_stats(existing[0]["properties"])
            roblox_username = src["roblox_username"]
            roblox_id       = src["roblox_id"]
            lorename        = src["lorename"]
        elif not (roblox_username and roblox_id and lorename):
            await interaction.followup.send(
                f"❌ {member.mention} has no existing roster entry to copy from, so you must "
                "provide `roblox_username`, `roblox_id` and `lorename` manually.",
                ephemeral=True,
            )
            return

        # Notion-only: always create a NEW row (command members can hold several).
        # Date Enlisted = the day they joined the guild (date-only), like /import_roster.
        await ns.create_imported_member(
            roblox_username=roblox_username,
            roblox_id=roblox_id,
            lorename=lorename,
            discord_username=str(member),
            discord_user_id=str(member.id),
            detachment=detachment.value,
            rank=rank,
            date_enlisted=member.joined_at,
        )

        await interaction.followup.send(
            f"✅ Added a roster entry for {member.mention}: **{detachment.value} / {rank}**. "
            "No Discord roles were changed.",
            ephemeral=True,
        )

    # ── /remove_roster_entry ─────────────────────────────────────────────

    @app_commands.command(
        name="remove_roster_entry",
        description="[Officer] Remove (archive) a member's roster entry for a detachment. Notion only.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        member="The Discord member",
        detachment="Which detachment entry to remove (omit to remove ALL their entries)",
    )
    @app_commands.choices(detachment=[
        app_commands.Choice(name="Black Stags",          value="Black Stags"),
        app_commands.Choice(name="Thunderhooves",        value="Thunderhooves"),
        app_commands.Choice(name="Stormguard",           value="Stormguard"),
        app_commands.Choice(name="Knights of the Storm", value="Knights of the Storm"),
        app_commands.Choice(name="Court",                value="Court"),
        app_commands.Choice(name="High Command",         value="High Command"),
    ])
    @_officer_check()
    async def remove_roster_entry(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        detachment: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        pages = await ns.get_members_by_discord_id(str(member.id))
        if not pages:
            await interaction.followup.send(
                f"❌ {member.mention} has no roster entries.", ephemeral=True
            )
            return

        if detachment is not None:
            targets = [
                p for p in pages
                if ns.extract_member_stats(p["properties"])["detachment"] == detachment.value
            ]
            if not targets:
                await interaction.followup.send(
                    f"❌ {member.mention} has no entry in **{detachment.value}**.", ephemeral=True
                )
                return
            where = f"in **{detachment.value}**"
        else:
            targets = pages
            where = "across **all** detachments"

        removed = 0
        for p in targets:
            try:
                await ns.archive_page(p["id"])
                removed += 1
                await asyncio.sleep(0.34)
            except Exception as exc:
                log.error("remove_roster_entry: failed to archive %s: %s", p.get("id"), exc)

        await interaction.followup.send(
            f"✅ Removed **{removed}** roster entr{'y' if removed == 1 else 'ies'} for "
            f"{member.mention} {where}. No Discord roles were changed.",
            ephemeral=True,
        )

    # ── /clear_roster ────────────────────────────────────────────────────

    @app_commands.command(
        name="clear_roster",
        description="[Ruler] DANGER: archive EVERY row in the Notion roster (for a clean re-import).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @_ruler_check()
    async def clear_roster(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            pages = await ns.get_all_roster_pages()
        except Exception as exc:
            log.error("clear_roster: fetch failed: %s", exc)
            await interaction.followup.send(f"❌ Couldn't read the roster: {exc}", ephemeral=True)
            return

        if not pages:
            await interaction.followup.send("The roster is already empty.", ephemeral=True)
            return

        page_ids = [p["id"] for p in pages]
        embed = discord.Embed(
            title="🗑️ Clear the ENTIRE roster?",
            description=(
                f"This archives **all {len(page_ids)} row(s)** in the Notion roster "
                "(every status). Archived rows go to Notion's trash and can be restored "
                "there for a while, but this command can't undo it.\n\n"
                "Afterwards, rebuild with `/import_roster dry_run:False`."
            ),
            color=discord.Color.dark_red(),
        )
        await interaction.followup.send(
            embed=embed,
            view=ClearRosterConfirmView(interaction.user.id, page_ids),
            ephemeral=True,
        )

    # ── /migrate_roster ──────────────────────────────────────────────────

    @app_commands.command(
        name="migrate_roster",
        description="[Ruler] Match roster lorenames to the tracking DB and backfill Roblox IDs/usernames.",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(dry_run="Preview only (default). Set to False to write to Notion.")
    @_ruler_check()
    async def migrate_roster(self, interaction: discord.Interaction, dry_run: bool = True):
        await interaction.response.defer(ephemeral=True)

        # 1) Build the tracking map: normalised lorename -> (roblox_id, roblox_username)
        try:
            tracking = await ns.get_all_tracking_members()
        except Exception as exc:
            log.error("migrate_roster: tracking fetch failed: %s", exc)
            await interaction.followup.send(
                f"❌ Couldn't read the Military Tracking DB: {exc}", ephemeral=True
            )
            return

        tmap: dict[str, tuple[str, str]] = {}
        ambiguous_keys: set[str] = set()
        for row in tracking:
            p = row["properties"]
            key = _norm_name(ns.get_prop_text(p, "Lorename"))
            if not key:
                continue
            value = (ns.get_prop_text(p, "Roblox ID"), ns.get_prop_text(p, "Username"))
            if key in tmap and tmap[key] != value:
                ambiguous_keys.add(key)
            tmap.setdefault(key, value)

        # 2) Walk the active roster, matching on each row's existing Lorename
        try:
            roster = await ns.get_all_active_members()
        except Exception as exc:
            log.error("migrate_roster: roster fetch failed: %s", exc)
            await interaction.followup.send(
                f"❌ Couldn't read the roster: {exc}", ephemeral=True
            )
            return

        matched = unmatched = ambiguous = no_lorename = errors = 0
        preview: list[str] = []

        for page in roster:
            lore = ns.get_prop_text(page["properties"], "Lorename")
            if not lore:
                no_lorename += 1
                if len(preview) < 25:
                    preview.append("⏭️ row with no lorename — skipped")
                continue

            key = _norm_name(lore)
            is_ambig = key in ambiguous_keys
            match = None if is_ambig else tmap.get(key)
            rid, ruser = match if match else (None, None)
            set_roblox = bool(match) and bool(rid or ruser)

            if set_roblox:
                matched += 1
            else:
                unmatched += 1
                if is_ambig:
                    ambiguous += 1

            if len(preview) < 25:
                if set_roblox:
                    preview.append(f"✅ **{lore}** → Roblox **{ruser}** (`{rid}`)")
                else:
                    tag = "ambiguous (dup lorename in tracking)" if is_ambig else "no tracking match"
                    preview.append(f"⚠️ **{lore}** → {tag}")

            if not dry_run and set_roblox:
                try:
                    await ns.update_roster_identity(
                        page["id"], roblox_id=rid, roblox_username=ruser
                    )
                    await asyncio.sleep(0.34)  # stay under Notion's ~3 req/s
                except Exception as exc:
                    errors += 1
                    log.error("migrate_roster: update failed for %s: %s", page.get("id"), exc)

        mode = "🔎 DRY RUN — nothing written" if dry_run else "✅ Migration complete"
        msg = (
            f"**{mode}**\n"
            f"Tracking rows read: **{len(tracking)}**"
            + (f" (⚠️ {len(ambiguous_keys)} duplicate lorename(s))" if ambiguous_keys else "")
            + "\n"
            f"Roblox backfilled: **{matched}**\n"
            f"No tracking match: **{unmatched}**"
            + (f" (incl. {ambiguous} ambiguous)" if ambiguous else "")
            + "\n"
            f"Roster rows with no lorename (skipped): **{no_lorename}**\n"
            f"Errors: **{errors}**"
        )
        if preview:
            msg += "\n\n__Preview (first 25):__\n" + "\n".join(preview)
        if dry_run:
            msg += "\n\nRun `/migrate_roster dry_run:False` to write these to Notion."

        await interaction.followup.send(msg[:1990], ephemeral=True)

    # ── /undo_role_changes ───────────────────────────────────────────────

    @app_commands.command(
        name="undo_role_changes",
        description="[Ruler] Reverse the bot's own recent role changes (incident recovery).",
    )
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        hours="How many hours back to reverse (default 6).",
        dry_run="Preview only (default). Set to False to apply.",
    )
    @_ruler_check()
    async def undo_role_changes(
        self,
        interaction: discord.Interaction,
        hours: int = 6,
        dry_run: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        bot_id = self.bot.user.id
        after = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))

        # Aggregate, per member, what the BOT removed vs added in the window.
        removed_by_bot: dict[int, set[int]] = {}
        added_by_bot: dict[int, set[int]] = {}
        try:
            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.member_role_update, after=after, limit=None
            ):
                if entry.user is None or entry.user.id != bot_id or entry.target is None:
                    continue
                before_roles = {r.id for r in (getattr(entry.before, "roles", None) or [])}
                after_roles  = {r.id for r in (getattr(entry.after, "roles", None) or [])}
                removed = before_roles - after_roles
                added   = after_roles - before_roles
                if removed:
                    removed_by_bot.setdefault(entry.target.id, set()).update(removed)
                if added:
                    added_by_bot.setdefault(entry.target.id, set()).update(added)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I lack the **View Audit Log** permission, so I can't read what to undo.",
                ephemeral=True,
            )
            return

        affected = set(removed_by_bot) | set(added_by_bot)
        if not affected:
            await interaction.followup.send(
                f"No role changes by me found in the last **{hours}h**.", ephemeral=True
            )
            return

        bot_top = guild.me.top_role
        members_done = restored = stripped = skipped_hierarchy = errors = 0
        preview: list[str] = []

        for mid in affected:
            member = guild.get_member(mid)
            if member is None:
                continue

            re_add_ids = removed_by_bot.get(mid, set()) - added_by_bot.get(mid, set())
            remove_ids = added_by_bot.get(mid, set()) - removed_by_bot.get(mid, set())

            to_add, to_remove = [], []
            for rid in re_add_ids:
                role = guild.get_role(rid)
                if not role or role in member.roles:
                    continue
                if role < bot_top and not role.managed:
                    to_add.append(role)
                else:
                    skipped_hierarchy += 1
            for rid in remove_ids:
                role = guild.get_role(rid)
                if not role or role not in member.roles:
                    continue
                if role < bot_top and not role.managed:
                    to_remove.append(role)
                else:
                    skipped_hierarchy += 1

            if not to_add and not to_remove:
                continue

            if len(preview) < 25:
                parts = []
                if to_add:
                    parts.append("re-add " + ", ".join(r.name for r in to_add))
                if to_remove:
                    parts.append("remove " + ", ".join(r.name for r in to_remove))
                preview.append(f"• {member} — " + "; ".join(parts))

            if not dry_run:
                try:
                    if to_add:
                        await member.add_roles(*to_add, reason=f"Undo bot role changes ({hours}h)")
                    if to_remove:
                        await member.remove_roles(*to_remove, reason=f"Undo bot role changes ({hours}h)")
                    await asyncio.sleep(0.4)
                except discord.HTTPException as exc:
                    errors += 1
                    log.error("undo_role_changes: failed for %s: %s", member, exc)
                    continue

            members_done += 1
            restored += len(to_add)
            stripped += len(to_remove)

        mode = "🔎 DRY RUN — nothing changed" if dry_run else "✅ Undo applied"
        msg = (
            f"**{mode}** — reversing my role changes from the last **{hours}h**\n"
            f"Members affected: **{members_done}**\n"
            f"Roles to re-add: **{restored}**\n"
            f"Roles to remove (e.g. Levy): **{stripped}**\n"
            f"Skipped (above my role / managed): **{skipped_hierarchy}**\n"
            f"Errors: **{errors}**"
        )
        if preview:
            msg += "\n\n__Preview (first 25):__\n" + "\n".join(preview)
        if dry_run:
            msg += "\n\nRun `/undo_role_changes hours:<n> dry_run:False` to apply."
        await interaction.followup.send(msg[:1990], ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
