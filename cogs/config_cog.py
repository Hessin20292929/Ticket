# cogs/config_cog.py
import discord
from discord.ext import commands
from discord import app_commands
from utils import db_manager # Relative import
import json

class ConfigCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    config_group = app_commands.Group(name="configticket", description="Configure the ticket system for this server.")
    type_group = app_commands.Group(name="tickettype", description="Manage ticket types/departments.", parent=config_group)

    @config_group.command(name="setupdefaults", description="Initial basic setup (staff role, ticket category).")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_defaults(self, interaction: discord.Interaction,
                             staff_role: discord.Role,
                             ticket_creation_category: discord.CategoryChannel,
                             transcript_channel: discord.TextChannel = None,
                             log_channel: discord.TextChannel = None,
                             archive_category: discord.CategoryChannel = None):
        await interaction.response.defer(ephemeral=True)
        
        default_staff_roles_json = json.dumps([staff_role.id])

        await db_manager.update_guild_config(
            interaction.guild_id,
            default_staff_roles=default_staff_roles_json,
            ticket_channel_category_id=ticket_creation_category.id,
            transcript_channel_id=transcript_channel.id if transcript_channel else None,
            log_channel_id=log_channel.id if log_channel else None,
            archive_channel_category_id=archive_category.id if archive_category else None,
            ticket_naming_format='ticket-{user_short}-{id}', # Default format
            ticket_limit_per_user=1,
            allow_user_close=1
        )
        await interaction.followup.send(
            f"Basic ticket configuration updated!\n"
            f"- Staff Role: {staff_role.mention}\n"
            f"- Ticket Category: {ticket_creation_category.name}\n"
            f"- Transcript Channel: {transcript_channel.mention if transcript_channel else 'Not set'}\n"
            f"- Log Channel: {log_channel.mention if log_channel else 'Not set'}\n"
            f"- Archive Category: {archive_category.name if archive_category else 'Not set'}\n"
            f"Now, add ticket types using `/configticket tickettype add`.",
            ephemeral=True
        )

    @type_group.command(name="add", description="Add a new ticket type/department.")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_type(self, interaction: discord.Interaction,
                       internal_name: str, # Used in custom_ids, no spaces
                       display_name: str,
                       description: str = None,
                       emoji: str = None,
                       button_style: app_commands.Choice[str] = None, # Will be 'primary', 'secondary', etc.
                       welcome_message: str = None,
                       specific_staff_role: discord.Role = None):
        await interaction.response.defer(ephemeral=True)
        internal_name_clean = internal_name.lower().replace(" ", "-")
        
        # Validate button style choice
        valid_styles = ['primary', 'secondary', 'success', 'danger']
        actual_button_style = button_style.value if button_style and button_style.value in valid_styles else 'primary'

        roles_list = [specific_staff_role.id] if specific_staff_role else None

        success = await db_manager.add_ticket_type(
            guild_id=interaction.guild_id,
            name=internal_name_clean,
            display_name=display_name,
            description=description,
            emoji=emoji,
            button_style=actual_button_style,
            welcome_message=welcome_message,
            specific_staff_roles=roles_list
        )
        if success:
            await interaction.followup.send(f"Ticket type '{display_name}' added with internal name `{internal_name_clean}`.", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed to add ticket type. An internal name `{internal_name_clean}` might already exist.", ephemeral=True)
        
        if button_style and button_style.value not in valid_styles:
             await interaction.followup.send(f"Warning: Invalid button style '{button_style.value}' provided. Defaulted to primary. Valid styles: {', '.join(valid_styles)}", ephemeral=True)


    @add_type.autocomplete('button_style')
    async def button_style_autocomplete(self, interaction: discord.Interaction, current: str):
        styles = ['primary', 'secondary', 'success', 'danger']
        return [
            app_commands.Choice(name=style.capitalize(), value=style)
            for style in styles if current.lower() in style.lower()
        ][:25]


    @type_group.command(name="remove", description="Remove a ticket type.")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_type(self, interaction: discord.Interaction, internal_name: str):
        await interaction.response.defer(ephemeral=True)
        internal_name_clean = internal_name.lower().replace(" ", "-")
        
        success = await db_manager.remove_ticket_type(interaction.guild_id, internal_name_clean)
        if success:
            await interaction.followup.send(f"Ticket type with internal name `{internal_name_clean}` removed.", ephemeral=True)
        else:
            await interaction.followup.send(f"Ticket type with internal name `{internal_name_clean}` not found.", ephemeral=True)

    @remove_type.autocomplete('internal_name')
    async def remove_type_autocomplete(self, interaction: discord.Interaction, current: str):
        types = await db_manager.get_ticket_types(interaction.guild_id)
        return [
            app_commands.Choice(name=tt['display_name'] + f" ({tt['name']})", value=tt['name'])
            for tt in types if current.lower() in tt['name'].lower() or current.lower() in tt['display_name'].lower()
        ][:25]

    @type_group.command(name="list", description="List configured ticket types.")
    @app_commands.checks.has_permissions(manage_guild=True) # Staff might want to see this
    async def list_types(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        types = await db_manager.get_ticket_types(interaction.guild_id)
        if not types:
            await interaction.followup.send("No ticket types configured for this server.", ephemeral=True)
            return
        
        embed = discord.Embed(title="Configured Ticket Types", color=discord.Color.blue())
        for tt in types:
            desc = f"Display: {tt['display_name']}"
            if tt['description']: desc += f"\nDesc: {tt['description']}"
            if tt['emoji']: desc += f"\nEmoji: {tt['emoji']}"
            if tt['specific_staff_roles']:
                roles = json.loads(tt['specific_staff_roles'])
                role_mentions = [f"<@&{r}>" for r in roles]
                desc += f"\nStaff: {', '.join(role_mentions)}"
            embed.add_field(name=f"Internal Name: `{tt['name']}`", value=desc, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # Add more config commands: set_ticket_limit, set_naming_format, set_default_staff_roles etc.

async def setup(bot: commands.Bot):
    await bot.add_cog(ConfigCog(bot))
    print("ConfigCog Loaded")
