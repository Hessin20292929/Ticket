# bot.py
import discord
from discord.ext import commands
import os
import asyncio
from utils import db_manager # Relative import
from utils import views # Import views to ensure they are known for on_ready re-adding
from dotenv import load_dotenv

load_dotenv() 

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN environment variable not found.")
    exit()

# Intents
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 
intents.guilds = True

class SuperTicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned_or("t!"), intents=intents)
        self.initial_extensions = [
            "cogs.config_cog",
            "cogs.ticket_cog",
            "cogs.ticket_commands",
        ]
        # Store persistent views here if needed, or manage via cog_load/on_ready
        self.persistent_views_added = False


    async def setup_hook(self):
        print("Running setup_hook...")
        # Create utils directory if it doesn't exist (for users copying code)
        if not os.path.exists('utils'):
            os.makedirs('utils')
            print("Created 'utils' directory. Ensure db_manager.py and views.py are inside.")

        await db_manager.initialize_database()
        
        for extension in self.initial_extensions:
            try:
                await self.load_extension(extension)
                print(f"Successfully loaded extension: {extension}")
            except Exception as e:
                print(f"Failed to load extension {extension}.")
                print(f"[ERROR] {e}")
        
        # Register persistent views that were defined globally
        # This is crucial for buttons to work after bot restarts.
        if not self.persistent_views_added:
            self.add_view(views.TicketPanelView(self)) # Pass bot instance
            # TicketActionsView is more dynamic as it includes channel/user IDs in custom_id
            # Its callbacks are handled by on_interaction matching the custom_id pattern.
            # No need to explicitly re-add TicketActionsView instances here if custom_ids are structured well.
            self.persistent_views_added = True
            print("Persistent views registered.")


    async def on_ready(self):
        print(f'Logged in as {self.user.name} (ID: {self.user.id})')
        print(f'discord.py version: {discord.__version__}')
        print('------')
        print(f"Bot is ready and listening for commands with prefix 't!' or mention.")
        
        # Sync slash commands
        # It's better to do this in setup_hook after loading cogs,
        # but sometimes on_ready is used as a fallback or for testing specific guilds.
        # If already done in setup_hook, this might be redundant or cause issues if not handled carefully.
        # For now, let's assume setup_hook is the primary place for sync.
        # If you want to sync to a specific test guild:
        # TEST_GUILD_ID = 123456789012345678 # Replace with your guild ID
        # guild = discord.Object(id=TEST_GUILD_ID)
        # self.tree.copy_global_to(guild=guild)
        # await self.tree.sync(guild=guild)
        # print(f"Synced commands to test guild {TEST_GUILD_ID}")
        # Else, for global sync (can take up to an hour):
        try:
            if not hasattr(self, 'synced_commands_globally'): # Sync only once
                synced = await self.tree.sync()
                print(f"Synced {len(synced)} global application commands.")
                self.synced_commands_globally = True
        except Exception as e:
            print(f"Failed to sync global application commands: {e}")


bot_instance = SuperTicketBot()

async def main():
    # Create cogs directory if it doesn't exist
    if not os.path.exists('cogs'):
        os.makedirs('cogs')
        print("Created 'cogs' directory. Ensure cog files are inside.")

    # Placeholder cog files (users should replace these with the actual cog code)
    cog_files_to_create = {
        "config_cog.py": "# Placeholder for ConfigCog. See provided code.",
        "ticket_cog.py": "# Placeholder for TicketCog. See provided code.",
        "ticket_commands.py": "# Placeholder for TicketCommandsCog. See provided code."
    }
    for filename, placeholder_content in cog_files_to_create.items():
        filepath = os.path.join('cogs', filename)
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                f.write(placeholder_content + f"\n\nasync def setup(bot):\n    print(f'{filename} needs its Cog class and setup function implemented.')\n")
            print(f"Created placeholder cog: {filepath}. Please fill it with the provided code.")
            
    await bot_instance.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
