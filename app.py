from flask import Flask, render_template, jsonify, request, redirect, url_for
import pandas as pd
# import requests # No longer needed as fetch_csv reads local files
import sqlite3
import threading
import time
import queue as Queue
import logging
from datetime import datetime
import json
import sys
# from io import StringIO # No longer needed as fetch_csv reads local files
import numpy as np
import os
import random

from hex_map import load_hex_map, load_post_label_mapping, plot_hex_map_with_hearts
from utils import format_pretty_timestamp

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# Path for CSVs and other app-bundled data files (remains relative to app)
APP_DATA_DIR = os.path.join(APP_ROOT, 'data')

# Paths for persistent storage on Render disk mount
PERSISTENT_MOUNT_PATH = '/mnt/data'
PERSISTENT_DB_DIR = os.path.join(PERSISTENT_MOUNT_PATH, 'database') # Directory for the DB
PERSISTENT_LOG_DIR = os.path.join(PERSISTENT_MOUNT_PATH, 'logs')    # Directory for logs

DATABASE_URL = os.path.join(PERSISTENT_DB_DIR, 'queue.db')

# Create persistent directories if they don't exist
os.makedirs(PERSISTENT_DB_DIR, exist_ok=True)
os.makedirs(PERSISTENT_LOG_DIR, exist_ok=True)

# Configure logging
LOG_FILE_PATH = os.path.join(PERSISTENT_LOG_DIR, "app.log")
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler(LOG_FILE_PATH),
    logging.StreamHandler()
])

# Log path initializations
logging.info(f"APP_ROOT set to: {APP_ROOT}")
logging.info(f"APP_DATA_DIR (for CSVs, etc.) set to: {APP_DATA_DIR}")
logging.info(f"PERSISTENT_DB_DIR set to: {PERSISTENT_DB_DIR} (created if didn't exist).")
logging.info(f"PERSISTENT_LOG_DIR set to: {PERSISTENT_LOG_DIR} (created if didn't exist).")
logging.info(f"DATABASE_URL set to: {DATABASE_URL}")
logging.info(f"LOG_FILE_PATH set to: {LOG_FILE_PATH}")

app = Flask(__name__)

# Configuration
# CSV and GeoJSON paths should use APP_DATA_DIR as they are part of the deployed application files
COUNTRIES_CONFIG = {
    'israel': {
        'csv_path': os.path.join(APP_DATA_DIR, '20221101_israel.csv'),
        'geojson_path': os.path.join(APP_DATA_DIR, 'ISR_Parliament_120.geojson'),
        'map_shape_path': os.path.join(APP_DATA_DIR, 'ISR_Parliament_120.geojson'),
        'post_label_mapping_path': None,
        'total_representatives': 120,
        # 'log_file': os.path.join(LOG_DIR, 'prayed_for_israel.json'), # Removed
        'name': 'Israel',
        'flag': '🇮🇱'
    },
    'iran': {
        'csv_path': os.path.join(APP_DATA_DIR, '20240510_iran.csv'),
        'geojson_path': os.path.join(APP_DATA_DIR, 'IRN_IslamicParliamentofIran_290_v2.geojson'),
        'map_shape_path': os.path.join(APP_DATA_DIR, 'IRN_IslamicParliamentofIran_290_v2.geojson'),
        'post_label_mapping_path': None,
        'total_representatives': 290,
        # 'log_file': os.path.join(PERSISTENT_LOG_DIR, 'prayed_for_iran.json'), # Example if logs were per country & persistent
        'name': 'Iran',
        'flag': '🇮🇷'
    }
}
HEART_IMG_PATH = 'static/heart_icons/heart_red.png' # Path to the heart image for map plotting (remains global)

party_info = {
    'israel': {
        'Likud': {'short_name': 'Likud', 'color': '#00387A'},
        'Yesh Atid': {'short_name': 'Yesh Atid', 'color': '#ADD8E6'},
        'Shas': {'short_name': 'Shas', 'color': '#FFFF00'},
        'Resilience': {'short_name': 'Resilience', 'color': '#0000FF'},
        'Labor': {'short_name': 'Labor', 'color': '#FF0000'},
        'Other': {'short_name': 'Other', 'color': '#CCCCCC'}
    },
    'iran': {
        'Principlist': {'short_name': 'Principlist', 'color': '#006400'},
        'Reformists': {'short_name': 'Reformists', 'color': '#90EE90'},
        'Independent': {'short_name': 'Independent', 'color': '#808080'},
        'Other': {'short_name': 'Other', 'color': '#CCCCCC'}
    },
    # Note: Kosovo party_info is removed here, assuming it's not needed with the new structure
    # or should be added to COUNTRIES_CONFIG if Kosovo becomes a configured country.
    # For now, focusing on the provided 'israel' and 'iran' configs.
}

# data_queue = Queue.Queue() # Removed, SQLite is now used for queueing
# logging.info(f"Global data_queue object created with id: {id(data_queue)}") # Removed

# Global data structures
prayed_for_data = {country: [] for country in COUNTRIES_CONFIG.keys()} # Populated from DB at startup
# queued_entries_data = {country: set() for country in COUNTRIES_CONFIG.keys()} # Removed, this logic is implicitly handled by DB unique constraints or pre-checks
deputies_data = {
    country: {'with_images': [], 'without_images': []}
    for country in COUNTRIES_CONFIG.keys()
}
HEX_MAP_DATA_STORE = {}
POST_LABEL_MAPPINGS_STORE = {}

# Old global paths and direct loads are removed as they are now per-country
# heart_img_path remains global as specified.

def init_sqlite_db():
    """Initializes the SQLite database and creates the prayer_queue table."""
    logging.info(f"Initializing SQLite database at {DATABASE_URL}...")
    try:
        conn = sqlite3.connect(DATABASE_URL)
        cursor = conn.cursor()
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
        logging.info("Ensured prayer_queue table exists.")

        # Create prayed_items table
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
        logging.info("Ensured prayed_items table exists.")

        # Create unique index for prayed_items
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_prayed_items_unique
            ON prayed_items (person_name, post_label, country_code);
        ''')
        logging.info("Ensured idx_prayed_items_unique index exists on prayed_items table.")

        # Create prayer_candidates table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prayer_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_name TEXT NOT NULL,
                post_label TEXT,
                country_code TEXT NOT NULL,
                party TEXT,
                thumbnail TEXT,
                status TEXT NOT NULL,
                status_timestamp TIMESTAMP NOT NULL,
                initial_add_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hex_id TEXT
            )
        ''')
        logging.info("Ensured prayer_candidates table exists with hex_id column.")

        # Create unique index for prayer_candidates
        # No change to unique index, hex_id is not part of uniqueness constraint
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_unique
            ON prayer_candidates (person_name, post_label, country_code);
        ''')
        logging.info("Ensured idx_candidates_unique index exists on prayer_candidates table.")

        conn.commit()
        logging.info("Successfully initialized SQLite database tables and indexes.")
    except sqlite3.Error as e:
        logging.error(f"Error initializing SQLite database: {e}")
    finally:
        if conn:
            conn.close()

def migrate_to_single_table_schema():
    """Migrates data from old prayer_queue and prayed_items tables to the new prayer_candidates table."""
    logging.info("Starting migration to single table schema if conditions are met.")
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_URL)
        conn.row_factory = sqlite3.Row # To access columns by name
        cursor = conn.cursor()

        # 1. Check conditions for migration
        cursor.execute("SELECT COUNT(*) FROM prayer_candidates")
        candidates_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM prayer_queue")
        queue_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM prayed_items")
        prayed_count = cursor.fetchone()[0]

        if candidates_count > 0:
            logging.info(f"Prayer_candidates table is not empty (contains {candidates_count} items). Migration will not run.")
            return

        if queue_count == 0 and prayed_count == 0:
            logging.info("Both prayer_queue and prayed_items tables are empty. No data to migrate.")
            return

        logging.info(f"Conditions met for migration: prayer_candidates is empty and old tables have data (queue: {queue_count}, prayed: {prayed_count}).")

        # 2. Migrate from prayer_queue
        migrated_from_queue = 0
        if queue_count > 0:
            cursor.execute("SELECT person_name, post_label, country_code, party, thumbnail, added_timestamp FROM prayer_queue")
            queue_items = cursor.fetchall()
            for item in queue_items:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO prayer_candidates
                            (person_name, post_label, country_code, party, thumbnail, status, status_timestamp, initial_add_timestamp, hex_id)
                        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, NULL)
                    ''', (item['person_name'], item['post_label'], item['country_code'], item['party'], item['thumbnail'], item['added_timestamp'], item['added_timestamp']))
                    if cursor.rowcount > 0:
                        migrated_from_queue += 1
                except sqlite3.Error as e:
                    logging.error(f"Error migrating item {item['person_name']} from prayer_queue: {e}")
            logging.info(f"Migrated {migrated_from_queue} records from prayer_queue to prayer_candidates.")

        # 3. Migrate from prayed_items
        migrated_from_prayed = 0
        if prayed_count > 0:
            cursor.execute("SELECT person_name, post_label, country_code, party, thumbnail, prayed_timestamp FROM prayed_items")
            prayed_items_list = cursor.fetchall()
            for item in prayed_items_list:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO prayer_candidates
                            (person_name, post_label, country_code, party, thumbnail, status, status_timestamp, initial_add_timestamp, hex_id)
                        VALUES (?, ?, ?, ?, ?, 'prayed', ?, ?, NULL)
                    ''', (item['person_name'], item['post_label'], item['country_code'], item['party'], item['thumbnail'], item['prayed_timestamp'], item['prayed_timestamp']))
                    if cursor.rowcount > 0:
                        migrated_from_prayed += 1
                except sqlite3.Error as e:
                    logging.error(f"Error migrating item {item['person_name']} from prayed_items: {e}")
            logging.info(f"Migrated {migrated_from_prayed} records from prayed_items to prayer_candidates.")

        conn.commit()
        logging.info("Migration to single table schema completed successfully.")

    except sqlite3.Error as e:
        logging.error(f"SQLite error during migration to single table schema: {e}")
        if conn:
            conn.rollback()
    except Exception as e_main:
        logging.error(f"Unexpected error during migration to single table schema: {e_main}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def initialize_app_data():
    # The content from the existing `if __name__ == '__main__':` block's loop
    # and the thread starting line will go here.
    init_sqlite_db() # Initialize SQLite database
    migrate_to_single_table_schema() # Migrate to new schema if needed
    migrate_json_logs_to_db() # Migrate old JSON logs if prayed_items table is empty
    load_prayed_for_data_from_db() # Load all prayed for data from DB into memory
    logging.debug("Starting application data initialization...") # Changed from INFO to DEBUG

    # Loop for deputies_data, HEX_MAP_DATA_STORE, POST_LABEL_MAPPINGS_STORE initialization
    for country_code_init in COUNTRIES_CONFIG.keys():
        logging.debug(f"Initializing non-log data for country: {country_code_init}") # Changed from INFO to DEBUG
        logging.debug(f"Using CSV path: {COUNTRIES_CONFIG[country_code_init]['csv_path']}") # Changed from INFO to DEBUG
        logging.debug(f"Using GeoJSON path: {COUNTRIES_CONFIG[country_code_init]['geojson_path']}") # Changed from INFO to DEBUG
        # The specific log line for 'log_file' path has been removed.

        # Fetch and process CSV data for deputies
        df_init = fetch_csv(country_code_init)
        if not df_init.empty:
            process_deputies(df_init, country_code_init) # process_deputies logs
            logging.debug(f"Processed deputies for {country_code_init}: {len(deputies_data[country_code_init]['with_images'])} with images, {len(deputies_data[country_code_init]['without_images'])} without.") # Changed from INFO to DEBUG
        else:
            logging.warning(f"CSV data for {country_code_init} was empty. No deputies processed.")

        # Load map shape data
        map_path = COUNTRIES_CONFIG[country_code_init]['map_shape_path']
        if os.path.exists(map_path):
            if country_code_init in ['israel', 'iran']:
                logging.debug(f"Attempting to load hex map for specific country: {country_code_init} from {map_path}") # Changed from INFO to DEBUG

            HEX_MAP_DATA_STORE[country_code_init] = load_hex_map(map_path)

            if country_code_init in ['israel', 'iran']:
                if HEX_MAP_DATA_STORE[country_code_init] is None:
                    logging.error(f"Critical Failure: Map data loading returned None for {country_code_init}.")
                elif HEX_MAP_DATA_STORE[country_code_init].empty:
                    logging.warning(f"Warning: Loaded map data for {country_code_init} is an empty GeoDataFrame.")
                else:
                    logging.info(f"Success: Loaded hex map for {country_code_init} with {len(HEX_MAP_DATA_STORE[country_code_init])} features.")
            else: # Fallback to generic logging for other countries
                if HEX_MAP_DATA_STORE[country_code_init] is not None and not HEX_MAP_DATA_STORE[country_code_init].empty:
                    logging.info(f"Successfully loaded hex map for {country_code_init} with {len(HEX_MAP_DATA_STORE[country_code_init])} features.")
                elif HEX_MAP_DATA_STORE[country_code_init] is not None and HEX_MAP_DATA_STORE[country_code_init].empty:
                    logging.warning(f"Loaded hex map for {country_code_init} is empty.")
                else:
                    logging.error(f"Failed to load hex map for {country_code_init} (it's None).")
        else:
            logging.error(f"Map file not found: {map_path} for country {country_code_init}")
            HEX_MAP_DATA_STORE[country_code_init] = None

        # Load post label mapping data
        post_label_path = COUNTRIES_CONFIG[country_code_init].get('post_label_mapping_path')
        if post_label_path and os.path.exists(post_label_path):
            POST_LABEL_MAPPINGS_STORE[country_code_init] = load_post_label_mapping(post_label_path)
        elif post_label_path:
            logging.error(f"Post label mapping file not found: {post_label_path} for country {country_code_init}")
            POST_LABEL_MAPPINGS_STORE[country_code_init] = pd.DataFrame()
        else: # No path specified (e.g., for Israel, Iran)
            logging.debug(f"No post label mapping file specified for country {country_code_init}. Assigning empty DataFrame.") # Changed from INFO to DEBUG
            POST_LABEL_MAPPINGS_STORE[country_code_init] = pd.DataFrame() # Ensure empty DataFrame is assigned

        # Logging for post_label_mapping results
        if POST_LABEL_MAPPINGS_STORE.get(country_code_init) is not None and not POST_LABEL_MAPPINGS_STORE[country_code_init].empty:
            logging.info(f"Successfully loaded post label mapping for {country_code_init} with {len(POST_LABEL_MAPPINGS_STORE[country_code_init])} entries.")
        elif POST_LABEL_MAPPINGS_STORE.get(country_code_init) is not None and POST_LABEL_MAPPINGS_STORE[country_code_init].empty:
            logging.warning(f"Loaded post label mapping for {country_code_init} is empty (this may be normal).")
        # No else needed as it's initialized to empty DataFrame

    logging.debug("Application data initialization complete.") # Changed from INFO to DEBUG

    # Start the queue updating thread
    # logging.info("Starting the update_queue background thread.") # Kept as INFO
    # threading.Thread(target=update_queue, daemon=True).start()

def migrate_json_logs_to_db():
    """Migrates data from old JSON log files to the prayed_items SQLite table if the table is empty."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Check if prayed_items table is empty
        cursor.execute("SELECT COUNT(*) FROM prayed_items")
        count = cursor.fetchone()[0]

        if count == 0:
            logging.info("prayed_items table is empty. Starting migration from JSON logs...")
            total_migrated_count = 0
            for country_code, config in COUNTRIES_CONFIG.items():
                # log_file_path = config['log_file'] # 'log_file' is removed from config
                # Construct path if needed for migration, or assume path structure if fixed
                # For this migration, we assume the old log files are still discoverable via a pattern
                # or that the 'log_file' key might temporarily exist in an older config version.
                # For now, let's assume 'log_file' key is gone and we need to reconstruct path or skip.
                # Safest is to check if 'log_file' key exists for migration robustness.
                log_file_path = config.get('log_file')
                if not log_file_path:
                    logging.warning(f"No 'log_file' configured for {country_code} in COUNTRIES_CONFIG. Skipping migration for this country.")
                    continue

                country_migrated_count = 0
                if os.path.exists(log_file_path):
                    try:
                        with open(log_file_path, 'r') as f:
                            items_from_log = json.load(f)

                        for item in items_from_log:
                            person_name = item.get('person_name')
                            # Use original post_label, can be None. DB schema allows NULL.
                            post_label = item.get('post_label')
                            # Ensure country_code is present, fallback to current loop's country_code
                            item_country_code = item.get('country_code', country_code)
                            party = item.get('party')
                            thumbnail = item.get('thumbnail')
                            prayed_timestamp = item.get('timestamp') # This is the crucial field

                            if person_name and item_country_code and prayed_timestamp: # Required fields
                                cursor.execute('''
                                    INSERT OR IGNORE INTO prayed_items
                                        (person_name, post_label, country_code, party, thumbnail, prayed_timestamp)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                ''', (person_name, post_label, item_country_code, party, thumbnail, prayed_timestamp))
                                # Check if a row was actually inserted (not ignored)
                                if cursor.rowcount > 0:
                                    country_migrated_count +=1
                            else:
                                logging.warning(f"Skipping item due to missing data during migration: {item} from {log_file_path}")

                        conn.commit()
                        logging.info(f"Migrated {country_migrated_count} items from {log_file_path} for country {country_code}.")
                        total_migrated_count += country_migrated_count
                    except json.JSONDecodeError:
                        logging.error(f"Error decoding JSON from {log_file_path}. Skipping migration for this file.")
                    except Exception as e_file:
                        logging.error(f"Error processing file {log_file_path}: {e_file}")
                else:
                    logging.info(f"Log file not found: {log_file_path}. No items to migrate for {country_code}.")

            if total_migrated_count > 0:
                logging.info(f"Total items migrated from JSON logs to prayed_items table: {total_migrated_count}.")
            else:
                logging.info("No items were migrated from JSON logs (either files were empty, not found, or items already existed).")
        else:
            logging.info(f"prayed_items table is not empty (contains {count} items). Migration from JSON logs skipped.")

    except sqlite3.Error as e:
        logging.error(f"SQLite error during migration: {e}")
        if conn: # Rollback if there was an error during the transaction for a file
            conn.rollback()
    except Exception as e_main:
        logging.error(f"Unexpected error during migration: {e_main}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def get_current_queue_items_from_db():
    """Fetches all items from the prayer_queue table, ordered by timestamp."""
    items = []
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_URL)
        conn.row_factory = sqlite3.Row # Access columns by name
        cursor = conn.cursor()
        # Select from prayer_candidates with status 'queued'
        cursor.execute("""
            SELECT id, person_name, post_label, country_code, party, thumbnail, initial_add_timestamp AS added_timestamp, hex_id
            FROM prayer_candidates
            WHERE status = 'queued'
            ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        for row in rows:
            items.append(dict(row))
        logging.info(f"Fetched {len(items)} items with status 'queued' from prayer_candidates.")
    except sqlite3.Error as e:
        logging.error(f"SQLite error in get_current_queue_items_from_db: {e}")
    except Exception as e_gen:
        logging.error(f"Unexpected error in get_current_queue_items_from_db: {e_gen}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return items

# Function to fetch the CSV
def fetch_csv(country_code):
    logging.debug(f"Fetching CSV data for {country_code}") # Changed from INFO to DEBUG
    csv_path = COUNTRIES_CONFIG[country_code]['csv_path']
    try:
        df = pd.read_csv(csv_path)
        logging.debug(f"Successfully fetched {len(df)} rows from {csv_path}") # Changed from INFO to DEBUG
        df = df.replace({np.nan: None})
        logging.debug(f"Fetched data for {country_code}: {df.head()}") # Kept as DEBUG
        return df
    except FileNotFoundError:
        logging.error(f"CSV file not found for {country_code} at {csv_path}")
        return pd.DataFrame()

# Process each entry to determine if an image is available
def process_deputies(csv_data, country_code):
    country_deputies_with_images = []
    country_deputies_without_images = []
    for index, row in csv_data.iterrows():
        image_url = row.get('image_url')
        processed_row = row.to_dict()
        if not image_url:
            # logging.debug(f"No image URL for {row.get('person_name')} ({country_code}) at index {index}") # Removed as per subtask
            country_deputies_without_images.append(processed_row)
            continue
        processed_row['Image'] = image_url
        country_deputies_with_images.append(processed_row)
        logging.debug(f"Image URL assigned for {row.get('person_name')} ({country_code}): {image_url}")
    deputies_data[country_code]['with_images'] = country_deputies_with_images
    deputies_data[country_code]['without_images'] = country_deputies_without_images
    if country_deputies_without_images:
        logging.info(f"No images found for the following names in {country_code}: {', '.join([dep.get('person_name', 'N/A') for dep in country_deputies_without_images])}")

# Removed old global csv_data, deputies_with_images, deputies_without_images,
# and their initial loading/processing. This is now handled in the
# __main__ block or by specific calls.

# Function to periodically update the queue
def update_queue():
    with app.app_context():
        logging.info("Update_queue function execution started.") # Changed log message slightly for clarity
        conn = None
        try:
            logging.info("[update_queue] Attempting to connect to DB.") # Kept original log
            conn = sqlite3.connect(DATABASE_URL)
            conn.row_factory = sqlite3.Row # <--- ADD THIS LINE
            cursor = conn.cursor()

            # PREEMPTIVELY DELETE EXISTING 'QUEUED' ITEMS
            logging.info("[update_queue] Deleting existing 'queued' items from prayer_candidates table before repopulation.")
            cursor.execute("DELETE FROM prayer_candidates WHERE status = 'queued'")
            # conn.commit() # Commit this delete immediately
            # logging.info(f"[update_queue] Deleted {cursor.rowcount} existing 'queued' items.")
            # Decided to commit at the end of all operations or if items_added_to_db_this_cycle > 0.
            # If the function errors out before insertions, this delete might be rolled back if not committed here.
            # For safety and clarity of this step, let's commit the delete separately.
            conn.commit()
            logging.info(f"[update_queue] Committed deletion of existing 'queued' items. Rows affected: {cursor.rowcount}")


            # Check if prayer_candidates has any entries at all.
            # If it does, assume seeding/migration has occurred.
            # cursor.execute("SELECT COUNT(id) FROM prayer_candidates")
            # count = cursor.fetchone()[0]
            # logging.info(f"[update_queue] Current count in prayer_candidates table: {count}")

            # if count > 0:
            #     logging.info(f"[update_queue] prayer_candidates is not empty (count: {count}). Seeding will be skipped.")
            #     return

            # logging.info("[update_queue] prayer_candidates is empty. Proceeding with initial data population from CSVs.")
            # If table is empty, proceed with the existing logic to populate prayer_candidates with 'queued' items.
            # The above check is removed to allow update_queue to always run fully.
            logging.info("[update_queue] Proceeding with data population from CSVs.")

            # Fetch identifiers of already prayed individuals
            cursor.execute("SELECT person_name, post_label, country_code FROM prayer_candidates WHERE status = 'prayed'")
            already_prayed_records = cursor.fetchall()
            already_prayed_ids = set()
            for record in already_prayed_records:
                # Normalize post_label for consistent set storage and lookup: use empty string if None
                pn = record['person_name']
                pl = record['post_label'] if record['post_label'] is not None else "" # Match how it might be checked later
                cc = record['country_code']
                already_prayed_ids.add((pn, pl, cc))
            logging.info(f"[update_queue] Found {len(already_prayed_ids)} individuals already marked as 'prayed'.")

            all_potential_candidates = []
            # Phase 1: Collect all potential candidates from all countries
            for country_code_collect in COUNTRIES_CONFIG.keys():
                df_raw = fetch_csv(country_code_collect) # Renamed to df_raw
                if df_raw.empty:
                    logging.warning(f"CSV data for {country_code_collect} is empty. Skipping for initial seeding.") # Changed to warning
                    continue

                # Get the number of representatives to select for this country
                num_to_select = COUNTRIES_CONFIG[country_code_collect].get('total_representatives')
                if num_to_select is None:
                    logging.warning(f"'total_representatives' not configured for {country_code_collect}. Using all entries from CSV.")
                    df_sampled = df_raw.sample(frac=1).reset_index(drop=True) # Shuffle all if no cap
                elif len(df_raw) > num_to_select:
                    logging.info(f"CSV for {country_code_collect} has {len(df_raw)} entries, selecting {num_to_select} randomly (before filtering prayed).")
                    df_sampled = df_raw.sample(n=num_to_select).reset_index(drop=True)
                else:
                    logging.info(f"CSV for {country_code_collect} has {len(df_raw)} entries (<= {num_to_select}). Taking all and shuffling (before filtering prayed).")
                    df_sampled = df_raw.sample(frac=1).reset_index(drop=True) # Shuffle all if fewer than cap

                logging.info(f"Selected {len(df_sampled)} individuals from {country_code_collect} CSV (before filtering prayed).")

                for index, row in df_sampled.iterrows(): # Iterate over the (potentially) sampled DataFrame
                    if row.get('person_name'):
                        item = row.to_dict()
                        item['country_code'] = country_code_collect
                        if not item.get('party'): # Standardize party
                            item['party'] = 'Other'

                        # Prepare for already_prayed_ids check
                        current_person_name = item['person_name']
                        current_post_label_raw = item.get('post_label')

                        # Normalize post_label from CSV item for comparison with already_prayed_ids keys
                        if isinstance(current_post_label_raw, str) and not current_post_label_raw.strip():
                            post_label_for_check = ""
                        elif current_post_label_raw is None:
                            post_label_for_check = ""
                        else:
                            post_label_for_check = current_post_label_raw # Keep original potentially unstripped for check if that's how it's stored
                                                                        # The key is consistency with how already_prayed_ids are created.
                                                                        # already_prayed_ids uses `pl if pl is not None else ""`. So this should match.

                        candidate_id_tuple = (current_person_name, post_label_for_check, item['country_code'])

                        if candidate_id_tuple not in already_prayed_ids:
                            # Standardize item['post_label'] for DB storage (applies if it's added to queue)
                            if isinstance(current_post_label_raw, str) and not current_post_label_raw.strip():
                                item['post_label'] = None
                            elif current_post_label_raw is None:
                                item['post_label'] = None
                            # Else: item['post_label'] is already the correct string from current_post_label_raw via to_dict()

                            image_url = item.get('image_url', HEART_IMG_PATH) # HEART_IMG_PATH is a global
                            if not image_url: # Ensure thumbnail is never empty if image_url was empty string
                                image_url = HEART_IMG_PATH
                            item['thumbnail'] = image_url
                            all_potential_candidates.append(item)
                        else:
                            logging.debug(f"[update_queue] Skipped {candidate_id_tuple} from CSV for {country_code_collect}; already prayed for.")
                    else:
                        logging.debug(f"Skipped entry due to missing person_name for {country_code_collect} at index {index} in sampled data: {row.to_dict()}")

            logging.info(f"[update_queue] Collected {len(all_potential_candidates)} new potential candidates after filtering out prayed ones.") # Updated log
            random.shuffle(all_potential_candidates)
            # logging.info(f"[update_queue] Collected {len(all_potential_candidates)} total potential new candidates from CSVs for initial seeding.") # Old log, replaced by above

            items_added_to_db_this_cycle = 0
            # Connection is already established and cursor is available

            # Prepare available hex IDs for random allocation countries
            available_hex_ids_by_country = {}
            random_allocation_countries = ['israel', 'iran'] # Define these, or get from config if more dynamic

            for country_code_hex_prep in random_allocation_countries:
                if country_code_hex_prep not in COUNTRIES_CONFIG:
                    continue # Skip if country not configured

                hex_map_gdf_prep = HEX_MAP_DATA_STORE.get(country_code_hex_prep)
                if hex_map_gdf_prep is not None and not hex_map_gdf_prep.empty and 'id' in hex_map_gdf_prep.columns:
                    all_map_hex_ids = set(hex_map_gdf_prep['id'].unique())

                    # Fetch used hex_ids from DB for this country
                    cursor.execute("""
                        SELECT hex_id FROM prayer_candidates
                        WHERE country_code = ? AND hex_id IS NOT NULL AND (status = 'prayed' OR status = 'queued')
                    """, (country_code_hex_prep,))
                    used_hex_ids_rows = cursor.fetchall()
                    used_hex_ids = {row['hex_id'] for row in used_hex_ids_rows}

                    current_available_hex_ids = list(all_map_hex_ids - used_hex_ids)
                    random.shuffle(current_available_hex_ids) # Shuffle for random assignment
                    available_hex_ids_by_country[country_code_hex_prep] = current_available_hex_ids
                    logging.info(f"[update_queue] For {country_code_hex_prep}: {len(all_map_hex_ids)} total map hexes, {len(used_hex_ids)} used, {len(current_available_hex_ids)} available for assignment.")
                else:
                    logging.warning(f"[update_queue] Hex map data or 'id' column not available for {country_code_hex_prep}. Cannot prepare available hex IDs.")
                    available_hex_ids_by_country[country_code_hex_prep] = []

            # Assign hex_id to items before adding to DB
            for item_to_process_for_hex in all_potential_candidates:
                item_country_code = item_to_process_for_hex['country_code']
                item_to_process_for_hex['hex_id'] = None # Default to None

                if item_country_code in random_allocation_countries:
                    if available_hex_ids_by_country.get(item_country_code): # Check if list exists and is not empty
                        assigned_hex_id = available_hex_ids_by_country[item_country_code].pop()
                        item_to_process_for_hex['hex_id'] = assigned_hex_id
                        logging.debug(f"[update_queue] Assigned hex_id {assigned_hex_id} to {item_to_process_for_hex['person_name']} for {item_country_code}")
                    else:
                        logging.warning(f"[update_queue] No available hex_ids to assign for {item_to_process_for_hex['person_name']} in {item_country_code}. Map might be full or data missing.")

            # Now, insert items with their assigned hex_ids (or None)
            for item_to_add in all_potential_candidates:
                person_name = item_to_add['person_name']
                post_label = item_to_add['post_label']
                country_code_add = item_to_add['country_code']
                party_add = item_to_add['party']
                thumbnail_add = item_to_add['thumbnail']
                hex_id_to_insert = item_to_add.get('hex_id') # Get the assigned hex_id

                current_ts_for_status = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                # ADDING DIAGNOSTIC LOGGING HERE
                logging.debug(f"[update_queue] Preparing to insert: Name='{person_name}', Country='{country_code_add}', HexID='{hex_id_to_insert}', PostLabel='{post_label}', Party='{party_add}'")
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO prayer_candidates
                            (person_name, post_label, country_code, party, thumbnail, status, status_timestamp, hex_id)
                        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
                    ''', (person_name, post_label if post_label else None, country_code_add, party_add, thumbnail_add, current_ts_for_status, hex_id_to_insert))
                    if cursor.rowcount > 0:
                        items_added_to_db_this_cycle += 1
                except sqlite3.Error as e_insert:
                    logging.error(f"SQLite error during initial seeding into prayer_candidates for {person_name} ({post_label}): {e_insert}")

            if items_added_to_db_this_cycle > 0:
                conn.commit() # Commit all successful inserts
                logging.info(f"[update_queue] Database commit successful for {items_added_to_db_this_cycle} items.")
                logging.info(f"[update_queue] Successfully inserted {items_added_to_db_this_cycle} new items into prayer_candidates during this seeding cycle.")
            # Log even if 0 items were added, to confirm the loop completed.
            logging.info(f"[update_queue] Attempted to insert candidates. Number of rows affected in this batch: {items_added_to_db_this_cycle}")


            current_db_candidates_size = 0 # Renamed variable
            cursor.execute("SELECT COUNT(id) FROM prayer_candidates WHERE status = 'queued'") # Check only 'queued'
            count_result = cursor.fetchone()
            if count_result:
                current_db_candidates_size = count_result[0]
            logging.info(f"Initial seeding process complete. Current 'queued' items in prayer_candidates: {current_db_candidates_size}")

        except Exception as e: # General exception
            logging.error(f"[update_queue] An critical error occurred during execution: {e}", exc_info=True)
            if conn: # Rollback if error occurred during transaction
                conn.rollback()
        finally:
            logging.info("[update_queue] Reached finally block, will close connection if open.")
            if conn:
                conn.close()
                logging.debug("SQLite connection closed in update_queue.")
        # The while True loop and time.sleep(90) are removed.

@app.route('/about')
def about_page():
    """Renders the about page."""
    logging.info("Serving about page from app.py")
    # This mirrors the about_page from project/blueprints/main.py
    # Ensure templates/about.html exists and is appropriate.
    now = datetime.now()
    return render_template('about.html', now=now)

def load_prayed_for_data_from_db():
    """Loads all prayed-for items from the SQLite database into the global prayed_for_data."""
    global prayed_for_data
    # Clear existing in-memory data first
    for country in COUNTRIES_CONFIG.keys():
        prayed_for_data[country] = []

    conn = None
    try:
        conn = sqlite3.connect(DATABASE_URL)
        conn.row_factory = sqlite3.Row # Access columns by name
        cursor = conn.cursor()
        # Select from prayer_candidates with status 'prayed'
        cursor.execute("""
            SELECT person_name, post_label, country_code, party, thumbnail, status_timestamp AS timestamp, hex_id
            FROM prayer_candidates
            WHERE status = 'prayed'
        """)
        rows = cursor.fetchall()
        loaded_count = 0
        for row_data in rows:
            item = dict(row_data) # This will now include hex_id if it was selected
            # 'timestamp' is already aliased from status_timestamp in the query
            country_code_load = item.get('country_code') # Renamed variable
            if country_code_load in prayed_for_data:
                prayed_for_data[country_code_load].append(item) # item now contains hex_id
                loaded_count +=1
            else:
                logging.warning(f"Found item in prayer_candidates (status='prayed') with unknown country_code: {country_code_load} - Item: {item.get('person_name')}")

        logging.info(f"Loaded {loaded_count} items with status 'prayed' from prayer_candidates into memory.")
        for country_code_key in prayed_for_data: # Use a different variable name
             logging.debug(f"Country {country_code_key} has {len(prayed_for_data[country_code_key])} prayed items in memory after DB load from prayer_candidates.")

    except sqlite3.Error as e:
        logging.error(f"SQLite error in load_prayed_for_data_from_db (reading prayer_candidates): {e}")
    except Exception as e_gen:
        logging.error(f"Unexpected error in load_prayed_for_data_from_db: {e_gen}", exc_info=True)
    finally:
        if conn:
            conn.close()

def reload_single_country_prayed_data_from_db(country_code_to_reload):
    global prayed_for_data
    if country_code_to_reload not in prayed_for_data:
        logging.warning(f"[reload_single_country_prayed_data_from_db] Invalid country_code: {country_code_to_reload}")
        return

    logging.info(f"[reload_single_country_prayed_data_from_db] Reloading prayed_for_data for country: {country_code_to_reload}")
    prayed_for_data[country_code_to_reload] = [] # Clear current list for this country

    conn_reload = None
    try:
        conn_reload = sqlite3.connect(DATABASE_URL)
        conn_reload.row_factory = sqlite3.Row
        cursor_reload = conn_reload.cursor()

        # Select from prayer_candidates with status 'prayed' for the specific country
        cursor_reload.execute("""
            SELECT person_name, post_label, country_code, party, thumbnail, status_timestamp AS timestamp, hex_id
            FROM prayer_candidates
            WHERE status = 'prayed' AND country_code = ?
        """, (country_code_to_reload,))

        rows = cursor_reload.fetchall()
        loaded_count = 0
        for row_data in rows:
            item = dict(row_data) # This will now include hex_id
            # 'timestamp' is already aliased from status_timestamp
            prayed_for_data[country_code_to_reload].append(item) # item now contains hex_id
            loaded_count += 1
        logging.info(f"[reload_single_country_prayed_data_from_db] Reloaded {loaded_count} 'prayed' items for {country_code_to_reload} from prayer_candidates into prayed_for_data.")

    except sqlite3.Error as e:
        logging.error(f"[reload_single_country_prayed_data_from_db] SQLite error for {country_code_to_reload} (reading prayer_candidates): {e}")
    except Exception as e_gen:
        logging.error(f"[reload_single_country_prayed_data_from_db] Unexpected error for {country_code_to_reload}: {e_gen}", exc_info=True)
    finally:
        if conn_reload:
            conn_reload.close()

@app.route('/')
def home():
    load_prayed_for_data_from_db() # <--- THIS LINE WAS ALREADY ADDED
    total_prayed_count_in_memory = sum(len(prayed_list) for prayed_list in prayed_for_data.values())
    logging.info(f"[home] After load_prayed_for_data_from_db(), total prayed items in memory: {total_prayed_count_in_memory}.")
    # For more detail (optional, can be verbose):
    # for c_code, data_list in prayed_for_data.items():
    #     if data_list: # Only log if there are items
    #         logging.debug(f"[home] Prayed data for {c_code} (first 1 if any): {data_list[:1]}")
    total_all_countries = sum(cfg['total_representatives'] for cfg in COUNTRIES_CONFIG.values())
    total_prayed_for_all_countries = sum(len(prayed_for_data[country]) for country in COUNTRIES_CONFIG.keys())
    current_remaining = total_all_countries - total_prayed_for_all_countries

    current_queue_items = get_current_queue_items_from_db()
    current_item_display = current_queue_items[0] if current_queue_items else None

    # Updated logging for home page
    queue_size = len(current_queue_items)
    current_person_name = current_item_display['person_name'] if current_item_display else "None"
    logging.info(f"Home page: SQLite queue size: {queue_size}. Current item for display: {current_person_name}")

    map_to_display_country = list(COUNTRIES_CONFIG.keys())[0] # Default to first country
    if current_item_display:
        map_to_display_country = current_item_display.get('country_code', map_to_display_country)

    # ==== DETAILED LOGGING START ====
    logging.debug(f"[home] map_to_display_country determined as: {map_to_display_country}") # Changed from INFO to DEBUG
    if map_to_display_country in prayed_for_data:
        logging.debug(f"[home] Size of prayed_for_data['{map_to_display_country}']: {len(prayed_for_data[map_to_display_country])}") # Changed from INFO to DEBUG
    else:
        logging.warning(f"[home] map_to_display_country '{map_to_display_country}' not found in prayed_for_data keys.")
    logging.debug(f"[home] Number of current_queue_items being passed to plot_hex_map_with_hearts: {len(current_queue_items)}") # Changed from INFO to DEBUG
    # ==== DETAILED LOGGING END ====

    # load_prayed_for_data_from_db() is called at startup.
    # If specific routes need to refresh this from DB, they could call it,
    # but for now, relying on initial load.
    # The map plotting uses the in-memory prayed_for_data which is populated from DB at start.
    # No need to call read_log() here anymore.

    hex_map_gdf = HEX_MAP_DATA_STORE.get(map_to_display_country)
    post_label_df = POST_LABEL_MAPPINGS_STORE.get(map_to_display_country)
    logging.debug(f"Rendering home page. Map for country: {map_to_display_country}") # Changed from INFO to DEBUG
    if hex_map_gdf is not None and not hex_map_gdf.empty:
        logging.debug(f"Hex map data for {map_to_display_country} is available for plotting.") # Changed from INFO to DEBUG
    else:
        logging.warning(f"Hex map data for {map_to_display_country} is MISSING or empty. Plotting may fail or show default.")
    if post_label_df is not None and not post_label_df.empty:
        logging.debug(f"Post label mapping for {map_to_display_country} is available.") # Changed from INFO to DEBUG
    else:
        logging.warning(f"Post label mapping for {map_to_display_country} is MISSING or empty (may be normal for random allocation).") # Kept as WARNING
    if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None:
        # Pass the list of prayed items for the country, the global queue, and the country code
        plot_hex_map_with_hearts(
            hex_map_gdf, # Use the fetched GeoDataFrame
            POST_LABEL_MAPPINGS_STORE[map_to_display_country],
            prayed_for_data[map_to_display_country],
            current_queue_items, # Pass items from SQLite
            map_to_display_country
        )
    else:
        logging.warning(f"Cannot plot initial map for {map_to_display_country}. Data missing.")

    display_deputies_with_images = deputies_data.get(map_to_display_country, {}).get('with_images', [])
    display_deputies_without_images = deputies_data.get(map_to_display_country, {}).get('without_images', [])

    default_country_code = list(COUNTRIES_CONFIG.keys())[0] if COUNTRIES_CONFIG else None

    return render_template('index.html',
                           remaining=current_remaining,
                           current=current_item_display, #This is the first item from DB queue
                           queue=current_queue_items, #This is the full DB queue
                           deputies_with_images=display_deputies_with_images,
                           deputies_without_images=display_deputies_without_images,
                           current_country_name=COUNTRIES_CONFIG[map_to_display_country]['name'],
                           all_countries=COUNTRIES_CONFIG, # Pass all country configs
                           default_country_code=default_country_code, # Pass default country code for links
                           initial_map_country_code=map_to_display_country # Pass current map country for JS
                           )

@app.route('/generate_map_for_country/<country_code>')
def generate_map_for_country(country_code):
    # ==== DETAILED LOGGING START ====
    logging.debug(f"[generate_map_for_country] Received country_code: {country_code}") # Changed from INFO to DEBUG
    # ==== DETAILED LOGGING END ====
    if country_code not in COUNTRIES_CONFIG:
        logging.error(f"Invalid country code '{country_code}' for map generation.")
        return jsonify(error='Invalid country code'), 404

    # load_prayed_for_data_from_db() is called at startup.
    # No need to call read_log() here anymore.

    hex_map_gdf = HEX_MAP_DATA_STORE.get(country_code)
    post_label_df = POST_LABEL_MAPPINGS_STORE.get(country_code)
    prayed_list_for_map = prayed_for_data.get(country_code, [])
    current_queue_for_map = get_current_queue_items_from_db() # Get queue from DB

    # ==== DETAILED LOGGING START ====
    logging.debug(f"[generate_map_for_country] Size of prayed_list_for_map for '{country_code}': {len(prayed_list_for_map)}") # Changed from INFO to DEBUG
    logging.debug(f"[generate_map_for_country] Size of current_queue_for_map for '{country_code}': {len(current_queue_for_map)}") # Changed from INFO to DEBUG
    # ==== DETAILED LOGGING END ====

    if hex_map_gdf is None or hex_map_gdf.empty : # Check for None or empty GeoDataFrame
        logging.error(f"Map data (GeoDataFrame) not available for {country_code} in generate_map_for_country.")
        return jsonify(error=f'Map data not available for {country_code}'), 500
    # post_label_df can be None or empty for random allocation countries, plot_hex_map_with_hearts handles this.

    logging.debug(f"Generating map for country: {country_code} on demand.") # Changed from INFO to DEBUG
    plot_hex_map_with_hearts(hex_map_gdf, post_label_df, prayed_list_for_map, current_queue_for_map, country_code)

    return jsonify(status=f'Map generated for {country_code}'), 200


@app.route('/queue')
def queue_page():
    items = get_current_queue_items_from_db() # Get queue from DB
    # country_name can be added here if needed, or handled by template with all_countries
    logging.info(f"Queue items for /queue page (from DB): {len(items)}")
    return render_template('queue.html', queue=items, all_countries=COUNTRIES_CONFIG, HEART_IMG_PATH=HEART_IMG_PATH)

@app.route('/queue/json')
def get_queue_json():
    items = get_current_queue_items_from_db()
    logging.info(f"get_queue_json(): Fetched {len(items)} items from SQLite prayer_queue for JSON response.")
    # Add country name to each item
    for item in items:
        # Ensure country_code exists and is valid before trying to access COUNTRIES_CONFIG
        if 'country_code' in item and item['country_code'] in COUNTRIES_CONFIG:
            item['country_name'] = COUNTRIES_CONFIG[item['country_code']]['name']
        else:
            item['country_name'] = 'Unknown Country' # Fallback for safety
            logging.warning(f"Item in queue/json missing valid country_code: {item.get('person_name')}")

    return jsonify(items)

@app.route('/process_item', methods=['POST'])
def process_item():
    conn = None
    item_processed = False
    processed_item_details = {}
    item_id_to_process_str = request.form.get('item_id') # Renamed for clarity
    item_id_to_process = None # Initialize for use in logging in case of early error

    if not item_id_to_process_str:
        logging.error("/process_item: Missing 'item_id' in POST request.")
        return jsonify(error="Missing item_id"), 400

    try:
        item_id_to_process = int(item_id_to_process_str)
    except ValueError:
        logging.error(f"/process_item: Invalid 'item_id' format: {item_id_to_process_str}.")
        return jsonify(error="Invalid item_id format"), 400

    try:
        conn = sqlite3.connect(DATABASE_URL)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Fetch the item's details first and ensure it's 'queued'
        # Ensure hex_id is fetched by using "SELECT *" or explicitly adding it.
        # "SELECT *" already includes all columns, so hex_id will be fetched.
        cursor.execute("SELECT * FROM prayer_candidates WHERE id = ? AND status = 'queued'", (item_id_to_process,))
        row = cursor.fetchone()

        if row:
            item_to_process = dict(row) # This will now include hex_id
            person_name_to_log = item_to_process.get('person_name', 'N/A')
            country_code_item = item_to_process['country_code']
            logging.info(f"Attempting to process item ID={item_id_to_process} (Name={person_name_to_log}, HexID={item_to_process.get('hex_id')}) as requested by frontend.")

            new_status_timestamp = datetime.now()
            cursor.execute("""
                UPDATE prayer_candidates
                SET status = 'prayed', status_timestamp = ?
                WHERE id = ? AND status = 'queued'
            """, (new_status_timestamp.strftime('%Y-%m-%d %H:%M:%S'), item_id_to_process))

            if cursor.rowcount > 0:
                conn.commit()
                logging.info(f"[process_item] Successfully committed DB update for item ID={item_id_to_process} to 'prayed'.")
                item_processed = True
                processed_item_details = {
                    'person_name': item_to_process['person_name'],
                    'post_label': item_to_process.get('post_label'),
                    'country_code': country_code_item,
                    'party': item_to_process.get('party'),
                    'thumbnail': item_to_process.get('thumbnail'),
                    'timestamp': new_status_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'hex_id': item_to_process.get('hex_id') # Add hex_id here
                }
                # This block should be removed or commented out:
                # if country_code_item in prayed_for_data:
                #     prayed_for_data[country_code_item].append(processed_item_details)
                # else:
                #     logging.warning(f"Country code {country_code_item} not found in prayed_for_data for item {person_name_to_log}. In-memory list not updated by process_item.")
            else:
                conn.rollback()
                logging.warning(f"Item ID={item_id_to_process} (Name={person_name_to_log}) was not updated to 'prayed'; status may have changed or item no longer exists as 'queued'.")
        else:
            logging.warning(f"/process_item: Item with ID={item_id_to_process} not found or not in 'queued' state at time of selection.")

    except sqlite3.Error as e:
        logging.error(f"SQLite error in /process_item for ID={item_id_to_process}: {e}", exc_info=True) # Added exc_info
        if conn: conn.rollback()
    except Exception as e:
        logging.error(f"Unexpected error in /process_item for ID={item_id_to_process}: {e}", exc_info=True)
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

    if item_processed and processed_item_details:
        try:
            country_code_plot = processed_item_details['country_code']

            # **Critical Fix**: Reload prayed data for the specific country
            # to ensure in-memory `prayed_for_data` is up-to-date before plotting.
            logging.info(f"[/process_item] Reloading prayed data for country {country_code_plot} before map plotting.")
            reload_single_country_prayed_data_from_db(country_code_plot)

            hex_map_gdf = HEX_MAP_DATA_STORE.get(country_code_plot)
            post_label_df = POST_LABEL_MAPPINGS_STORE.get(country_code_plot)
            current_sqlite_queue_for_map = get_current_queue_items_from_db()

            logging.debug(f"[/process_item] Map update for country: {country_code_plot} after processing ID={item_id_to_process} and reloading prayed data.")

            # Ensure prayed_for_data[country_code_plot] is accessed *after* reload
            if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None:
                plot_hex_map_with_hearts(
                    hex_map_gdf,
                    post_label_df,
                    prayed_for_data[country_code_plot], # This should now be fresh
                    current_sqlite_queue_for_map,
                    country_code_plot
                )
            else:
                logging.warning(f"[/process_item] Cannot plot map for {country_code_plot}. Hex map GDF or post_label_df might be missing/empty.")

        except Exception as e_map_plotting:
            logging.error(f"Error during map plotting in /process_item for ID={item_id_to_process}: {e_map_plotting}", exc_info=True)

    return '', 204

@app.route('/statistics/', defaults={'country_code': None})
@app.route('/statistics/<country_code>')
def statistics(country_code):
    load_prayed_for_data_from_db() # <--- ADD THIS LINE
    if country_code is None:
        country_code = list(COUNTRIES_CONFIG.keys())[0]
        return redirect(url_for('statistics', country_code=country_code))

    if country_code not in COUNTRIES_CONFIG:
        logging.warning(f"Invalid country code '{country_code}' for statistics. Redirecting to default.")
        default_country_code = list(COUNTRIES_CONFIG.keys())[0]
        return redirect(url_for('statistics', country_code=default_country_code))

    # Data is loaded from DB at startup by load_prayed_for_data_from_db()
    # No need to call read_log(country_code) here.
    party_counts = {}
    current_country_party_info = party_info.get(country_code, {})

    # Ensure 'Other' exists in current_country_party_info for fallback
    other_party_default = {'short_name': 'Other', 'color': '#CCCCCC'} # A generic default for 'Other'

    for item in prayed_for_data[country_code]:
        party = item.get('party', 'Other')
        # Fallback to the specific country's 'Other', then to a generic 'Other' if not defined
        party_details = current_country_party_info.get(party, current_country_party_info.get('Other', other_party_default))
        short_name = party_details['short_name']
        party_counts[short_name] = party_counts.get(short_name, 0) + 1

    sorted_party_counts = sorted(party_counts.items(), key=lambda x: x[1], reverse=True)

    return render_template('statistics.html',
                           sorted_party_counts=sorted_party_counts,
                           current_party_info=current_country_party_info,
                           all_countries=COUNTRIES_CONFIG,
                           country_code=country_code,
                           country_name=COUNTRIES_CONFIG[country_code]['name'])


@app.route('/statistics/data/<country_code>')
def statistics_data(country_code):
    load_prayed_for_data_from_db() # <--- ADD THIS LINE
    if country_code not in COUNTRIES_CONFIG:
        return jsonify({"error": "Country not found"}), 404

    # Data is loaded from DB at startup.
    party_counts = {}
    current_country_party_info = party_info.get(country_code, {})
    other_party_default = {'short_name': 'Other'}

    for item in prayed_for_data[country_code]:
        party = item.get('party', 'Other')
        party_details = current_country_party_info.get(party, current_country_party_info.get('Other', other_party_default))
        short_name = party_details['short_name']
        party_counts[short_name] = party_counts.get(short_name, 0) + 1
    return jsonify(party_counts)

@app.route('/statistics/timedata/<country_code>')
def statistics_timedata(country_code):
    load_prayed_for_data_from_db() # <--- ADD THIS LINE
    if country_code not in COUNTRIES_CONFIG:
        return jsonify({"error": "Country not found"}), 404

    # Data is loaded from DB at startup.
    timestamps = []
    values = []
    # current_country_party_info is not strictly needed here if we're just passing the party name string
    # but if color or other info were to be passed, it would be.
    for item in prayed_for_data[country_code]:
        timestamps.append(item.get('timestamp'))
        values.append({
            'place': item.get('post_label'),
            'person': item.get('person_name'),
            'party': item.get('party') # Pass the original party name
        })
    return jsonify({'timestamps': timestamps, 'values': values, 'country_name': COUNTRIES_CONFIG[country_code]['name']})

@app.route('/prayed/', defaults={'country_code': None})
@app.route('/prayed/<country_code>')
def prayed_list(country_code):
    load_prayed_for_data_from_db() # <--- THIS LINE WAS ALREADY ADDED

    if country_code is None:
        # If redirecting, load_prayed_for_data_from_db() will run again in the new request, which is fine.
        country_code = list(COUNTRIES_CONFIG.keys())[0] # Default to first country if none provided
        # For an overall view, we might expect a specific URL like /prayed/overall
        # This redirect ensures country_code is always a specific country or handled by 'overall' logic path
        if country_code: # Check if COUNTRIES_CONFIG was empty
             return redirect(url_for('prayed_list', country_code=country_code))
        else: # No countries configured, perhaps redirect to a page indicating this
             return redirect(url_for('home')) # Fallback, or a dedicated "no data" page

    if country_code == 'overall':
        # This will be handled by prayed_list_overall route now,
        # but if direct navigation to /prayed/overall happens, this logic is fine.
        # The logging for 'overall' is better placed in prayed_list_overall itself.
        pass # Overall logic is handled by a different route or below
    elif country_code not in COUNTRIES_CONFIG:
        logging.warning(f"Invalid country code '{country_code}' for prayed list. Redirecting to default.")
        default_country_code = list(COUNTRIES_CONFIG.keys())[0] if COUNTRIES_CONFIG else None
        if default_country_code:
            return redirect(url_for('prayed_list', country_code=default_country_code))
        else:
            return redirect(url_for('home')) # Fallback if no countries configured

    # Ensure this is after country_code is finalized and checked
    if country_code and country_code != 'overall' and country_code in prayed_for_data:
        logging.info(f"[/prayed/{country_code}] After load_prayed_for_data_from_db(), items for this country in memory: {len(prayed_for_data[country_code])}.")
    # elif country_code == 'overall': # This logging is better in prayed_list_overall
    #     total_prayed_overall = sum(len(lst) for lst in prayed_for_data.values())
    #     logging.info(f"[/prayed/overall] After load_prayed_for_data_from_db(), total prayed items in memory: {total_prayed_overall}.")

    current_country_party_info = party_info.get(country_code, {})
    # Ensure 'Other' exists in current_country_party_info for fallback
    other_party_default = {'short_name': 'Other', 'color': '#CCCCCC'}

    # Prepare a new list for rendering to avoid modifying data in prayed_for_data directly
    current_prayed_items_display = []
    for item_original in prayed_for_data[country_code]:
        item = item_original.copy() # Work with a copy for display modifications
        item['formatted_timestamp'] = format_pretty_timestamp(item.get('timestamp'))
        party_name_from_log = item.get('party', 'Other')
        party_data = current_country_party_info.get(party_name_from_log,
                                                  current_country_party_info.get('Other', other_party_default))
        item['party_class'] = party_data['short_name'].lower().replace(' ', '-').replace('&', 'and')
        item['party_color'] = party_data['color']
        # 'country_code' should already be in the item from when it was processed
        # but if adding it for safety:
        if 'country_code' not in item:
             item['country_code'] = country_code # Ensure it's there for the template form
        current_prayed_items_display.append(item)

    return render_template('prayed.html',
                           prayed_for_list=current_prayed_items_display,
                           country_code=country_code,
                           country_name=COUNTRIES_CONFIG[country_code]['name'],
                           all_countries=COUNTRIES_CONFIG)

# Routes for Overall Statistics
@app.route('/statistics/overall')
def statistics_overall():
    load_prayed_for_data_from_db() # <--- ADD THIS LINE
    return render_template('statistics.html',
                           country_code='overall',
                           country_name='Overall',
                           sorted_party_counts={}, # No specific party breakdown for overall
                           current_party_info={},    # No specific party info for overall
                           all_countries=COUNTRIES_CONFIG)

@app.route('/statistics/data/overall')
def statistics_data_overall():
    load_prayed_for_data_from_db() # <--- ADD THIS LINE
    total_prayed_count = sum(len(prayed_list) for prayed_list in prayed_for_data.values())
    return jsonify({'Overall': total_prayed_count})

@app.route('/statistics/timedata/overall')
def statistics_timedata_overall():
    load_prayed_for_data_from_db() # <--- ADD THIS LINE
    all_prayed_items = []
    for country_items in prayed_for_data.values():
        all_prayed_items.extend(country_items)

    # Sort by timestamp - ensure items have 'timestamp' and it's comparable
    # It's good practice to handle items that might be missing 'timestamp' if that's possible
    all_prayed_items.sort(key=lambda x: x.get('timestamp', ''))

    timestamps = []
    values = []
    for item in all_prayed_items:
        if item.get('timestamp'): # Ensure timestamp exists before adding
            timestamps.append(item.get('timestamp'))
            values.append({
                'place': item.get('post_label'), # Changed from 'place' to 'post_label' for consistency
                'person': item.get('person_name'),
                'country': COUNTRIES_CONFIG[item['country_code']]['name'] if item.get('country_code') in COUNTRIES_CONFIG else 'Unknown'
                # Party is intentionally omitted for the overall timedata view
            })
    return jsonify({'timestamps': timestamps, 'values': values, 'country_name': 'Overall'})

# Route for Overall Prayed List
@app.route('/prayed/overall')
def prayed_list_overall():
    load_prayed_for_data_from_db() # <--- ADD THIS LINE
    overall_prayed_list_display = []
    for country_code, items_list in prayed_for_data.items():
        for item in items_list:
            display_item = item.copy()
            # Ensure country_code from item is valid before accessing COUNTRIES_CONFIG
            item_country_code = display_item.get('country_code')
            if item_country_code and item_country_code in COUNTRIES_CONFIG:
                 display_item['country_name_display'] = COUNTRIES_CONFIG[item_country_code]['name']
            else:
                 display_item['country_name_display'] = 'Unknown Country' # Fallback
            display_item['formatted_timestamp'] = format_pretty_timestamp(item.get('timestamp'))
            # Party class/color not added as it's an overall list; template would need to handle this
            overall_prayed_list_display.append(display_item)

    # Sort by timestamp, most recent first
    overall_prayed_list_display.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    return render_template('prayed.html',
                           prayed_for_list=overall_prayed_list_display,
                           country_code='overall',
                           country_name='Overall',
                           all_countries=COUNTRIES_CONFIG,
                           current_party_info={}) # No specific party context for overall


@app.route('/purge')
def purge_queue():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM prayer_candidates")
        logging.info("Purged all items from SQLite prayer_candidates table.")
        # Removing old table purges:
        # cursor.execute("DELETE FROM prayer_queue")
        # logging.info("Purged all items from SQLite prayer_queue table.")
        # cursor.execute("DELETE FROM prayed_items")
        # logging.info("Purged all items from SQLite prayed_items table.")
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"SQLite error during purge of prayer_candidates table: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

    # Clear in-memory prayed_for data for the current session
    for country_code_purge in COUNTRIES_CONFIG.keys():
        prayed_for_data[country_code_purge] = []
    logging.info("Cleared in-memory prayed_for_data for all countries.")

    # JSON log file clearing is now removed as it's obsolete.

    # Call update_queue to repopulate
    logging.info("Calling update_queue() after purge to repopulate the queue.")
    update_queue()

    # Reset map for the default/first country after purge
    default_country_purge = list(COUNTRIES_CONFIG.keys())[0]
    hex_map_gdf = HEX_MAP_DATA_STORE.get(default_country_purge)
    post_label_df = POST_LABEL_MAPPINGS_STORE.get(default_country_purge)
    if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None:
        plot_hex_map_with_hearts(
            hex_map_gdf,
            post_label_df,
            [], # Empty prayed_for_items
            [], # Empty queue_items (since DB is cleared)
            default_country_purge
        )
    return redirect(url_for('home'))

@app.route('/refresh')
def refresh_data():
    # The update_queue thread is already running as a daemon.
    # This endpoint might be for forcing an immediate check outside the 90s loop,
    # or could be removed if not deemed necessary.
    logging.info("Refresh endpoint called. Queue update is handled by a background thread.")
    return redirect(url_for('home'))

@app.route('/put_back', methods=['POST'])
def put_back_in_queue():
    person_name = request.form.get('person_name')
    post_label_form = request.form.get('post_label')
    item_country_code_from_form = request.form.get('country_code')
    redirect_target_country_code = item_country_code_from_form # Used for redirecting at the end

    # Strip whitespace from form inputs
    if person_name:
        person_name = person_name.strip()

    # _post_label_from_form_stripped = None
    # if post_label_form is not None: # Ensure not to strip None, only actual strings
    #     _post_label_from_form_stripped = post_label_form.strip()
        # If stripping makes it empty, it will be handled by later logic converting "" to None for DB

    if not item_country_code_from_form or item_country_code_from_form not in COUNTRIES_CONFIG:
        logging.error(f"Invalid or missing country_code '{item_country_code_from_form}' in put_back request form.")
    else:
        # For searching in memory (if still needed for item_to_put_back_from_memory)
        # This part is less critical if we trust the form values for the DB operation primarily.
        # Keep the existing logic for post_label_key_search for in-memory lookup if it's used.
        _post_label_from_form_stripped_for_mem_search = None
        if post_label_form is not None:
            _post_label_from_form_stripped_for_mem_search = post_label_form.strip()
        # post_label_key_search_for_memory is used for the initial in-memory lookup if that logic path is still heavily relied upon.
        post_label_key_search_for_memory = _post_label_from_form_stripped_for_mem_search if _post_label_from_form_stripped_for_mem_search else ""


        # --- Start of new DB query logic for post_label ---
        query_post_label_value_for_db = None
        is_post_label_null_in_db_query = False
        log_display_post_label = "" # For logging

        if post_label_form is None or not post_label_form.strip(): # Catches None, "", "   " submitted from form
            is_post_label_null_in_db_query = True
            log_display_post_label = "NULL"
        else:
            # Use the raw value from the form for the DB query, as this matches what's in item.post_label
            query_post_label_value_for_db = post_label_form
            log_display_post_label = f"'{post_label_form}'" # Use f-string for clarity

        # This logging uses log_display_post_label for clarity on what's being queried
        logging.info(f"Preparing to put back item: Name='{person_name}', PostLabel for DB Query={log_display_post_label}, Country='{item_country_code_from_form}'.")

        # --- START OF NEW DIAGNOSTIC BLOCK ---
        diag_conn = None
        try:
            diag_conn = sqlite3.connect(DATABASE_URL)
            diag_conn.row_factory = sqlite3.Row
            diag_cursor = diag_conn.cursor()

            # Base of the SELECT query
            diag_select_sql = "SELECT * FROM prayer_candidates WHERE person_name = ? AND country_code = ?"
            diag_params = [person_name, item_country_code_from_form]

            # Conditionally add post_label check
            if is_post_label_null_in_db_query: # True if post_label_form was None, empty, or whitespace
                diag_select_sql += " AND post_label IS NULL"
                # No change to diag_params needed
            else: # post_label_form has actual content
                diag_select_sql += " AND post_label = ?"
                diag_params.append(query_post_label_value_for_db) # query_post_label_value_for_db holds the actual string

            logging.debug(f"[DIAGNOSTIC] Executing SELECT: {diag_select_sql} with params {diag_params}")
            diag_cursor.execute(diag_select_sql, tuple(diag_params)) # Ensure diag_params is a tuple
            diagnostic_row = diag_cursor.fetchone()

            if diagnostic_row:
                logging.info(f"[DIAGNOSTIC] Found existing record for {person_name} (PostLabel in form: '{post_label_form}', Queried as: {log_display_post_label}, Country: {item_country_code_from_form}): Status='{diagnostic_row['status']}', DB PostLabel='{diagnostic_row['post_label']}', ID='{diagnostic_row['id']}'")
            else:
                logging.warning(f"[DIAGNOSTIC] No record found for {person_name} (PostLabel in form: '{post_label_form}', Queried as: {log_display_post_label}, Country: {item_country_code_from_form}) with the specified name/post_label/country combination.")

        except sqlite3.Error as e_diag:
            logging.error(f"[DIAGNOSTIC] SQLite error during diagnostic select: {e_diag}", exc_info=True) # Add exc_info
        except Exception as e_diag_generic:
            logging.error(f"[DIAGNOSTIC] Generic error during diagnostic select: {e_diag_generic}", exc_info=True)
        finally:
            if diag_conn:
                diag_conn.close()
        # --- END OF NEW DIAGNOSTIC BLOCK ---
        # --- End of new DB query logic for post_label --- # This comment is correctly placed after the original logic block it refers to.

        # The part finding item_to_put_back_from_memory can remain as is, using post_label_key_search_for_memory
        # This section is primarily for fetching the full item details if needed, though not strictly required if keys are sufficient.
        item_to_put_back_from_memory = None
        item_index_to_remove_from_memory = -1 # Reset or ensure this is correctly handled if memory op depends on it
        # current_country_prayed_list = prayed_for_data.get(item_country_code_from_form, []) # Example of getting the list
        # (Original logic for finding item_to_put_back_from_memory and item_index_to_remove_from_memory would go here if it's essential)
        # For now, we are focusing on the DB update being correct based on form values.


        # Database operation
        db_conn = None
        updated_in_db = False
        try:
            db_conn = sqlite3.connect(DATABASE_URL)
            db_conn.row_factory = sqlite3.Row # Important for fetching diagnostic_row details by name
            cursor = db_conn.cursor()
            new_status_timestamp = datetime.now()

            # Fetch the item first to check its current hex_id
            # The diagnostic_row from earlier can be used if it's confirmed to be the correct item.
            # For safety, re-fetch or ensure diagnostic_row is exactly the one to update.
            # Assuming diagnostic_row (fetched above the try-finally) is the target item.
            # Let's refine this to fetch within the transaction for safety.

            current_hex_id = None
            select_sql_for_put_back = "SELECT id, hex_id FROM prayer_candidates WHERE person_name = ? AND country_code = ? AND status = 'prayed'"
            params_for_put_back = [person_name, item_country_code_from_form]
            if is_post_label_null_in_db_query:
                select_sql_for_put_back += " AND post_label IS NULL"
            else:
                select_sql_for_put_back += " AND post_label = ?"
                params_for_put_back.append(query_post_label_value_for_db)

            cursor.execute(select_sql_for_put_back, tuple(params_for_put_back))
            item_to_update_details = cursor.fetchone()

            if not item_to_update_details:
                logging.warning(f"Item {person_name} (Post: {log_display_post_label}) for {item_country_code_from_form} not found with status 'prayed' for put_back. No DB update made.")
                updated_in_db = False
            else:
                current_hex_id = item_to_update_details['hex_id']
                item_db_id = item_to_update_details['id']
                hex_id_to_set = current_hex_id

                random_allocation_countries = ['israel', 'iran']
                if item_country_code_from_form in random_allocation_countries and not current_hex_id:
                    logging.info(f"Item {person_name} in {item_country_code_from_form} has NULL hex_id. Attempting to assign one.")
                    hex_map_gdf_put_back = HEX_MAP_DATA_STORE.get(item_country_code_from_form)
                    if hex_map_gdf_put_back is not None and not hex_map_gdf_put_back.empty and 'id' in hex_map_gdf_put_back.columns:
                        all_map_hex_ids_pb = set(hex_map_gdf_put_back['id'].unique())

                        # Fetch currently used hex_ids (prayed or queued) for this country
                        cursor.execute("""
                            SELECT hex_id FROM prayer_candidates
                            WHERE country_code = ? AND hex_id IS NOT NULL AND id != ?
                        """, (item_country_code_from_form, item_db_id)) # Exclude current item being processed
                        used_hex_ids_rows_pb = cursor.fetchall()
                        used_hex_ids_pb = {row['hex_id'] for row in used_hex_ids_rows_pb}

                        available_hex_ids_pb = list(all_map_hex_ids_pb - used_hex_ids_pb)
                        if available_hex_ids_pb:
                            random.shuffle(available_hex_ids_pb)
                            hex_id_to_set = available_hex_ids_pb.pop()
                            logging.info(f"Assigned new hex_id {hex_id_to_set} to {person_name} during put_back.")
                        else:
                            logging.warning(f"No available hex_ids to assign to {person_name} in {item_country_code_from_form} during put_back.")
                            # hex_id_to_set remains None if no hex can be assigned
                    else:
                        logging.warning(f"Hex map data not available for {item_country_code_from_form} during put_back hex_id assignment.")

                # Now perform the update with potentially new hex_id
                cursor.execute("""
                    UPDATE prayer_candidates
                    SET status = 'queued', status_timestamp = ?, hex_id = ?
                    WHERE id = ?
                """, (new_status_timestamp.strftime('%Y-%m-%d %H:%M:%S'), hex_id_to_set, item_db_id))

                if cursor.rowcount > 0:
                    db_conn.commit()
                    logging.info(f"Item {person_name} (ID: {item_db_id}, Post: {log_display_post_label}) for {item_country_code_from_form} status updated to 'queued', hex_id set to {hex_id_to_set}.")
                    updated_in_db = True
                else:
                    # This case should ideally not be reached if item_to_update_details was found.
                    db_conn.rollback()
                    logging.error(f"Failed to update item {person_name} (ID: {item_db_id}) even after finding it. This should not happen.")

        except sqlite3.Error as e:
            logging.error(f"SQLite error in /put_back_in_queue when updating prayer_candidates for {person_name}: {e}")
            if db_conn: db_conn.rollback()
        finally:
            if db_conn: db_conn.close()

        if updated_in_db:
            # Reload this country's prayed data from DB to update in-memory list
            reload_single_country_prayed_data_from_db(item_country_code_from_form)
            logging.info(f"In-memory prayed_for_data for {item_country_code_from_form} reloaded after putting item back to queue.")

            # Map plotting
            hex_map_gdf = HEX_MAP_DATA_STORE.get(item_country_code_from_form)
            post_label_df = POST_LABEL_MAPPINGS_STORE.get(item_country_code_from_form) # Corrected Indentation
            current_sqlite_queue_for_map_put_back = get_current_queue_items_from_db() # Corrected Indentation

            if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None: # Corrected Indentation
                plot_hex_map_with_hearts( # Corrected Indentation
                    hex_map_gdf,
                    post_label_df,
                    prayed_for_data[item_country_code_from_form],
                    current_sqlite_queue_for_map_put_back,
                    item_country_code_from_form
                )
        # else: (if not updated_in_db)
            # No need to update memory or plot map if DB wasn't changed.
            # The warning log about no DB update made is sufficient.

        # Redirect logic (should be outside the 'if updated_in_db' unless redirect depends on success)
        # Assuming redirect_target_country_code is defined earlier based on item_country_code_from_form
    if redirect_target_country_code and redirect_target_country_code in COUNTRIES_CONFIG:
        return redirect(url_for('prayed_list', country_code=redirect_target_country_code))
    else:
        default_redirect_country = list(COUNTRIES_CONFIG.keys())[0] if COUNTRIES_CONFIG else None
        if default_redirect_country:
            logging.warning(f"put_back_in_queue: Invalid or missing country_code in form ('{item_country_code_from_form}'). Redirecting to default: {default_redirect_country}")
            return redirect(url_for('prayed_list', country_code=default_redirect_country))
        else:
            logging.error("put_back_in_queue: No valid country_code from form and no default country configured.")
            return redirect(url_for('home')) # Absolute fallback

# Synchronously initialize application data when the module is loaded
logging.info("Starting synchronous application data initialization at module load...")
initialize_app_data() # This will block until complete. Its last step starts the update_queue daemon.
logging.info("Synchronous application data initialization finished at module load.")

if __name__ == '__main__':
    # This block is mainly for local Flask development server
    try:
        port = int(os.environ.get('PORT', 5000))
        # Note: initialize_app_data() is already called above, so it runs once when app starts.
        # For local dev, app.run() might cause another load if reloader is on, but for Gunicorn, it's fine.
        app.run(debug=True, host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print('You pressed Ctrl+C! Exiting gracefully...')
        sys.exit(0)
