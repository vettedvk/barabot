"""
Discharge review — the Approve / Deny buttons attached to a discharge request in
the review channel. Only Bot Admins may act.

PERSISTENT and stateless: the member's Discord ID is read from the "Member" field
and the Discharge Log page id from the embed footer ('ref:<id>'); the roster page
is looked up fresh on click. So the buttons survive a bot restart. Registered
once at startup via bot.add_view(DischargeReviewView()).
"""

import discord

import audit_log
import notion_service as ns
import role_service
import util


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

        embed = interaction.message.embeds[0]
        member_id   = util.id_in_field(embed, "Member")
        log_page_id = util.ref_in_footer(embed)
        if member_id is None:
            await interaction.followup.send("❌ Couldn't read member from this message.", ephemeral=True)
            return

        # Mark EVERY active roster row Discharged + archived (specialised-
        # detachment members hold several), and the log entry Approved.
        pages = await ns.get_members_by_discord_id(str(member_id))
        active = [p for p in pages
                  if ns.extract_member_stats(p["properties"])["status"] == "Active"]
        lorename = ns.extract_member_stats(active[0]["properties"])["lorename"] if active else ""
        for page in active:
            await ns.discharge_member(page["id"])
        if log_page_id:
            await ns.update_discharge_log_status(log_page_id, "Approved", decided_by=str(interaction.user))

        # Strip military roles, grant Visitor (Verified is kept), and drop the
        # rank prefix from the nickname — the lore name stays.
        guild_member = interaction.guild.get_member(member_id)
        if guild_member:
            await role_service.apply_discharge_roles(guild_member, lorename=lorename)
            try:
                await guild_member.send(
                    "✅ Your discharge request has been **approved**. "
                    "Your service record has been archived. Go well — the storm remembers."
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

        embed = interaction.message.embeds[0]
        member_id   = util.id_in_field(embed, "Member")
        log_page_id = util.ref_in_footer(embed)

        if log_page_id:
            await ns.update_discharge_log_status(log_page_id, "Denied", decided_by=str(interaction.user))

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
