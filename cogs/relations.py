"""
Relations cog — display and edit House Baratheon's diplomatic relations.

/relations          — post the relations embed (Bot Admin).
/relations_set      — set a house's status / add a house (Bot Admin).
"""

import discord
from discord import app_commands
from discord.ext import commands

import config
import notion_service as ns
import util


def _is_admin(interaction: discord.Interaction) -> bool:
    return util.is_admin(interaction.user)


def _build_description(relations: list[dict]) -> str:
    legend = (
        "**__HOUSE BARATHEON RELATIONS__**\n"
        f"{config.RELATION_EMOJI['Allied']}  = **__ALLIED__**\n"
        f"{config.RELATION_EMOJI['Neutral']}  = **__NEUTRAL__**\n"
        f"{config.RELATION_EMOJI['Enemy']}  = **__ENEMY__**\n"
        "======================================\n"
    )

    # Group by region
    by_region: dict[str, list[dict]] = {}
    for r in relations:
        by_region.setdefault(r["region"], []).append(r)

    parts = [legend]
    regions = config.RELATION_REGION_ORDER + [
        reg for reg in by_region if reg not in config.RELATION_REGION_ORDER
    ]
    for region in regions:
        houses = by_region.get(region)
        if not houses:
            continue
        houses.sort(key=lambda h: (h["order"] is None, h["order"] or 0, h["house"]))
        parts.append(f"\n*__{region.upper()}__*\n")
        for h in houses:
            emoji = config.RELATION_EMOJI.get(h["status"], "⬜")
            parts.append(f"**HOUSE {h['house'].upper()}** {emoji} ")
    return "\n".join(parts)


class RelationsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="relations", description="[Admin] Display House Baratheon's diplomatic relations.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    async def relations(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        await interaction.response.defer()
        relations = await ns.get_all_relations()
        embed = discord.Embed(
            description=_build_description(relations),
            color=discord.Color.dark_blue(),
        )
        if config.RELATIONS_LOGO_URL:
            embed.set_thumbnail(url=config.RELATIONS_LOGO_URL)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="relations_set", description="[Admin] Set a house's relation status.")
    @app_commands.guilds(discord.Object(id=config.GUILD_ID))
    @app_commands.describe(
        house="House name (without 'House' prefix), e.g. Lannister",
        status="Relation status",
        region="Required only when adding a NEW house",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Allied",  value="Allied"),
            app_commands.Choice(name="Neutral", value="Neutral"),
            app_commands.Choice(name="Enemy",   value="Enemy"),
        ],
        region=[
            app_commands.Choice(name="Crownlands",  value="Crownlands"),
            app_commands.Choice(name="Westerlands", value="Westerlands"),
            app_commands.Choice(name="Riverlands",  value="Riverlands"),
            app_commands.Choice(name="The North",   value="The North"),
            app_commands.Choice(name="Iron Isles",  value="Iron Isles"),
            app_commands.Choice(name="The Reach",   value="The Reach"),
            app_commands.Choice(name="Dorne",       value="Dorne"),
            app_commands.Choice(name="Stormlands",  value="Stormlands"),
            app_commands.Choice(name="The Vale",    value="The Vale"),
        ],
    )
    async def relations_set(
        self,
        interaction: discord.Interaction,
        house: str,
        status: app_commands.Choice[str],
        region: app_commands.Choice[str] = None,
    ):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        house = house.strip().title()
        region_val = region.value if region else None
        try:
            result = await ns.set_relation(house, status.value, region_val)
        except ValueError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

        verb = "added" if result == "created" else "updated"
        await interaction.followup.send(
            f"✅ House **{house}** {verb} → **{status.value}**.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RelationsCog(bot))
