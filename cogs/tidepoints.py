"""
Tidepoints cog — /give_tidepoints and /remove_tidepoints.
Gated to the Highborn role.
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import notion_service as ns
import role_service
import util
from rank_engine import compute_rank, never_demote


def _highborn_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not util.is_highborn(interaction.user):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)


class TidepointsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="give_tidepoints", description="[Admin] Grant tidepoints to a member.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        member="The Discord member",
        amount="Amount of tidepoints to grant",
        reason="Reason for the grant",
    )
    @_highborn_check()
    async def give_tidepoints(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int,
        reason: str,
    ):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        roster_page = await ns.get_fleet_member_by_discord_id(str(member.id))
        if not roster_page:
            await interaction.followup.send("❌ Member not found in roster.", ephemeral=True)
            return

        props   = roster_page["properties"]
        stats   = ns.extract_member_stats(props)
        company = stats["detachment"]

        new_points = stats["points"] + amount
        computed = compute_rank(
            company, new_points,
            combat_trainings=stats["combat_trainings"],
            joints=stats["joints"],
            prs=stats["prs"],
            basic_levy=stats["basic_levy"],
            tenure_days=ns.tenure_days(stats),
        )
        # Grandfather rule: the engine only ever promotes — a held rank is
        # only removed manually.
        new_rank = never_demote(company, stats["rank"], computed)

        await ns.apply_tidepoints_grant(roster_page["id"], props, amount, new_rank)

        if new_rank != stats["rank"]:
            guild_member = interaction.guild.get_member(member.id)
            if guild_member:
                await role_service.apply_rank_and_company(
                    guild_member, company, new_rank, old_rank=stats["rank"], lorename=stats["lorename"]
                )

        pts_label = config.POINTS_EMOJI or "pts"
        await interaction.followup.send(
            f"✅ Granted **{amount} tidepoints** to {member.mention}. Reason: *{reason}*"
            + (f" → promoted to **{new_rank}**! 🎉" if new_rank != stats["rank"] else ""),
            ephemeral=True,
        )

    @app_commands.command(name="remove_tidepoints", description="[Admin] Remove tidepoints from a member.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        member="The Discord member",
        amount="Amount of tidepoints to remove",
        reason="Reason for the removal",
    )
    @_highborn_check()
    async def remove_tidepoints(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: int,
        reason: str,
    ):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        roster_page = await ns.get_fleet_member_by_discord_id(str(member.id))
        if not roster_page:
            await interaction.followup.send("❌ Member not found in roster.", ephemeral=True)
            return

        props = roster_page["properties"]
        await ns.apply_tidepoints_remove(roster_page["id"], props, amount)

        await interaction.followup.send(
            f"✅ Removed **{amount} tidepoints** from {member.mention}. Reason: *{reason}*. "
            "(Points and rank are unchanged.)",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TidepointsCog(bot))
