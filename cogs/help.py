"""
Help cog — /help shows a permission-aware command reference.

Everyone sees member commands. Each higher tier additionally sees its own
section: Officers (Military Command) see the roster/military commands, the Court
sees logging, full admins see the admin commands, and the rulers (Heir/Lady/Lord
of Storm's End) additionally see the destructive commands.
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import util


# (command, description) grouped by required permission tier
MEMBER_COMMANDS = [
    ("Enlistment panel", "Use **Begin Enlistment** (pick your region), **Court Application**, or **Envoy Application** to apply (reviewed). Recruits are placed into a retinue after their Basic Levy Training."),
    ("Region panel", "Press **Set My Region** to tag yourself EU or NA (your retinue is assigned after your Basic Levy Training)."),
    ("Discharge panel", "Press **Request Discharge** on the discharge panel to submit a discharge request (reviewed)."),
    ("LOA panel", "Press **Request LOA** on the leave-of-absence panel to request time off — your rank/post are kept while on leave (reviewed)."),
    ("/roster [member]", "View a roster record. Defaults to yourself."),
    ("/myprogress", "See how close you are to your next rank (points/trainings/tenure needed)."),
    ("/help", "Show this command list."),
    ("Assessments panel", "Knights: request a Corporal or Lieutenant Assessment — a private ticket channel opens with your hosts. (Knight Trial and Stormguard tryouts are invitation-only.)"),
]

# Officer tier — Military Command access roles (and above).
OFFICER_COMMANDS = [
    ("/event [detachment] [title]", "Announce an event — DMs everyone in that retinue, or House-wide in one go."),
    ("/set_rank [member] [rank]", "Manually set a member's rank (manual ladders + leadership appointments)."),
    ("/move_detachment [member] [company] [rank]", "Move a member to a different detachment, optionally setting their rank in the same command."),
    ("/force_enlist [member] [fleet] [as_envoy] …", "Manually enlist a member — military (retinue/Levy) or, with as_envoy, as a diplomatic Envoy."),
    ("/force_discharge [member]", "Manually discharge an enlisted member or envoy (archives all Notion rows, strips roles, grants Visitor)."),
    ("/add_roster_entry [member] [detachment] [rank] …", "Add a Notion roster entry only (no Discord roles). Copies Roblox/lore from the member's existing entry."),
    ("/remove_roster_entry [member] [detachment]", "Remove (archive) a member's roster entry for a detachment, or all entries if no detachment given. Notion only."),
    ("/sync", "Reconcile manual Discord role changes into Notion (transfers detachments, updates ranks, logs abandoned posts)."),
    ("/end_loa [member]", "End a member's approved LOA — restore their roster rows to Active and remove the LOA role."),
    ("/strike [member] [reason]", "Issue a disciplinary strike (3 active → demote a rank, 5 → removal; strikes expire after 7 days)."),
    ("/strikes [member]", "View a member's active strikes."),
    ("/clear_strike [member]", "Clear a member's active strikes."),
    ("/create_schedule", "Open the weekly training schedule builder (also edits the current week). Post button publishes it; edits then apply live."),
    ("/edit_schedule", "Edit the current week's training schedule."),
    ("/post_schedule", "Post or refresh the public weekly schedule embed (normally automatic)."),
]

# Logging tier — the Court.
LOGGER_COMMANDS = [
    ("/log_event [event_type] [attendees] [host] [co_host] [supervisor]", "Log an event after it happens — paste the attendees and everyone gets points/attendance (and promotions) in Notion."),
    ("/end_loa [member]", "End a member's approved LOA — restore their roster rows to Active and remove the LOA role."),
    ("/create_schedule", "Open the weekly training schedule builder (also edits the current week). Post button publishes it; edits then apply live."),
    ("/edit_schedule", "Edit the current week's training schedule."),
    ("/post_schedule", "Post or refresh the public weekly schedule embed (normally automatic)."),
]

# Full-admin tier — every non-destructive command.
ADMIN_COMMANDS = [
    ("/give_tidepoints [member] [amount] [reason]", "Grant tidepoints (adds to Event Points AND Tidepoints, recomputes rank)."),
    ("/remove_tidepoints [member] [amount] [reason]", "Remove tidepoints only (e.g. prize redemption). Does not change rank."),
    ("/create_council_title [name]", "Add a new ceremonial council title to the list."),
    ("/assign_council_title [member] [title]", "Give a council member a title (e.g. Lord Admiral)."),
    ("/relations", "Display House Baratheon's diplomatic relations."),
    ("/relations_set [house] [status]", "Set or add a house's diplomatic status."),
    ("/setup_trials_panel", "Post the assessment-request panels (Corporal + Lieutenant; requests open private ticket channels)."),
    ("/setup_region_panel", "Post the persistent 'Set My Region' retinue-sorting panel in the current channel."),
    ("/self_update", "Post the 'Update Roblox Info' self-service panel (members fill in their own Roblox ID/username; auto-saved, no review)."),
    ("/setup_enlist_panel", "Post the enlistment / diplomatic entry panel in its channel."),
    ("/setup_discharge_panel", "Post the persistent Discharge Request panel in its channel."),
    ("/setup_loa_panel", "Post the persistent LOA (Leave of Absence) request panel in its channel."),
    ("/missingnotionrole", "List military members who are not in the Notion roster."),
    ("Accept / Decline buttons", "Approve or deny enlistment, discharge, and LOA requests."),
]

# Ruler tier — Heir / Lady / Lord of Storm's End only. Destructive/irreversible.
RULER_COMMANDS = [
    ("/purge [message_id] [channel]", "Discharge single-entry members who joined before, and didn't react to, a message. Knights/Guardsmen are flagged, not auto-discharged; the full list is DMed to you."),
    ("/clear_roster", "DANGER: archive every row in the Notion roster (for a clean re-import). Asks for confirmation."),
    ("/import_roster [dry_run]", "Bulk-import members from their Discord roles into Notion, seeding rank-appropriate points (preview first)."),
    ("/migrate_roster [dry_run]", "Match roster lorenames to the tracking DB and backfill Roblox IDs/usernames (preview first)."),
    ("/cleanup_roles [dry_run]", "Enforce separators, station & Court rules across the whole server; reports retinue conflicts. Preview first."),
    ("/migrate_roster_v2", "One-off: copy every member from the legacy roster into the new Roster V2, unsorted (no detachment)."),
    ("/apply_roster_roles [member] [dry_run]", "Sync Discord roles from the roster — strip legacy roles and apply each member's rank/detachment. Preview first."),
    ("/toggle_sync", "Turn the periodic Discord→Notion sync on/off at runtime."),
    ("/undo_role_changes [hours] [dry_run]", "Reverse the bot's own role changes over the last N hours (incident recovery; preview first)."),
]


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show the commands you can use.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def help_command(self, interaction: discord.Interaction):
        user = interaction.user
        is_ruler   = util.is_ruler(user)
        is_admin   = util.is_admin(user)          # full-admin tier (includes rulers)
        is_officer = util.is_officer(user)        # Military Command + admin
        is_logger  = util.is_event_logger(user)   # Court + admin

        embed = discord.Embed(
            title="⚡ House Baratheon — Command Guide",
            description="Here are the commands available to you.",
            color=discord.Color.dark_gold(),
        )

        def add_section(title: str, items):
            # Discord caps each field value at 1024 chars, so split long
            # sections across multiple fields (continuation gets a "(cont.)").
            lines = [f"**{cmd}** — {desc}" for cmd, desc in items]
            chunks: list[str] = []
            current = ""
            for line in lines:
                if current and len(current) + 1 + len(line) > 1024:
                    chunks.append(current)
                    current = line
                else:
                    current = f"{current}\n{line}" if current else line
            if current:
                chunks.append(current)

            for i, chunk in enumerate(chunks):
                embed.add_field(
                    name=title if i == 0 else f"{title} (cont.)",
                    value=chunk,
                    inline=False,
                )

        add_section("📜 Member Commands", MEMBER_COMMANDS)

        if is_officer:
            add_section("⚔️ Officer Commands", OFFICER_COMMANDS)

        if is_logger:
            add_section("📋 Court — Logging", LOGGER_COMMANDS)

        if is_admin:
            add_section("🛡️ Admin Commands", ADMIN_COMMANDS)

        if is_ruler:
            add_section("👑 Ruler Commands (destructive)", RULER_COMMANDS)

        if not is_officer and not is_logger and not is_admin:
            embed.set_footer(text="Some commands are restricted to Command, the Court, and House leadership.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
