"""
Enlistment / Envoy application review — the Accept / Decline buttons posted to the
enlistment review channel. Only the reviewer roles in config may act.

PERSISTENT and stateless: every value an action needs is recovered from the embed
on click (applicant Discord ID from the "Applicant" field; Roblox details and the
chosen Company from their fields), so the buttons survive a restart. Registered
once at startup via bot.add_view() for each view class.
"""

import discord

import audit_log
import config
import notion_service as ns
import role_service
import util
from rank_engine import AUTO_LADDERS


class EnlistmentReviewView(discord.ui.View):
    """Approve/deny a military enlistment; on approval create/reactivate the roster row."""

    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅",
                       custom_id="vel_enlist_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not util.is_reviewer(interaction.user):
            await interaction.response.send_message("❌ You can't review applications.", ephemeral=True)
            return
        await interaction.response.defer()

        embed = interaction.message.embeds[0]
        applicant_id = util.id_in_field(embed, "Applicant")
        if applicant_id is None:
            await interaction.followup.send("❌ Couldn't read applicant from this message.", ephemeral=True)
            return

        roblox_name = util.embed_field(embed, "Roblox Username") or ""
        roblox_id   = util.embed_field(embed, "Roblox ID") or ""
        lorename    = util.embed_field(embed, "Lore Name") or ""
        # "Retinue" on new applications; "Fleet" kept for pre-switch embeds.
        company     = (util.embed_field(embed, "Retinue")
                       or util.embed_field(embed, "Fleet") or "Black Stags")
        # Starting rank = the bottom of the retinue's auto ladder (or Levy fallback).
        ladder = AUTO_LADDERS.get(company)
        rank   = ladder[0] if ladder else "Levy"

        discord_user_id = str(applicant_id)
        member = interaction.guild.get_member(applicant_id)
        discord_username = str(member) if member else discord_user_id

        # Reactivate a prior roster row if one exists; otherwise create a new one.
        existing = await ns.get_member_by_discord_id(discord_user_id)
        if existing:
            if ns.extract_member_stats(existing["properties"])["status"] != "Active":
                await ns.reactivate_member(existing["id"], discord_username, detachment=company, rank=rank)
        else:
            await ns.create_member(
                roblox_username=roblox_name,
                roblox_id=str(roblox_id),
                lorename=lorename,
                discord_username=discord_username,
                discord_user_id=discord_user_id,
                detachment=company,
                rank=rank,
            )

        # Apply fleet + rank roles + nickname, house membership, Verified, and
        # drop the temporary join role (separators are handled by role hygiene).
        if member:
            await role_service.apply_rank_and_company(member, company, rank, lorename=lorename)
            await role_service.add_house_membership_roles(member)
            await util.grant_role(member, config.ROLE_VERIFIED, "Enlisted in House Baratheon")
            await util.remove_role(member, config.ROLE_UNVERIFIED, "Enlisted — removing join role")
            await util.remove_role(member, config.ROLE_VISITOR, "Enlisted — no longer a visitor")
            try:
                await member.send(
                    f"⚡ Your enlistment has been **approved**! Welcome to House Baratheon, "
                    f"**{roblox_name}**. You've joined the **{company}** at the rank of "
                    f"**{rank}**. Ours is the Fury."
                )
            except discord.HTTPException:
                pass

        await util.finalize_review(interaction, self, color=discord.Color.green(), label="✅ Approved by")
        await audit_log.log_event(
            interaction.client,
            title="✅ Enlistment approved",
            color=discord.Color.green(),
            fields=[
                ("Reviewer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Applicant", f"<@{applicant_id}> (`{applicant_id}`)", True),
                ("Posting", f"{company} / {rank}", True),
                ("Roblox", f"{roblox_name} (`{roblox_id}`)", False),
            ],
        )

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌",
                       custom_id="vel_enlist_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not util.is_reviewer(interaction.user):
            await interaction.response.send_message("❌ You can't review applications.", ephemeral=True)
            return
        await interaction.response.defer()

        applicant_id = util.id_in_field(interaction.message.embeds[0], "Applicant")
        member = interaction.guild.get_member(applicant_id) if applicant_id else None
        if member:
            try:
                await member.send(
                    f"❌ Your enlistment application was **declined** by {interaction.user.mention}. "
                    "You may contact an officer for guidance."
                )
            except discord.HTTPException:
                pass

        await util.finalize_review(interaction, self, color=discord.Color.red(), label="❌ Declined by")
        await audit_log.log_event(
            interaction.client,
            title="❌ Enlistment declined",
            color=discord.Color.red(),
            fields=[
                ("Reviewer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Applicant", f"<@{applicant_id}> (`{applicant_id}`)", True),
            ],
        )


class EnvoyReviewView(discord.ui.View):
    """Approve/deny a diplomatic (envoy) application; on approval grant the Envoy role."""

    def __init__(self):
        super().__init__(timeout=None)  # persistent

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅",
                       custom_id="vel_envoy_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not util.is_reviewer(interaction.user):
            await interaction.response.send_message("❌ You can't review applications.", ephemeral=True)
            return
        await interaction.response.defer()

        applicant_id = util.id_in_field(interaction.message.embeds[0], "Applicant")
        member = interaction.guild.get_member(applicant_id) if applicant_id else None
        if member:
            # Envoy role assignment is reported explicitly if it fails, since it's
            # the whole point of approving a diplomatic application.
            role = interaction.guild.get_role(config.ROLE_ENVOY)
            if role:
                try:
                    await member.add_roles(role, reason="Envoy application approved")
                except discord.Forbidden:
                    await interaction.followup.send(
                        "⚠️ Approved, but I couldn't assign the Envoy role (check role hierarchy).",
                        ephemeral=True,
                    )
            await util.grant_role(member, config.ROLE_VERIFIED, "Enlisted in House Baratheon")
            await util.remove_role(member, config.ROLE_UNVERIFIED, "Enlisted — removing join role")
            try:
                await member.send(
                    "🕊️ Your envoy application to House Baratheon has been **approved**. "
                    "You have been granted diplomatic standing."
                )
            except discord.HTTPException:
                pass

        await util.finalize_review(interaction, self, color=discord.Color.green(), label="✅ Approved by")
        await audit_log.log_event(
            interaction.client,
            title="✅ Envoy application approved",
            color=discord.Color.green(),
            fields=[
                ("Reviewer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Applicant", f"<@{applicant_id}> (`{applicant_id}`)", True),
            ],
        )

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌",
                       custom_id="vel_envoy_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not util.is_reviewer(interaction.user):
            await interaction.response.send_message("❌ You can't review applications.", ephemeral=True)
            return
        await interaction.response.defer()

        applicant_id = util.id_in_field(interaction.message.embeds[0], "Applicant")
        member = interaction.guild.get_member(applicant_id) if applicant_id else None
        if member:
            try:
                await member.send(
                    f"❌ Your envoy application was **declined** by {interaction.user.mention}."
                )
            except discord.HTTPException:
                pass

        await util.finalize_review(interaction, self, color=discord.Color.red(), label="❌ Declined by")
        await audit_log.log_event(
            interaction.client,
            title="❌ Envoy application declined",
            color=discord.Color.red(),
            fields=[
                ("Reviewer", f"{interaction.user.mention} (`{interaction.user.id}`)", True),
                ("Applicant", f"<@{applicant_id}> (`{applicant_id}`)", True),
            ],
        )
