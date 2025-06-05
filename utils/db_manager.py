# utils/db_manager.py
import aiosqlite
import datetime
import json # For storing list of staff roles for ticket types

DATABASE_NAME = 'tickets.db'

async def initialize_database():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        # Guild configurations
        await db.execute('''
            CREATE TABLE IF NOT EXISTS guild_configs (
                guild_id INTEGER PRIMARY KEY,
                panel_channel_id INTEGER,
                panel_message_id INTEGER,
                ticket_channel_category_id INTEGER, -- Discord Category ID for tickets
                archive_channel_category_id INTEGER, -- Optional: Discord Category for closed tickets
                transcript_channel_id INTEGER,
                log_channel_id INTEGER, -- For staff notifications about new tickets
                default_staff_roles TEXT, -- JSON list of role IDs
                ticket_naming_format TEXT DEFAULT 'ticket-{user_short}-{id}', -- e.g. ticket-user-0001
                ticket_limit_per_user INTEGER DEFAULT 1,
                allow_user_close INTEGER DEFAULT 1, -- 0 for false, 1 for true
                ticket_counter INTEGER DEFAULT 0
            )
        ''')

        # Ticket Types (Departments/Categories)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS ticket_types (
                type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL, -- Internal name/key for the type
                display_name TEXT NOT NULL, -- Name shown on button/select
                description TEXT,
                emoji TEXT,
                button_style TEXT DEFAULT 'primary', -- 'primary', 'secondary', 'success', 'danger'
                welcome_message TEXT, -- Custom welcome message for this type
                specific_staff_roles TEXT, -- JSON list of role IDs for this type
                UNIQUE (guild_id, name),
                FOREIGN KEY (guild_id) REFERENCES guild_configs (guild_id)
            )
        ''')
        
        # Active and Closed Tickets
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_db_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                ticket_display_id INTEGER NOT NULL, -- Guild-specific sequential ID (e.g., #0001)
                user_id INTEGER NOT NULL,
                channel_id INTEGER UNIQUE NOT NULL,
                ticket_type_name TEXT NOT NULL, -- References 'name' from ticket_types
                status TEXT DEFAULT 'open', -- open, claimed, closed
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                claimed_by_staff_id INTEGER,
                closed_by_user_id INTEGER, -- Could be staff or original user if allowed
                closed_at TIMESTAMP,
                close_reason TEXT,
                transcript_message_id INTEGER, -- Message ID of the transcript in the transcript_channel
                FOREIGN KEY (guild_id) REFERENCES guild_configs (guild_id)
            )
        ''')
        await db.commit()
    print("Database initialized/checked.")

# --- Guild Config Functions ---
async def get_guild_config(guild_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row # Access columns by name
        async with db.execute("SELECT * FROM guild_configs WHERE guild_id = ?", (guild_id,)) as cursor:
            return await cursor.fetchone()

async def update_guild_config(guild_id: int, **kwargs):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        # Convert lists/dicts to JSON strings if they are part of kwargs
        for key, value in kwargs.items():
            if isinstance(value, (list, dict)):
                kwargs[key] = json.dumps(value)
        
        fields = ", ".join([f"{key} = ?" for key in kwargs])
        values = list(kwargs.values())
        
        # Upsert logic
        set_clause = ", ".join([f"{key} = excluded.{key}" for key in kwargs])
        columns = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * (len(kwargs) + 1)) # +1 for guild_id

        sql = f'''
            INSERT INTO guild_configs (guild_id, {columns}) 
            VALUES ({placeholders})
            ON CONFLICT(guild_id) DO UPDATE SET {fields}
        '''
        # For INSERT, values are (guild_id, val1, val2, ...)
        # For UPDATE, values are (val1, val2, ..., guild_id)
        insert_values = [guild_id] + list(kwargs.values())
        update_values = list(kwargs.values()) + [guild_id]

        await db.execute(sql, insert_values + update_values) # This needs refinement for SQLite upsert
        
        # Simpler upsert for SQLite:
        await db.execute(f'''
            INSERT OR REPLACE INTO guild_configs (guild_id, {columns})
            VALUES (?, {", ".join(["?"]*len(kwargs))})
        ''', (guild_id, *list(kwargs.values())))

        await db.commit()


async def get_and_increment_ticket_counter(guild_id: int) -> int:
    async with aiosqlite.connect(DATABASE_NAME) as db:
        # Ensure guild config exists
        async with db.execute("SELECT ticket_counter FROM guild_configs WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            if row is None: # First ticket for this guild, config might not be fully set
                await db.execute("INSERT OR IGNORE INTO guild_configs (guild_id, ticket_counter) VALUES (?, 0)", (guild_id,))
                await db.commit() # commit the insert before update
        
        await db.execute("UPDATE guild_configs SET ticket_counter = ticket_counter + 1 WHERE guild_id = ?", (guild_id,))
        await db.commit()
        async with db.execute("SELECT ticket_counter FROM guild_configs WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 1

# --- Ticket Type Functions ---
async def add_ticket_type(guild_id: int, name: str, display_name: str, description: str = None, emoji: str = None, button_style: str = 'primary', welcome_message: str = None, specific_staff_roles: list = None):
    roles_json = json.dumps(specific_staff_roles) if specific_staff_roles else None
    async with aiosqlite.connect(DATABASE_NAME) as db:
        try:
            await db.execute('''
                INSERT INTO ticket_types (guild_id, name, display_name, description, emoji, button_style, welcome_message, specific_staff_roles)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (guild_id, name.lower().replace(" ", "-"), display_name, description, emoji, button_style, welcome_message, roles_json))
            await db.commit()
            return True
        except aiosqlite.IntegrityError: # Unique constraint (guild_id, name)
            return False

async def get_ticket_types(guild_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ticket_types WHERE guild_id = ? ORDER BY display_name", (guild_id,)) as cursor:
            return await cursor.fetchall()

async def get_ticket_type_by_name(guild_id: int, name: str):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ticket_types WHERE guild_id = ? AND name = ?", (guild_id, name)) as cursor:
            return await cursor.fetchone()

async def remove_ticket_type(guild_id: int, name: str):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.execute("DELETE FROM ticket_types WHERE guild_id = ? AND name = ?", (guild_id, name))
        await db.commit()
        return cursor.rowcount > 0

# --- Ticket Functions ---
async def create_ticket(guild_id: int, user_id: int, channel_id: int, ticket_type_name: str, ticket_display_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute('''
            INSERT INTO tickets (guild_id, user_id, channel_id, ticket_type_name, ticket_display_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?)
        ''', (guild_id, user_id, channel_id, ticket_type_name, ticket_display_id, datetime.datetime.now(datetime.timezone.utc)))
        await db.commit()

async def get_ticket_by_channel(channel_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)) as cursor:
            return await cursor.fetchone()

async def get_open_tickets_by_user(guild_id: int, user_id: int):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status != 'closed'", (guild_id, user_id)) as cursor:
            return await cursor.fetchall()

async def update_ticket(channel_id: int, **kwargs):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        fields = ", ".join([f"{key} = ?" for key in kwargs])
        values = list(kwargs.values()) + [channel_id]
        await db.execute(f"UPDATE tickets SET {fields} WHERE channel_id = ?", values)
        await db.commit()
