# utils/views.py
import discord
from discord import ui
from . import db_manager # Using . for relative import within package
import datetime
import io # For transcript file

# --- Modals ---
class CloseTicketModal(ui.Modal, title="Close Ticket"):
    reason_input = ui.TextInput(
        label="Reason for closing (optional)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )

    def __init__(self, bot, ticket_channel_id: int):
        super().__init__()
        self.bot = bot
        self.ticket_channel_id = ticket_channel_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        guild_config = await db_manager.get_guild_config(interaction.guild_id)
        ticket_data = await db_manager.get_ticket_by_channel(self.ticket_channel_id)
        ticket_channel = interaction.guild.get_channel(self.ticket_channel_id)

        if not ticket_data or not ticket_channel or not guild_config:
            await interaction.followup.send("Error: Ticket or configuration not found.", ephemeral=True)
            return

        reason = self.reason_input.value or "No reason provided."

        # --- Transcript Generation ---
        transcript_message_link = None
        if guild_config['transcript_channel_id']:
            transcript_channel = interaction.guild.get_channel(guild_config['transcript_channel_id'])
            if transcript_channel:
                messages = []
                async for message in ticket_channel.history(limit=None, oldest_first=True):
                    messages.append(
                        f"[{message.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}] "
                        f"{message.author.display_name} ({message.author.id}): {message.content}"
                    )
                    if message.attachments:
                        for att in message.attachments:
                            messages.append(f"  [Attachment: {att.filename} - {att.url}]")

                transcript_content = "\n".join(messages)
                transcript_filename = f"transcript-{ticket_channel.name.replace('ticket-', '')}.txt"
                
                try:
                    transcript_file = discord.File(io.StringIO(transcript_content), filename=transcript_filename)
                    ticket_creator = await self.bot.fetch_user(ticket_data['user_id'])
                    
                    embed = discord.Embed(
                        title=f"Ticket Transcript - #{ticket_data['ticket_display_id']}",
                        color=discord.Color.greyple(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.add_field(name="Opened By", value=f"{ticket_creator.mention} ({ticket_creator.id})", inline=True)
                    embed.add_field(name="Closed By", value=f"{interaction.user.mention} ({interaction.user.id})", inline=True)
                    embed.add_field(name="Reason", value=reason, inline=False)
                    embed.add_field(name="Channel", value=f"`{ticket_channel.name}` ({ticket_channel.id})", inline=False)
                    
                    transcript_msg = await transcript_channel.send(embed=embed, file=transcript_file)
                    transcript_message_link = transcript_msg.jump_url
                except Exception as e:
                    print(f"Error sending transcript for ticket {ticket_channel.id}: {e}")
                    await interaction.followup.send("Ticket closed, but an error occurred while sending the transcript.", ephemeral=True)
            else:
                await interaction.followup.send("Transcript channel not found, but closing ticket.", ephemeral=True)
        
        # --- Update DB ---
        await db_manager.update_ticket(
            channel_id=self.ticket_channel_id,
            status='closed',
            closed_by_user_id=interaction.user.id,
            closed_at=datetime.datetime.now(datetime.timezone.utc),
            close_reason=reason,
            transcript_message_id=transcript_message_link # Store link or ID of transcript message
        )

        # --- Notify User in Ticket Channel ---
        close_embed = discord.Embed(
            title="Ticket Closed",
            description=f"This ticket has been closed by {interaction.user.mention}.\nReason: {reason}",
            color=discord.Color.red()
        )
        if transcript_message_link:
            close_embed.add_field(name="Transcript", value=f"[View Transcript]({transcript_message_link})")
        
        try:
            await ticket_channel.send(embed=close_embed)
        except discord.HTTPException:
            pass # Channel might already be inaccessible to bot

        # --- Modify Channel (Archive or Permissions) ---
        new_name = f"closed-{ticket_data['ticket_display_id']}-{ticket_data['ticket_type_name']}"
        user_who_opened = interaction.guild.get_member(ticket_data['user_id']) # get_member is fine here as they are in guild
        
        try:
            if guild_config['archive_channel_category_id']:
                archive_category = interaction.guild.get_channel(guild_config['archive_channel_category_id'])
                if archive_category:
                    await ticket_channel.edit(name=new_name, category=archive_category, sync_permissions=True)
                    # Further refine permissions in archive if needed (e.g., remove user access)
                    if user_who_opened:
                        await ticket_channel.set_permissions(user_who_opened, overwrite=None) # Remove specific user perms
                else: # Fallback if archive category not found
                    await ticket_channel.edit(name=new_name)
                    if user_who_opened: await ticket_channel.set_permissions(user_who_opened, send_messages=False, read_messages=True)
            else: # No archive category, just rename and lock
                await ticket_channel.edit(name=new_name)
                if user_who_opened: await ticket_channel.set_permissions(user_who_opened, send_messages=False, read_messages=True)
            
            await interaction.followup.send(f"Ticket #{ticket_data['ticket_display_id']} has been closed.", ephemeral=True)
        except Exception as e:
            print(f"Error archiving/modifying channel {ticket_channel.id}: {e}")
            await interaction.followup.send("Ticket closed, but an error occurred modifying the channel.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        print(f"Error in CloseTicketModal: {error}")
        await interaction.response.send_message("Oops! Something went wrong.", ephemeral=True)


# --- Views for Ticket Panel and In-Ticket Actions ---
class TicketActionsView(ui.View):
    def __init__(self, bot, ticket_channel_id: int, ticket_owner_id: int):
        super().__init__(timeout=None) # Persistent
        self.bot = bot
        self.ticket_channel_id = ticket_channel_id
        self.ticket_owner_id = ticket_owner_id
        # The custom_id helps re-identify this view if the bot restarts
        self.add_item(ui.Button(label="Close Ticket", style=discord.ButtonStyle.red, custom_id=f"ticket_actions:close:{ticket_channel_id}:{ticket_owner_id}", emoji="🔒"))
        # Add other buttons like "Claim Ticket" (for staff) here later

class TicketPanelView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None) # Persistent
        self.bot = bot
        # Buttons will be added dynamically by populate_buttons

    async def populate_buttons(self, guild_id: int):
        self.clear_items() # Clear before adding new ones
        ticket_types = await db_manager.get_ticket_types(guild_id)
        
        if not ticket_types:
            self.add_item(ui.Button(label="No ticket types configured", style=discord.ButtonStyle.grey, disabled=True, custom_id="ticket_panel:no_types"))
            return

        for tt_row in ticket_types:
            style_map = {
                'primary': discord.ButtonStyle.primary,
                'secondary': discord.ButtonStyle.secondary,
                'success': discord.ButtonStyle.success,
                'danger': discord.ButtonStyle.danger,
            }
            button_style = style_map.get(tt_row['button_style'].lower(), discord.ButtonStyle.primary)
            
            self.add_item(ui.Button(
                label=tt_row['display_name'],
                emoji=tt_row['emoji'] if tt_row['emoji'] else None,
                style=button_style,
                custom_id=f"ticket_panel:create:{guild_id}:{tt_row['name']}" # Include guild_id and type_name
            ))
