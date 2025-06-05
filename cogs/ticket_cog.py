# cogs/ticket_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui
from utils import db_manager, views # Relative imports
import json
import datetime

class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register persistent views. This is important for buttons to work after bot restarts.
        self.bot.add_view(views.TicketPanelView(bot))
        # For TicketActionsView, it's better to add it when the ticket is created
        # or re-add it in on_ready by iterating active ticket channels.
        # However, simple custom_id based callback matching also works.

    async def get_staff_roles_for_ticket_type(self, guild: discord.Guild, ticket_type_name: str, guild_config):
        """Determines the applicable staff roles for a given ticket type."""
        ticket_type_db = await db_manager.get_ticket_type_by_name(guild.id, ticket_type_name)
        
        specific_roles = []
        if ticket_type_db and ticket_type_db['specific_staff_roles']:
            role_ids = json.loads(ticket_type_db['specific_staff_roles'])
            for role_id in role_ids:
                role = guild.get_role(role_id)
                if role: specific_roles.append(role)
        
        if specific_roles:
            return specific_roles

        # Fallback to default staff roles
        default_roles = []
        if guild_config and guild_config['default_staff_roles']:
            role_ids = json.loads(guild_config['default_staff_roles'])
            for role_id in role_ids:
                role = guild.get_role(role_id)
                if role: default_roles.append(role)
        return default_roles if default_roles else [guild.default_role] # Fallback if nothing set


    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        if not interaction.data or 'custom_id' not in interaction.data:
            return

        custom_id = interaction.data['custom_id']
        parts = custom_id.split(':')
        action_type = parts[0]

        if action_type == "ticket_panel" and parts[1] == "create":
            # Custom ID: ticket_panel:create:{guild_id}:{type_name}
            await interaction.response.defer(ephemeral=True, thinking=True)
            
            try:
                guild_id_from_id = int(parts[2])
                ticket_type_name = parts[3]
            except (IndexError, ValueError):
                await interaction.followup.send("Invalid button ID.", ephemeral=True)
                return

            if interaction.guild_id != guild_id_from_id: # Should not happen with well-formed IDs
                await interaction.followup.send("Button belongs to a different server.", ephemeral=True)
                return

            guild = interaction.guild
            user = interaction.user
            guild_config = await db_manager.get_guild_config(guild.id)
            ticket_type_db = await db_manager.get_ticket_type_by_name(guild.id, ticket_type_name)

            if not guild_config or not guild_config['ticket_channel_category_id'] or not ticket_type_db:
                await interaction.followup.send("Ticket system is not fully configured. Contact an admin.", ephemeral=True)
                return

            # Check ticket limit
            open_tickets = await db_manager.get_open_tickets_by_user(guild.id, user.id)
            if len(open_tickets) >= guild_config.get('ticket_limit_per_user', 1):
                await interaction.followup.send(f"You have reached the maximum limit of {guild_config.get('ticket_limit_per_user', 1)} open ticket(s).", ephemeral=True)
                return

            ticket_creation_category = guild.get_channel(guild_config['ticket_channel_category_id'])
            if not ticket_creation_category or not isinstance(ticket_creation_category, discord.CategoryChannel):
                await interaction.followup.send("Configured ticket category is invalid. Admin needs to fix this.", ephemeral=True)
                return

            staff_roles_to_apply = await self.get_staff_roles_for_ticket_type(guild, ticket_type_name, guild_config)
            if not staff_roles_to_apply or staff_roles_to_apply == [guild.default_role]: # Check if any valid roles were found
                 await interaction.followup.send("No valid staff roles configured for this ticket type. Admin needs to fix this.", ephemeral=True)
                 return


            ticket_display_id = await db_manager.get_and_increment_ticket_counter(guild.id)
            
            # Naming format
            naming_format = guild_config.get('ticket_naming_format', 'ticket-{user_short}-{id}')
            user_short_name = user.name.split('#')[0][:10] # First 10 chars of username
            channel_name_raw = naming_format.replace("{user_full}", user.name).replace("{user_short}", user_short_name).replace("{id}", f"{ticket_display_id:04d}").replace("{type}", ticket_type_name)
            channel_name = "".join(c if c.isalnum() or c == '-' else '' for c in channel_name_raw.lower())[:100]


            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True, view_channel=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_permissions=True) # Bot needs these
            }
            for role in staff_roles_to_apply:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, attach_files=True, embed_links=True, view_channel=True)

            try:
                ticket_channel = await ticket_creation_category.create_text_channel(
                    name=channel_name,
                    overwrites=overwrites,
                    topic=f"Ticket #{ticket_display_id} | User: {user.display_name} ({user.id}) | Type: {ticket_type_db['display_name']}"
                )
            except discord.HTTPException as e:
                print(f"Failed to create ticket channel for {user.name}: {e}")
                await interaction.followup.send(f"Failed to create ticket channel: {e}. Ensure I have 'Manage Channels' permission in the category.", ephemeral=True)
                # TODO: Potentially decrement ticket counter if creation fails. Requires careful handling.
                return

            await db_manager.create_ticket(guild.id, user.id, ticket_channel.id, ticket_type_name, ticket_display_id)

            # Welcome message in ticket
            welcome_msg_text = ticket_type_db.get('welcome_message') or \
                               f"Welcome {user.mention}! You've opened a **{ticket_type_db['display_name']}** ticket.\n" \
                               "Please describe your issue, and a staff member will assist you shortly."
            
            ticket_embed = discord.Embed(
                title=f"{ticket_type_db['display_name']} - Ticket #{ticket_display_id}",
                description=welcome_msg_text,
                color=discord.Color.green() # Or category-specific color
            )
            ticket_embed.set_footer(text=f"User ID: {user.id}")
            
            actions_view = views.TicketActionsView(self.bot, ticket_channel.id, user.id)
            await ticket_channel.send(content=user.mention, embed=ticket_embed, view=actions_view)
            await interaction.followup.send(f"Ticket created: {ticket_channel.mention}", ephemeral=True)

            # Staff Notification
            if guild_config['log_channel_id']:
                log_channel = guild.get_channel(guild_config['log_channel_id'])
                if log_channel:
                    staff_mentions = " ".join([role.mention for role in staff_roles_to_apply if role != guild.default_role and role.mentionable])
                    notif_embed = discord.Embed(
                        title=f"🆕 New Ticket: {ticket_type_db['display_name']}",
                        description=f"**Opened by:** {user.mention} ({user.name})\n"
                                    f"**Ticket:** {ticket_channel.mention} (`#{ticket_display_id}`)",
                        color=discord.Color.blue(),
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    try:
                        await log_channel.send(content=staff_mentions if staff_mentions else None, embed=notif_embed)
                    except Exception as e:
                        print(f"Failed to send staff log notification: {e}")
        
        elif action_type == "ticket_actions" and parts[1] == "close":
            # Custom ID: ticket_actions:close:{channel_id}:{owner_id}
            try:
                channel_id_from_id = int(parts[2])
                # owner_id_from_id = int(parts[3]) # Not strictly needed for permission check if we use DB
            except (IndexError, ValueError):
                await interaction.response.send_message("Invalid close button ID.", ephemeral=True)
                return

            if interaction.channel_id != channel_id_from_id:
                await interaction.response.send_message("This button is for a different ticket.", ephemeral=True)
                return

            ticket_data = await db_manager.get_ticket_by_channel(interaction.channel_id)
            if not ticket_data or ticket_data['status'] == 'closed':
                await interaction.response.send_message("This ticket is not valid or already closed.", ephemeral=True)
                return

            guild_config = await db_manager.get_guild_config(interaction.guild_id)
            can_user_close = guild_config.get('allow_user_close', 1) == 1 if guild_config else False
            
            is_owner = interaction.user.id == ticket_data['user_id']
            
            # Determine if interactor is staff for this ticket
            applicable_staff_roles = await self.get_staff_roles_for_ticket_type(interaction.guild, ticket_data['ticket_type_name'], guild_config)
            is_staff = any(role in interaction.user.roles for role in applicable_staff_roles if role != interaction.guild.default_role)
            
            if not is_staff and (not is_owner or not can_user_close):
                await interaction.response.send_message("You do not have permission to close this ticket.", ephemeral=True)
                return
            
            modal = views.CloseTicketModal(bot=self.bot, ticket_channel_id=interaction.channel_id)
            await interaction.response.send_modal(modal)


    ticket_panel_group = app_commands.Group(name="ticketpanel", description="Manage the ticket creation panel.")

    @ticket_panel_group.command(name="create", description="Creates/updates the ticket panel in the current channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def create_ticket_panel(self, interaction: discord.Interaction,
                                  title: str = "Support Tickets",
                                  description: str = "Click a button below to open a ticket for the respective category."):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        
        guild_config = await db_manager.get_guild_config(guild_id)
        if not guild_config or not guild_config['ticket_channel_category_id'] or not guild_config['default_staff_roles']:
            await interaction.followup.send("Please run `/configticket setupdefaults` first.", ephemeral=True)
            return

        ticket_types = await db_manager.get_ticket_types(guild_id)
        if not ticket_types:
            await interaction.followup.send("No ticket types configured. Use `/configticket tickettype add` to add some.", ephemeral=True)
            return

        embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
        view = views.TicketPanelView(self.bot)
        await view.populate_buttons(guild_id) # Crucial to populate based on current guild

        if not view.children or (len(view.children) == 1 and view.children[0].custom_id == "ticket_panel:no_types"):
             await interaction.followup.send("Panel not created: No ticket types found or an error occurred populating buttons.", ephemeral=True)
             return

        try:
            # If an old panel message exists, try to delete it or edit it
            if guild_config.get('panel_message_id') and guild_config.get('panel_channel_id'):
                try:
                    old_panel_channel = self.bot.get_channel(guild_config['panel_channel_id'])
                    if old_panel_channel:
                        old_panel_message = await old_panel_channel.fetch_message(guild_config['panel_message_id'])
                        await old_panel_message.delete()
                        print(f"Old ticket panel deleted in guild {guild_id}")
                except (discord.NotFound, discord.Forbidden, AttributeError):
                    print(f"Could not delete old panel message in guild {guild_id}. It might have been deleted manually.")
            
            panel_message = await interaction.channel.send(embed=embed, view=view)
            await db_manager.update_guild_config(
                guild_id,
                panel_channel_id=interaction.channel_id,
                panel_message_id=panel_message.id
            )
            await interaction.followup.send(f"Ticket panel created/updated in {interaction.channel.mention}!", ephemeral=True)
        except Exception as e:
            print(f"Error creating panel: {e}")
            await interaction.followup.send(f"Error creating panel: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    # Ensure the utils package can be found if running bot.py from parent dir
    import sys
    if './utils' not in sys.path: # Ensure utils is in path if running from top level
        sys.path.append('./utils')
        
    await bot.add_cog(TicketCog(bot))
    print("TicketCog Loaded")
