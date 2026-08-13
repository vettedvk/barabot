"""
LOA review — the Approve / Deny buttons attached to an LOA request in the
approval channel. Approvers: Bot Admins, Military Command officers, and the
Court (util.is_loa_reviewer).

PERSISTENT and stateless: the member's Discord ID is read from the "Member"
field and the LOA Log page id from the embed footer ('ref:<id>'); the roster
pages are looked up fresh on click, so the buttons survive a bot restart.
Registered once at startup via bot.add_view(LOAReviewView()).

Unlike discharge, an approved LOA does NOT archive the roster rows — each active
row's Status is set to "LOA" (they're coming back) and the LOA role is granted.
Use /end_loa to restore a member when their leave is over.
"""

import re
from datetime import date, timedelta

import discord

import audit_log
import config
import notion_service as ns
import util


class LOAReviewView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="Approve LOA", style=discord.ButtonStyle.success, emoji="✅",
                       custom_id="bar_loa_accept")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not util.is_loa_reviewer(interaction.user):
            await interaction.response.send_message(
                "❌ Only Command, the Court, or Bot Admins may review LOA requests.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()

        embed = interaction.message.embeds[0]
        member_id   = util.id_in_field(embed, "Member")
        log_page_id = util.ref_in_footer(embed)
        if member_id is None:
            await interaction.followup.send("❌ Couldn't read member from this message.", ephemeral=True)
            return

        # The requested day count is carried in the "Duration" field ("14 days").
        # Stamp an auto-expiry date so the LOA restores itself; fall back to a
        # plain LOA (manual /end_loa) if it can't be parsed (e.g. old requests).
        m = re.search(r"\d+", util.embed_field(embed, "Duration") or "")
        until = date.today() + timedelta(days=int(m.group())) if m else None

        # Set every ACTIVE roster row to LOA (specialised-detachment members hold
        # several). Rows are NOT archived — the member is on leave, not gone.
        pages = await ns.get_members_by_discord_id(str(member_id))
        active = [p for p in pages
                  if ns.extract_member_stats(p["properties"])["status"] == "Active"]
        for page in active:
            if until:
                await ns.set_member_loa(page["id"], until)
            else:
                await ns.set_member_status(page["id"], config.LOA_STATUS)
        if log_page_id:
            await ns.update_loa_log_status(log_page_id, "Approved", decided_by=str(interaction.user))

        # Tag the member with the LOA role (keeps all their other roles).
        guild_member = interaction.guild.get_member(member_id)
        if guild_member:
            await util.grant_role(guild_member, config.ROLE_LOA, reason="LOA approved")
            back = f" You'll be automatically restored on **{until.isoformat()}**." if until else ""
            try:
                await guild_member.send(
                    "✅ Your **Leave of Absence** request has been **approved**. "
                    f"Rest well — your post will be here when you return.{back} "
                    "Ours is the Fury."
                )
            except discord.HTTPException:
                pass

        await util.finalize_review(interaction, self, color=discord.Color.green(), label="✅ Approved by")
        await audit_log.log_event(
            interaction.client,
            title="✅ LOA approved",
            color=discord.Color.green(),
            fields=[
                ("Reviewer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Member", f"<@{member_id}> (`{member_id}`)", True),
                ("Rows set to LOA", str(len(active)), True),
            ],
        )

    @discord.ui.button(label="Deny LOA", style=discord.ButtonStyle.danger, emoji="❌",
                       custom_id="bar_loa_decline")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not util.is_loa_reviewer(interaction.user):
            await interaction.response.send_message(
                "❌ Only Command, the Court, or Bot Admins may review LOA requests.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()

        embed = interaction.message.embeds[0]
        member_id   = util.id_in_field(embed, "Member")
        log_page_id = util.ref_in_footer(embed)

        if log_page_id:
            await ns.update_loa_log_status(log_page_id, "Denied", decided_by=str(interaction.user))

        if member_id:
            requester = interaction.guild.get_member(member_id)
            if requester:
                try:
                    await requester.send(
                        "❌ Your **Leave of Absence** request was **denied** by "
                        f"{interaction.user.mention}. Contact an officer if you have questions."
                    )
                except discord.HTTPException:
                    pass

        await util.finalize_review(interaction, self, color=discord.Color.red(), label="❌ Denied by")
        await audit_log.log_event(
            interaction.client,
            title="❌ LOA denied",
            color=discord.Color.red(),
            fields=[
                ("Reviewer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Member", f"<@{member_id}> (`{member_id}`)", True),
            ],
        )
