"""
Help cog — /help shows a permission-aware command reference.

Everyone sees the member panels. Admins additionally see the panel-setup
commands; the rulers (Heir/Lady/Lord of Storm's End) see the server-wide role
tools.
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import util


# (command, description) grouped by required permission tier
MEMBER_COMMANDS = [
    ("Enlistment panel", "Press **Begin Enlistment**, pick your region, and fill in the form (Lore Name, Roblox details, past experience, House Words). Approved recruits join as a Levy."),
    ("Envoy panel", "Representing another house/allegiance? Press **Envoy Application** and name a real GoT house or allegiance (reviewed)."),
    ("Court panel", "Press **Court Application** to confirm your identity and sit the written test (reviewed; approved applicants join the Court as a Clerk)."),
    ("Region panel", "Press **Set My Region** to tag yourself EU or NA."),
    ("Discharge panel", "Press **Request Discharge** to step down from service (reviewed; approval strips your military roles and grants Visitor)."),
    ("Assessments panel", "Knights: request a Corporal or Lieutenant Assessment — a private ticket channel opens with your hosts. (Knight Trial and Stormguard tryouts are invitation-only.)"),
    ("/help", "Show this command list."),
]

# Full-admin tier — panel setup + reporting.
ADMIN_COMMANDS = [
    ("/setup_enlist_panel", "Post the military enlistment panel in its channel."),
    ("/setup_envoy_panel", "Post the Envoy (diplomatic entry) panel in the current channel."),
    ("/setup_court_panel", "Post the Court of Storm's End application panel in the current channel."),
    ("/setup_region_panel", "Post the persistent 'Set My Region' panel in the current channel."),
    ("/setup_trials_panel", "Post the assessment-request panels (Corporal + Lieutenant)."),
    ("/setup_discharge_panel", "Post the persistent Discharge Request panel in its channel."),
    ("/weekly_report", "Post the weekly digest now — enlistments and promotions over the last 7 days."),
    ("Accept / Decline buttons", "Approve or deny enlistment, envoy, court, and discharge requests."),
]

# Ruler tier — Heir / Lady / Lord of Storm's End.
RULER_COMMANDS = [
    ("/cleanup_roles [dry_run]", "Enforce separators, station & Court rules across the whole server; reports retinue conflicts. Preview first."),
]


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show the commands you can use.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def help_command(self, interaction: discord.Interaction):
        user = interaction.user
        is_ruler = util.is_ruler(user)
        is_admin = util.is_admin(user)

        embed = discord.Embed(
            title="⚡ House Baratheon — Command Guide",
            description="Here are the commands available to you.",
            color=discord.Color.dark_gold(),
        )

        def add_section(title: str, items):
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

        if is_admin:
            add_section("🛡️ Admin Commands", ADMIN_COMMANDS)

        if is_ruler:
            add_section("👑 Ruler Commands", RULER_COMMANDS)

        if not is_admin:
            embed.set_footer(text="Some commands are restricted to House leadership.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
