import sqlite3
import click
from flask import current_app, g # g is a context global for flask requests
from flask.cli import with_appcontext
import logging # Use Flask's app.logger instead of global logging if possible within functions

# Helper to get the database connection
# Uses g to store the connection per request, ensuring it's reused if needed
# and closed automatically at the end of the request.
def get_db():
    if 'db' not in g:
        try:
            g.db = sqlite3.connect(
                current_app.config['DATABASE_URL'],
                detect_types=sqlite3.PARSE_DECLTYPES
            )
            g.db.row_factory = sqlite3.Row
            current_app.logger.debug("Database connection established.")
        except sqlite3.Error as e:
            current_app.logger.error(f"Error connecting to database: {e}")
            raise # Reraise the exception if connection fails
    return g.db

# Helper to close the database connection
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
        current_app.logger.debug("Database connection closed.")

# Function to initialize the database schema
# This is the original init_sqlite_db, adapted.
def init_db_schema():
    db = get_db()
    cursor = db.cursor()
    current_app.logger.info(f"Initializing SQLite database schema at {current_app.config['DATABASE_URL']}...")

    # prayer_candidates table (primary table)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prayer_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_name TEXT NOT NULL,
            post_label TEXT,
            country_code TEXT NOT NULL,
            party TEXT,
            thumbnail TEXT,
            status TEXT NOT NULL, -- 'queued', 'prayed'
            status_timestamp TIMESTAMP NOT NULL,
            initial_add_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- When first added from CSV
            hex_id TEXT -- For random allocation countries like Israel, Iran
        )
    ''')
    current_app.logger.info("Ensured prayer_candidates table exists with hex_id column.")
    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_unique
        ON prayer_candidates (person_name, post_label, country_code);
    ''')
    current_app.logger.info("Ensured idx_candidates_unique index exists on prayer_candidates table.")

    # Old tables (for migration reference, can be removed if migration is complete and verified)
    # These are kept here to show the full schema initialization if needed for a fresh start
    # or if migration logic depends on checking their existence.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prayer_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_name TEXT NOT NULL,
            post_label TEXT,
            country_code TEXT NOT NULL,
            party TEXT,
            thumbnail TEXT,
            added_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(person_name, post_label, country_code)
        )
    ''')
    current_app.logger.info("Ensured prayer_queue table (legacy) exists.")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prayed_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_name TEXT NOT NULL,
            post_label TEXT,
            country_code TEXT NOT NULL,
            party TEXT,
            thumbnail TEXT,
            prayed_timestamp TIMESTAMP NOT NULL
        )
    ''')
    current_app.logger.info("Ensured prayed_items table (legacy) exists.")
    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prayed_items_unique
        ON prayed_items (person_name, post_label, country_code);
    ''')
    current_app.logger.info("Ensured idx_prayed_items_unique index (legacy) exists on prayed_items table.")

    db.commit()
    current_app.logger.info("Successfully initialized/verified SQLite database schema.")


# CLI command to initialize the database
@click.command('init-db')
@with_appcontext
def init_db_command():
    """Clear existing data and create new tables."""
    # Check if tables exist, optionally drop them, then recreate
    # For simplicity, init_db_schema is idempotent (CREATE TABLE IF NOT EXISTS)
    # If you need to clear data, add DROP TABLE commands here.
    # For example:
    # db = get_db()
    # db.execute("DROP TABLE IF EXISTS prayer_candidates")
    # db.execute("DROP TABLE IF EXISTS prayer_queue")
    # db.execute("DROP TABLE IF EXISTS prayed_items")
    # db.commit()
    # current_app.logger.info("Dropped existing tables.")

    init_db_schema()
    click.echo('Initialized the database.')

# Function to register db commands with the Flask app
def init_app(app):
    # This ensures close_db is called after each request
    app.teardown_appcontext(close_db)
    # Add the init-db command to be callable via `flask init-db`
    app.cli.add_command(init_db_command)
    current_app.logger.info("Database module initialized with app.")

    # Initialize schema on app startup if DB file doesn't exist or is empty
    # This is a common pattern for simple apps.
    # More robust applications might require explicit migration commands.
    # try:
    #     with app.app_context(): # Need app context to access current_app.config and g
    #         # Simple check: if db file is very small, assume it's new or empty
    #         db_path = current_app.config['DATABASE_URL']
    #         # if not os.path.exists(db_path) or os.path.getsize(db_path) < 100: # Arbitrary small size
    #         # current_app.logger.info("Database appears new or empty, initializing schema.")
    #         init_db_schema() # This will create tables if they don't exist
    # except Exception as e:
    #    current_app.logger.error(f"Failed to auto-initialize DB schema on startup: {e}")
    # The schema initialization is now handled by data_initializer.initialize_application
    # to ensure correct order of operations (DB init, then migration, then data load).

# --- Data Access Functions (Examples, to be expanded) ---

def get_all_prayer_candidates_by_status(status='queued'):
    """Fetches all items from prayer_candidates table with a given status."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, person_name, post_label, country_code, party, thumbnail,
               initial_add_timestamp AS added_timestamp, hex_id, status_timestamp
        FROM prayer_candidates
        WHERE status = ?
        ORDER BY id ASC
    """, (status,))
    items = [dict(row) for row in cursor.fetchall()]
    current_app.logger.debug(f"Fetched {len(items)} items with status '{status}' from prayer_candidates.")
    return items

def get_candidate_by_id(candidate_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM prayer_candidates WHERE id = ?", (candidate_id,))
    row = cursor.fetchone()
    return dict(row) if row else None

def update_candidate_status(candidate_id, new_status, new_status_timestamp):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE prayer_candidates
        SET status = ?, status_timestamp = ?
        WHERE id = ?
    """, (new_status, new_status_timestamp, candidate_id))
    # For 'queued' to 'prayed', we might also want to ensure it was 'queued' before.
    # The original app.py did this in the SQL: WHERE id = ? AND status = 'queued'
    # This function is more generic, the service layer can enforce prior status.
    db.commit()
    return cursor.rowcount # Returns number of rows updated

def update_candidate_status_and_hex_id(candidate_id, new_status, new_status_timestamp, new_hex_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE prayer_candidates
        SET status = ?, status_timestamp = ?, hex_id = ?
        WHERE id = ?
    """, (new_status, new_status_timestamp, new_hex_id, candidate_id))
    db.commit()
    return cursor.rowcount

# Add more specific data access functions as needed...
# e.g., functions for inserting new candidates, deleting, fetching prayed items by country, etc.
# These will be used by the service layer.
# The migration logic will also use these or direct cursor executions.
