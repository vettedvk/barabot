"""
Titles cog — manage the ceremonial council titles layered onto command members
(Lord Admiral, Marshal, Lord Commander, etc.).

Titles are stored in the roster's "Title" Notion select and are independent of
rank. /create_council_title adds a new title to the list; /assign_council_title
gives a member a title (written to their High Command roster row if they have
one, else their first roster row).
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import notion_service as ns
import util


async def title_autocomplete(interaction: discord.Interaction, current: str):
    """Suggest existing Title options as the admin types."""
    try:
        options = await ns.get_select_options("Title")
    except Exception:
        options = []
    cur = current.lower()
    return [app_commands.Choice(name=t, value=t) for t in options if cur in t.lower()][:25]


class TitlesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="create_council_title", description="[Admin] Add a new council title to the list.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(name="The new title to add (e.g. Hand of the House)")
    async def create_council_title(self, interaction: discord.Interaction, name: str):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        name = name.strip()
        if not name:
            await interaction.followup.send("❌ Title can't be empty.", ephemeral=True)
            return
        try:
            created = await ns.add_title_option(name)
        except Exception as exc:
            await interaction.followup.send(f"❌ Couldn't add the title: {exc}", ephemeral=True)
            return

        if created:
            await interaction.followup.send(f"✅ Added council title **{name}**.", ephemeral=True)
        else:
            await interaction.followup.send(f"ℹ️ **{name}** already exists.", ephemeral=True)

    @app_commands.command(name="assign_council_title", description="[Admin] Assign a council title to a member.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(member="The council member", title="The title to assign")
    @app_commands.autocomplete(title=title_autocomplete)
    async def assign_council_title(self, interaction: discord.Interaction, member: discord.Member, title: str):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        valid = await ns.get_select_options("Title")
        if valid and title not in valid:
            await interaction.followup.send(
                f"❌ `{title}` isn't a council title. Add it first with /create_council_title.",
                ephemeral=True,
            )
            return

        pages = await ns.get_members_by_discord_id(str(member.id))
        if not pages:
            await interaction.followup.send(
                f"❌ {member.mention} has no roster entry to attach a title to.", ephemeral=True
            )
            return

        # Prefer their High Command (council) row; otherwise use the first row.
        target = next(
            (p for p in pages if ns.extract_member_stats(p["properties"])["detachment"] == "High Command"),
            pages[0],
        )
        await ns.set_member_title(target["id"], title)
        await interaction.followup.send(
            f"✅ {member.mention} titled **{title}**.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TitlesCog(bot))
