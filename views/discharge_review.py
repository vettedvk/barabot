"""
Discharge review — the Approve / Deny buttons attached to a discharge request in
the review channel. Only Bot Admins may act.

Pure Discord: the member's Discord ID is read from the "Member" field and the
roles are read live. On approval the bot strips all military roles and grants
Visitor (Verified is kept). No external store.

PERSISTENT and stateless — survives a bot restart. Registered once at startup
via bot.add_view(DischargeReviewView()).
"""

import discord

import audit_log
import config
import role_service
import util


def _lorename_from_nick(nick: str | None) -> str:
    """Lore name from a '{rank}, {forename surname}' nickname (drop the rank
    prefix); if there's no comma, the whole nickname is the lore name."""
    nick = (nick or "").strip()
    return nick.split(",", 1)[1].strip() if "," in nick else nick


def summarize_service(member: discord.Member) -> str:
    """One-line summary of the member's current retinue + rank roles, read from
    Discord — used in the request/review embed so reviewers have context."""
    ids = {r.id for r in member.roles}
    retinues = [name for name, rid in config.COMPANY_ROLE_IDS.items() if rid in ids]
    ranks = [name for name, rid in config.RANK_ROLE_IDS.items() if rid in ids]
    parts = []
    if retinues:
        parts.append("Retinue(s): " + ", ".join(retinues))
    if ranks:
        parts.append("Rank(s): " + ", ".join(ranks))
    return "\n".join(parts) or "—"


class DischargeReviewView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="Approve Discharge", style=discord.ButtonStyle.success, emoji="✅",
                       custom_id="vel_discharge_accept")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        await interaction.response.defer()

        member_id = util.id_in_field(interaction.message.embeds[0], "Member")
        if member_id is None:
            await interaction.followup.send("❌ Couldn't read member from this message.", ephemeral=True)
            return

        guild_member = interaction.guild.get_member(member_id)
        if guild_member:
            lorename = _lorename_from_nick(guild_member.nick)
            await role_service.apply_discharge_roles(guild_member, lorename=lorename)
            try:
                await guild_member.send(
                    "✅ Your discharge request has been **approved**. "
                    "Go well — the storm remembers."
                )
            except discord.HTTPException:
                pass

        await util.finalize_review(interaction, self, color=discord.Color.green(), label="✅ Approved by")
        await audit_log.log_event(
            interaction.client,
            title="✅ Discharge approved",
            color=discord.Color.green(),
            fields=[
                ("Reviewer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Member", f"<@{member_id}> (`{member_id}`)", True),
            ],
        )

    @discord.ui.button(label="Deny Discharge", style=discord.ButtonStyle.danger, emoji="❌",
                       custom_id="vel_discharge_decline")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not util.is_admin(interaction.user):
            await interaction.response.send_message("❌ Bot Admins only.", ephemeral=True)
            return
        await interaction.response.defer()

        member_id = util.id_in_field(interaction.message.embeds[0], "Member")
        if member_id:
            requester = interaction.guild.get_member(member_id)
            if requester:
                try:
                    await requester.send(
                        "❌ Your discharge request was **denied** by "
                        f"{interaction.user.mention}. Contact an admin if you have questions."
                    )
                except discord.HTTPException:
                    pass

        await util.finalize_review(interaction, self, color=discord.Color.red(), label="❌ Denied by")
        await audit_log.log_event(
            interaction.client,
            title="❌ Discharge denied",
            color=discord.Color.red(),
            fields=[
                ("Reviewer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Member", f"<@{member_id}> (`{member_id}`)", True),
            ],
        )
