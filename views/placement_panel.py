"""
Post-training placement — the in-channel prompt the host gets after logging a
Basic Levy Training via /log_event. New Levys aren't auto-sorted, so the host
walks each attendee into a retinue here; placement sets their detachment and
promotes them Levy → Soldier (they've completed the training).

Not persistent — it carries per-session state (which recruit is being placed)
and times out. Only the host or an officer may use it.
"""

import logging

import discord

import config
import notion_service as ns
import role_service
import util

log = logging.getLogger(__name__)


class PlacementView(discord.ui.View):
    def __init__(self, host_id: int, recruits: list[tuple[str, str]]):
        super().__init__(timeout=1800)
        self.host_id = host_id
        self.recruits: dict[str, str] = dict(recruits)  # discord_id -> label
        self.pending: str | None = None

        self.recruit_select = discord.ui.Select(placeholder="① Pick a recruit", row=0)
        self.retinue_select = discord.ui.Select(
            placeholder="② Assign a retinue", row=1,
            options=[discord.SelectOption(label=d, value=d) for d in config.PLACEMENT_DETACHMENTS],
        )
        self.recruit_select.callback = self._on_recruit
        self.retinue_select.callback = self._on_retinue
        self._refresh_recruit_options()
        self.add_item(self.recruit_select)
        self.add_item(self.retinue_select)

    def _refresh_recruit_options(self):
        opts = [discord.SelectOption(label=lbl[:100], value=uid)
                for uid, lbl in list(self.recruits.items())[:25]]
        self.recruit_select.options = opts or [discord.SelectOption(label="(all placed)", value="none")]
        self.recruit_select.disabled = not self.recruits
        self.retinue_select.disabled = not self.recruits

    def embed(self) -> discord.Embed:
        e = discord.Embed(title="🪖 Place your recruits", color=discord.Color.gold())
        if not self.recruits:
            e.description = "✅ All recruits placed. Ours is the Fury."
        else:
            listing = "\n".join(f"• <@{uid}>" for uid in self.recruits)
            note = f"\n\n**Now placing:** <@{self.pending}> — choose a retinue below." if self.pending else ""
            e.description = (
                "These attendees still need a retinue (placing them makes them a "
                f"**Soldier**):\n{listing}{note}\n\n① pick a recruit, then ② choose their retinue."
            )
        return e

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.host_id or util.is_officer(interaction.user):
            return True
        await interaction.response.send_message(
            "❌ Only the host or an officer can place these recruits.", ephemeral=True)
        return False

    async def _on_recruit(self, interaction: discord.Interaction):
        val = self.recruit_select.values[0]
        if val == "none":
            await interaction.response.defer()
            return
        self.pending = val
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _on_retinue(self, interaction: discord.Interaction):
        if not self.pending:
            await interaction.response.send_message(
                "Pick a recruit first (menu ①).", ephemeral=True)
            return
        det = self.retinue_select.values[0]
        uid = self.pending
        await interaction.response.defer()

        member = interaction.guild.get_member(int(uid)) if uid.isdigit() else None
        try:
            pages = await ns.get_members_by_discord_id(uid)
            target = next((p for p in pages
                           if not ns.extract_member_stats(p["properties"])["detachment"]), None)
            target = target or (pages[0] if pages else None)
            lorename = ns.extract_member_stats(target["properties"])["lorename"] if target else ""
            if target:
                await ns.set_member_company(target["id"], det, "Soldier", reset_points=True)
            if member:
                await role_service.apply_rank_and_company(
                    member, det, "Soldier", old_rank="Levy", lorename=lorename)
                try:
                    await member.send(
                        f"⚔️ You've been placed into the **{det}** as a **Soldier**. "
                        "Ours is the Fury.")
                except discord.HTTPException:
                    pass
        except Exception as exc:
            log.error("placement failed for %s: %s", uid, exc)
            await interaction.followup.send(f"⚠️ Couldn't place <@{uid}> — {exc}", ephemeral=True)
            return

        self.recruits.pop(uid, None)
        self.pending = None
        self._refresh_recruit_options()
        if not self.recruits:
            for child in self.children:
                child.disabled = True
            self.stop()
        await interaction.message.edit(embed=self.embed(), view=self)
