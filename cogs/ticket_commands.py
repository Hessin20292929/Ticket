# cogs/ticket_commands.py
import discord
from discord.ext import commands
from discord import app_commands
from utils import db_manager, views # Relative imports
import json

class TicketCommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    ticket_group = app_commands.Group(name="ticket", description="Manage tickets.")

    @ticket_group.command(name="close", description="Closes the current ticket channel (if used within one) or a specified one.")
    @app_commands.describe(reason="Optional reason for closing the ticket.")
    async def close_ticket_command(self, interaction: discord.Interaction, reason: str = None):
        # This command can be used by staff directly.
        # The button in TicketActionsView uses a modal, this is an alternative.
        
        ticket_data = await db_manager.get_ticket_by_channel(interaction.channel_id)
        if not ticket_data or ticket_data['status'] == 'closed':
            await interaction.response.send_message("This is not an active ticket channel or it's already closed.", ephemeral=True)
            return

        guild_config = await db_manager.get_guild_config(interaction.guild_id)
        if not guild_config:
            await interaction.response.send_message("Server configuration not found.", ephemeral=True)
            return
            
        # Permission check (simplified for command context, more robust check in modal)
        # Here, we assume if someone can run this slash command, they are staff
        # For more fine-grained control, check against configured staff roles.
        cog = self.bot.get_cog("TicketCog") # Get the other cog to use its helper
        if not cog:
            await interaction.response.send_message("TicketCog not found, cannot verify staff roles.", ephemeral=True)
            return
            
        applicable_staff_roles = await cog.get_staff_roles_for_ticket_type(interaction.guild, ticket_data['ticket_type_name'], guild_config)
        is_staff = any(role in interaction.user.roles for role in applicable_staff_roles if role != interaction.guild.default_role)

        if not is_staff:
            await interaction.response.send_message("You do not have permission to close this ticket using this command.", ephemeral=True)
            return
        
        # Initiate the close process using the modal for consistency
        # Or, directly call a shared close function if you refactor that out of the modal.
        # For now, let's just say this command prompts the modal too.
        # Or, for a command, it might just close directly:
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        # --- Re-implementing close logic here for command (can be refactored) ---
        close_reason_text = reason or "Closed via command."
        ticket_channel = interaction.channel 
        
        transcript_message_link = None # Placeholder
        if guild_config['transcript_channel_id']:
            # (Simplified transcript logic - copy from CloseTicketModal if needed fully)
            transcript_channel_obj = interaction.guild.get_channel(guild_config['transcript_channel_id'])
            if transcript_channel_obj:
                 await transcript_channel_obj.send(f"Transcript for {ticket_channel.name} (closed by {interaction.user.name} via command): Reason - {close_reason_text}. Full transcript would go here.")
                 # transcript_message_link = ... (get jump_url of the above message)
        
        await db_manager.update_ticket(
            channel_id=ticket_channel.id,
            status='closed',
            closed_by_user_id=interaction.user.id,
            closed_at=datetime.datetime.now(datetime.timezone.utc),
            close_reason=close_reason_text,
            transcript_message_id=None # Update if you generate transcript
        )
        new_name = f"closed-{ticket_data['ticket_display_id']}-{ticket_data['ticket_type_name']}"
        try:
            await ticket_channel.edit(name=new_name)
            # Further permission/archiving logic as in modal
            await ticket_channel.send(f"Ticket closed by {interaction.user.mention} via command. Reason: {close_reason_text}")
            await interaction.followup.send("Ticket closed.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ticket closed in DB, but error modifying channel: {e}", ephemeral=True)


    # Add more commands: /ticket adduser, /ticket claim, /ticket reopen, /ticket priority, etc.

async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCommandsCog(bot))
    print("TicketCommandsCog Loaded")
