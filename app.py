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
DATA_DIR = os.path.join(APP_ROOT, 'data')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
DATABASE_URL = os.path.join(DATA_DIR, 'queue.db')
os.makedirs(LOG_DIR, exist_ok=True) # Create log directory immediately
os.makedirs(DATA_DIR, exist_ok=True) # Ensure data directory exists for DB

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler(os.path.join(LOG_DIR, "app.log")),
    logging.StreamHandler()
])

# Log path initializations (optional but good for debugging)
logging.info(f"APP_ROOT set to: {APP_ROOT}")
logging.info(f"LOG_DIR set to: {LOG_DIR} (created if didn't exist).")

app = Flask(__name__)

# Configuration
COUNTRIES_CONFIG = {
    'israel': {
        'csv_path': os.path.join(APP_ROOT, 'data/20221101_israel.csv'),
        'geojson_path': os.path.join(APP_ROOT, 'data/ISR_Parliament_120.geojson'),
        'map_shape_path': os.path.join(APP_ROOT, 'data/ISR_Parliament_120.geojson'),
        'post_label_mapping_path': None,
        'total_representatives': 120,
        # 'log_file': os.path.join(LOG_DIR, 'prayed_for_israel.json'), # Removed
        'name': 'Israel',
        'flag': '🇮🇱'
    },
    'iran': {
        'csv_path': os.path.join(APP_ROOT, 'data/20240510_iran.csv'),
        'geojson_path': os.path.join(APP_ROOT, 'data/IRN_IslamicParliamentofIran_290_v2.geojson'),
        'map_shape_path': os.path.join(APP_ROOT, 'data/IRN_IslamicParliamentofIran_290_v2.geojson'),
        'post_label_mapping_path': None,
        'total_representatives': 290,
        # 'log_file': os.path.join(LOG_DIR, 'prayed_for_iran.json'), # Removed
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

        conn.commit()
        logging.info("Successfully initialized SQLite database tables and indexes.")
    except sqlite3.Error as e:
        logging.error(f"Error initializing SQLite database: {e}")
    finally:
        if conn:
            conn.close()

def initialize_app_data():
    # The content from the existing `if __name__ == '__main__':` block's loop
    # and the thread starting line will go here.
    init_sqlite_db() # Initialize SQLite database
    migrate_json_logs_to_db() # Migrate old JSON logs if prayed_items table is empty
    load_prayed_for_data_from_db() # Load all prayed for data from DB into memory
    logging.info("Starting application data initialization...")

    # Loop for deputies_data, HEX_MAP_DATA_STORE, POST_LABEL_MAPPINGS_STORE initialization
    for country_code_init in COUNTRIES_CONFIG.keys():
        logging.info(f"Initializing non-log data for country: {country_code_init}")
        logging.info(f"Using CSV path: {COUNTRIES_CONFIG[country_code_init]['csv_path']}")
        logging.info(f"Using GeoJSON path: {COUNTRIES_CONFIG[country_code_init]['geojson_path']}")
        # The specific log line for 'log_file' path has been removed.

        # Fetch and process CSV data for deputies
        df_init = fetch_csv(country_code_init)
        if not df_init.empty:
            process_deputies(df_init, country_code_init) # process_deputies logs
            logging.info(f"Processed deputies for {country_code_init}: {len(deputies_data[country_code_init]['with_images'])} with images, {len(deputies_data[country_code_init]['without_images'])} without.")
        else:
            logging.warning(f"CSV data for {country_code_init} was empty. No deputies processed.")

        # Load map shape data
        map_path = COUNTRIES_CONFIG[country_code_init]['map_shape_path']
        if os.path.exists(map_path):
            if country_code_init in ['israel', 'iran']:
                logging.info(f"Attempting to load hex map for specific country: {country_code_init} from {map_path}")

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
            logging.info(f"No post label mapping file specified for country {country_code_init}. Assigning empty DataFrame.")
            POST_LABEL_MAPPINGS_STORE[country_code_init] = pd.DataFrame() # Ensure empty DataFrame is assigned

        # Logging for post_label_mapping results
        if POST_LABEL_MAPPINGS_STORE.get(country_code_init) is not None and not POST_LABEL_MAPPINGS_STORE[country_code_init].empty:
            logging.info(f"Successfully loaded post label mapping for {country_code_init} with {len(POST_LABEL_MAPPINGS_STORE[country_code_init])} entries.")
        elif POST_LABEL_MAPPINGS_STORE.get(country_code_init) is not None and POST_LABEL_MAPPINGS_STORE[country_code_init].empty:
            logging.warning(f"Loaded post label mapping for {country_code_init} is empty (this may be normal).")
        # No else needed as it's initialized to empty DataFrame

    logging.info("Application data initialization complete.")

    # Start the queue updating thread
    logging.info("Starting the update_queue background thread.")
    threading.Thread(target=update_queue, daemon=True).start()

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
        # Select all relevant columns for display and processing
        cursor.execute("""
            SELECT id, person_name, post_label, country_code, party, thumbnail, added_timestamp
            FROM prayer_queue
            ORDER BY added_timestamp ASC
        """)
        rows = cursor.fetchall()
        for row in rows:
            items.append(dict(row))
        logging.info(f"Fetched {len(items)} items from SQLite prayer_queue.")
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
    logging.info(f"Fetching CSV data for {country_code}")
    csv_path = COUNTRIES_CONFIG[country_code]['csv_path']
    try:
        df = pd.read_csv(csv_path)
        logging.info(f"Successfully fetched {len(df)} rows from {csv_path}")
        df = df.replace({np.nan: None})
        logging.debug(f"Fetched data for {country_code}: {df.head()}")
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
        logging.info("Update_queue thread started.")
        while True:
            conn = None  # Initialize conn to None
            try:
                logging.info("update_queue [cycle start]: Checking for new items to add to SQLite prayer_queue.")
                all_potential_candidates = []
                # Phase 1: Collect all potential candidates from all countries
                for country_code_collect in COUNTRIES_CONFIG.keys():
                    df_update = fetch_csv(country_code_collect)
                    if df_update.empty:
                        logging.debug(f"No CSV data for {country_code_collect} in this cycle.")
                        continue

                    df_update = df_update.sample(frac=1).reset_index(drop=True)
                    # current_prayed_for_ids is used to avoid re-adding recently prayed for items from *this session*
                    # It does not check the DB, as the DB queue handles persistence.
                    current_prayed_for_ids = {(item['person_name'], item.get('post_label', '')) for item in prayed_for_data[country_code_collect]}
                    country_candidates_selected_this_cycle = set() # Tracks items selected in the current CSV scan for this country

                    for index, row in df_update.iterrows():
                        if row.get('person_name'):
                            item = row.to_dict()
                            item['country_code'] = country_code_collect
                            if not item.get('party'):
                                item['party'] = 'Other'

                            # Ensure post_label is consistently handled (e.g., as empty string if None)
                            item_post_label = item.get('post_label') if item.get('post_label') is not None else ""
                            item['post_label'] = item_post_label # Standardize it in the item dict

                            entry_id = (item['person_name'], item_post_label) # Used for session-based prayed_for check

                            # Check against this session's prayed_for data and candidates already selected in this cycle
                            if entry_id not in current_prayed_for_ids and \
                               entry_id not in country_candidates_selected_this_cycle:
                                image_url = item.get('image_url', HEART_IMG_PATH)
                                if not image_url: # Ensure thumbnail has a value
                                    image_url = HEART_IMG_PATH
                                item['thumbnail'] = image_url
                                all_potential_candidates.append(item)
                                country_candidates_selected_this_cycle.add(entry_id)
                        else:
                            logging.debug(f"Skipped entry due to missing person_name for {country_code_collect} at index {index}: {row.to_dict()}")

                logging.info(f"Collected {len(all_potential_candidates)} total potential new candidates from all countries this cycle.")
                random.shuffle(all_potential_candidates)

                items_added_to_db_this_cycle = 0
                if all_potential_candidates: # Only connect if there's something to potentially add
                    conn = sqlite3.connect(DATABASE_URL)
                    cursor = conn.cursor()

                    for item_to_add in all_potential_candidates:
                        person_name = item_to_add['person_name']
                        post_label = item_to_add['post_label'] # Already standardized
                        country_code = item_to_add['country_code']
                        party = item_to_add['party']
                        thumbnail = item_to_add['thumbnail']

                        # Check if item already exists in SQLite prayer_queue
                        # Handle post_label being potentially NULL in DB if it was empty string
                        if post_label == "":
                            cursor.execute("SELECT id FROM prayer_queue WHERE person_name = ? AND post_label IS NULL AND country_code = ?",
                                           (person_name, country_code))
                        else:
                            cursor.execute("SELECT id FROM prayer_queue WHERE person_name = ? AND post_label = ? AND country_code = ?",
                                           (person_name, post_label, country_code))

                        if cursor.fetchone() is None:
                            # Item does not exist, insert it
                            try:
                                cursor.execute('''
                                    INSERT INTO prayer_queue (person_name, post_label, country_code, party, thumbnail)
                                    VALUES (?, ?, ?, ?, ?)
                                ''', (person_name, post_label if post_label else None, country_code, party, thumbnail))
                                conn.commit()
                                logging.info(f"Added to SQLite prayer_queue: {person_name} (Post: {post_label}, Party: {party}) from {country_code}")
                                items_added_to_db_this_cycle += 1
                            except sqlite3.IntegrityError:
                                # This might happen if another process/thread added it, or due to timing.
                                logging.warning(f"IntegrityError when trying to insert {person_name} ({post_label}) for {country_code}. Item might already exist (race condition).")
                            except sqlite3.Error as e:
                                logging.error(f"SQLite error when inserting {person_name} ({post_label}): {e}")
                        else:
                            logging.debug(f"Item {person_name} ({post_label}) for {country_code} already exists in SQLite prayer_queue. Skipping.")

                if items_added_to_db_this_cycle > 0:
                    logging.info(f"Added {items_added_to_db_this_cycle} new items to the SQLite prayer_queue this cycle.")

                # Query current size of SQLite queue for logging
                current_db_queue_size = 0
                if conn: # If connection was opened
                    cursor.execute("SELECT COUNT(id) FROM prayer_queue")
                    count_result = cursor.fetchone()
                    if count_result:
                        current_db_queue_size = count_result[0]

                logging.info(f"Update_queue cycle complete. Current SQLite prayer_queue size: {current_db_queue_size}")

            except Exception as e:
                logging.error(f"Unexpected error in update_queue thread: {e}", exc_info=True)
            finally:
                if conn:
                    conn.close()
                    logging.debug("SQLite connection closed in update_queue.")

            time.sleep(90)

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
        cursor.execute("SELECT person_name, post_label, country_code, party, thumbnail, prayed_timestamp FROM prayed_items")

        rows = cursor.fetchall()
        loaded_count = 0
        for row_data in rows:
            item = dict(row_data)
            # Map prayed_timestamp from DB to 'timestamp' for consistency in current app logic
            item['timestamp'] = item.pop('prayed_timestamp', None)

            country_code = item.get('country_code')
            if country_code in prayed_for_data:
                prayed_for_data[country_code].append(item)
                loaded_count +=1
            else:
                logging.warning(f"Found item in prayed_items table with unknown country_code: {country_code} - Item: {item.get('person_name')}")

        logging.info(f"Loaded {loaded_count} items from prayed_items DB into memory.")
        for country_code_key in prayed_for_data:
             logging.debug(f"Country {country_code_key} has {len(prayed_for_data[country_code_key])} prayed items in memory after DB load.")

    except sqlite3.Error as e:
        logging.error(f"SQLite error in load_prayed_for_data_from_db: {e}")
    except Exception as e_gen:
        logging.error(f"Unexpected error in load_prayed_for_data_from_db: {e_gen}", exc_info=True)
    finally:
        if conn:
            conn.close()

def add_prayed_item_to_db(item):
    """Adds a single prayed-for item to the prayed_items SQLite table."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_URL)
        cursor = conn.cursor()

        # Ensure 'timestamp' from item is used for 'prayed_timestamp'
        prayed_timestamp_val = item.get('timestamp')
        if not prayed_timestamp_val:
            # Fallback if 'timestamp' is somehow missing, though process_item should set it
            prayed_timestamp_val = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logging.warning(f"Item for {item.get('person_name')} missing 'timestamp', using current time for prayed_timestamp.")

        cursor.execute('''
            INSERT INTO prayed_items (person_name, post_label, country_code, party, thumbnail, prayed_timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (item.get('person_name'),
              item.get('post_label'),
              item.get('country_code'),
              item.get('party'),
              item.get('thumbnail'),
              prayed_timestamp_val))
        conn.commit()
        logging.info(f"Added item to prayed_items DB: {item.get('person_name')} for {item.get('country_code')}")
    except sqlite3.IntegrityError:
        logging.warning(f"IntegrityError: Item {item.get('person_name')} for {item.get('country_code')} likely already exists in prayed_items DB. Not re-added.")
    except sqlite3.Error as e:
        logging.error(f"SQLite error in add_prayed_item_to_db for {item.get('person_name')}: {e}")
        if conn:
            conn.rollback()
    except Exception as e_gen:
        logging.error(f"Unexpected error in add_prayed_item_to_db: {e_gen}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

@app.route('/')
def home():
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
    logging.info(f"[home] map_to_display_country determined as: {map_to_display_country}")
    if map_to_display_country in prayed_for_data:
        logging.info(f"[home] Size of prayed_for_data['{map_to_display_country}']: {len(prayed_for_data[map_to_display_country])}")
    else:
        logging.warning(f"[home] map_to_display_country '{map_to_display_country}' not found in prayed_for_data keys.")
    logging.info(f"[home] Number of current_queue_items being passed to plot_hex_map_with_hearts: {len(current_queue_items)}")
    # ==== DETAILED LOGGING END ====

    # load_prayed_for_data_from_db() is called at startup.
    # If specific routes need to refresh this from DB, they could call it,
    # but for now, relying on initial load.
    # The map plotting uses the in-memory prayed_for_data which is populated from DB at start.
    # No need to call read_log() here anymore.

    hex_map_gdf = HEX_MAP_DATA_STORE.get(map_to_display_country)
    post_label_df = POST_LABEL_MAPPINGS_STORE.get(map_to_display_country)
    logging.info(f"Rendering home page. Map for country: {map_to_display_country}")
    if hex_map_gdf is not None and not hex_map_gdf.empty:
        logging.info(f"Hex map data for {map_to_display_country} is available for plotting.")
    else:
        logging.warning(f"Hex map data for {map_to_display_country} is MISSING or empty. Plotting may fail or show default.")
    if post_label_df is not None and not post_label_df.empty:
        logging.info(f"Post label mapping for {map_to_display_country} is available.")
    else:
        logging.warning(f"Post label mapping for {map_to_display_country} is MISSING or empty (may be normal for random allocation).")
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
    logging.info(f"[generate_map_for_country] Received country_code: {country_code}")
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
    logging.info(f"[generate_map_for_country] Size of prayed_list_for_map for '{country_code}': {len(prayed_list_for_map)}")
    logging.info(f"[generate_map_for_country] Size of current_queue_for_map for '{country_code}': {len(current_queue_for_map)}")
    # ==== DETAILED LOGGING END ====

    if hex_map_gdf is None or hex_map_gdf.empty : # Check for None or empty GeoDataFrame
        logging.error(f"Map data (GeoDataFrame) not available for {country_code} in generate_map_for_country.")
        return jsonify(error=f'Map data not available for {country_code}'), 500
    # post_label_df can be None or empty for random allocation countries, plot_hex_map_with_hearts handles this.

    logging.info(f"Generating map for country: {country_code} on demand.")
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
    processed_item_details = {} # To store details for logging and map plotting

    try:
        conn = sqlite3.connect(DATABASE_URL)
        conn.row_factory = sqlite3.Row # Access columns by name
        cursor = conn.cursor()

        # Fetch the oldest item
        cursor.execute("SELECT * FROM prayer_queue ORDER BY added_timestamp ASC LIMIT 1")
        row = cursor.fetchone()

        if row:
            # Convert row to a dictionary
            item = dict(row)
            item_id_to_delete = item['id']
            person_name_to_log = item.get('person_name', 'N/A')
            logging.info(f"Fetched item from prayer_queue: ID={item_id_to_delete}, Name={person_name_to_log}")

            # Store details for use after deletion
            processed_item_details = item.copy()
            country_code_item = item['country_code']

            # Delete the item from the queue
            cursor.execute("DELETE FROM prayer_queue WHERE id = ?", (item_id_to_delete,))
            conn.commit()
            logging.info(f"Successfully deleted item ID={item_id_to_delete}, Name={person_name_to_log} from prayer_queue DB table.")
            item_processed = True

            # Add timestamp for logging purposes (not stored in DB this way)
            item['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Add to SQLite prayed_items table
            # add_prayed_item_to_db already logs success/failure, including IntegrityError
            add_prayed_item_to_db(item)

            # Also update in-memory for current session consistency
            prayed_for_data[country_code_item].append(item)

            logging.info(f"Processed item from SQLite queue (ID={item_id_to_delete}, Name={person_name_to_log}), added to prayed_items DB and in-memory for country {COUNTRIES_CONFIG[country_code_item]['name']}")

        else:
            logging.info("No items in SQLite prayer_queue to process.")

    except sqlite3.Error as e:
        logging.error(f"SQLite error in /process_item: {e}")
        if conn:
            conn.rollback() # Rollback on error
    except Exception as e:
        logging.error(f"Unexpected error in /process_item: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

    if item_processed and processed_item_details:
        # Plot map for the specific country of the processed item
        try:
            # Plot map for the specific country of the processed item
            country_code_plot = processed_item_details['country_code']
            hex_map_gdf = HEX_MAP_DATA_STORE.get(country_code_plot)
            post_label_df = POST_LABEL_MAPPINGS_STORE.get(country_code_plot)

            current_sqlite_queue_for_map = []
            temp_conn_map = None # Renamed to avoid conflict with outer conn
            try:
                temp_conn_map = sqlite3.connect(DATABASE_URL)
                temp_conn_map.row_factory = sqlite3.Row
                temp_cursor_map = temp_conn_map.cursor() # Renamed cursor
                temp_cursor_map.execute("SELECT person_name, post_label, country_code FROM prayer_queue")
                current_sqlite_queue_for_map = [dict(item_row) for item_row in temp_cursor_map.fetchall()] # Renamed item
            except sqlite3.Error as e_map_queue:
                logging.error(f"SQLite error fetching queue for map plotting in /process_item: {e_map_queue}")
            finally:
                if temp_conn_map:
                    temp_conn_map.close()

            logging.info(f"[/process_item] Attempting map update for country_code_plot: {country_code_plot}")
            if country_code_plot in prayed_for_data:
                logging.info(f"[/process_item] Size of prayed_for_data['{country_code_plot}'] for map: {len(prayed_for_data[country_code_plot])}")
            logging.info(f"[/process_item] Number of current_sqlite_queue_for_map items for map: {len(current_sqlite_queue_for_map)}")

            if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None: # post_label_df can be empty for IR/ISR
                plot_hex_map_with_hearts(
                    hex_map_gdf,
                    post_label_df,
                    prayed_for_data[country_code_plot],
                    current_sqlite_queue_for_map,
                    country_code_plot
                )
            else:
                logging.warning(f"Map data for {country_code_plot} not loaded or incomplete. Skipping map plot after processing.")
        except Exception as e_map_plotting:
            logging.error(f"Error during map plotting in /process_item for {processed_item_details.get('person_name')}: {e_map_plotting}", exc_info=True)
            # Continue to return success for item processing even if map plotting fails

    return '', 204

@app.route('/statistics/', defaults={'country_code': None})
@app.route('/statistics/<country_code>')
def statistics(country_code):
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
    if country_code is None:
        country_code = list(COUNTRIES_CONFIG.keys())[0]
        return redirect(url_for('prayed_list', country_code=country_code))

    if country_code not in COUNTRIES_CONFIG:
        logging.warning(f"Invalid country code '{country_code}' for prayed list. Redirecting to default.")
        default_country_code = list(COUNTRIES_CONFIG.keys())[0]
        return redirect(url_for('prayed_list', country_code=default_country_code))

    # Data is loaded from DB at startup.
    # No need to call read_log(country_code) here.
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
    return render_template('statistics.html',
                           country_code='overall',
                           country_name='Overall',
                           sorted_party_counts={}, # No specific party breakdown for overall
                           current_party_info={},    # No specific party info for overall
                           all_countries=COUNTRIES_CONFIG)

@app.route('/statistics/data/overall')
def statistics_data_overall():
    total_prayed_count = sum(len(prayed_list) for prayed_list in prayed_for_data.values())
    return jsonify({'Overall': total_prayed_count})

@app.route('/statistics/timedata/overall')
def statistics_timedata_overall():
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
        cursor.execute("DELETE FROM prayer_queue")
        logging.info("Purged all items from SQLite prayer_queue table.")
        cursor.execute("DELETE FROM prayed_items")
        logging.info("Purged all items from SQLite prayed_items table.")
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"SQLite error during purge of prayer_queue and prayed_items tables: {e}")
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

    if not item_country_code_from_form or item_country_code_from_form not in COUNTRIES_CONFIG:
        logging.error(f"Invalid or missing country_code '{item_country_code_from_form}' in put_back request form.")
    else:
        post_label_key_search = post_label_form if post_label_form is not None else ""
        # Standardize post_label for consistency, as done in update_queue
        post_label_to_insert = post_label_key_search if post_label_key_search else None # Used for DB INSERT for prayer_queue

        # No need to call read_log here, data is in memory from initial load.

        item_to_put_back_from_memory = None
        item_index_to_remove_from_memory = -1
        current_country_prayed_list = prayed_for_data.get(item_country_code_from_form, [])

        # Log details of what is being searched for from the form
        logging.info(f"[/put_back] Searching for item to remove: Name='{person_name}', PostLabel(form)='{post_label_form}', StandardizedPostLabelSearch='{post_label_key_search}', Country='{item_country_code_from_form}'")

        for i, item_in_memory in enumerate(current_country_prayed_list):
            mem_person_name = item_in_memory.get('person_name')
            original_mem_post_label = item_in_memory.get('post_label') # Original value from memory
            mem_item_post_label_standardized = original_mem_post_label if original_mem_post_label is not None else ""

            # Detailed log for each item being checked in memory
            logging.debug(f"[/put_back] Checking in-memory item #{i}: Name='{mem_person_name}', OriginalPostLabel='{original_mem_post_label}', StandardizedPostLabel='{mem_item_post_label_standardized}'")

            if mem_person_name == person_name and mem_item_post_label_standardized == post_label_key_search:
                item_to_put_back_from_memory = item_in_memory.copy()
                item_index_to_remove_from_memory = i
                logging.info(f"[/put_back] Found item to remove at index {i}.")
                break
            # Add an else to log if no match for this iteration, for verbosity during debugging
            # else:
            #    logging.debug(f"[/put_back] No match for item #{i}. Name Match: {mem_person_name == person_name}, PostLabel Match: {mem_item_post_label_standardized == post_label_key_search}")

        db_conn = None # Rename to avoid conflict with outer 'conn' if it were used differently
        if item_to_put_back_from_memory:
            # Enhanced logging for put_back
            logging.info(f"Preparing to put back item: {item_to_put_back_from_memory.get('person_name')} for country {item_country_code_from_form}.")
            logging.info(f"Index to remove from memory: {item_index_to_remove_from_memory}.")
            if item_country_code_from_form in prayed_for_data:
                logging.info(f"Current length of prayed_for_data['{item_country_code_from_form}']: {len(prayed_for_data[item_country_code_from_form])}.")
            else:
                logging.warning(f"Country code {item_country_code_from_form} not found in prayed_for_data for length logging.")

            try:
                db_conn = sqlite3.connect(DATABASE_URL)
                cursor = db_conn.cursor()

                # 1. Add item back to SQLite prayer_queue table
                # Ensure all necessary fields are present from item_to_put_back_from_memory
                # 'added_timestamp' for prayer_queue table will be set by default by SQLite
                pq_person_name = item_to_put_back_from_memory['person_name']
                # Use post_label_to_insert which is derived from form, can be None
                pq_post_label = post_label_to_insert
                pq_country_code = item_country_code_from_form # From form, validated
                pq_party = item_to_put_back_from_memory.get('party', 'Other')
                pq_thumbnail = item_to_put_back_from_memory.get('thumbnail', HEART_IMG_PATH)

                cursor.execute('''
                    INSERT INTO prayer_queue (person_name, post_label, country_code, party, thumbnail)
                    VALUES (?, ?, ?, ?, ?)
                ''', (pq_person_name, pq_post_label, pq_country_code, pq_party, pq_thumbnail))
                logging.info(f"Item {pq_person_name} (Post: {pq_post_label}) from {pq_country_code} re-added to SQLite prayer_queue.")

                # 2. Delete item from prayed_items table in DB
                # Use post_label_key_search for precise matching with what was in prayed_for_data (and thus in DB)
                # If post_label_key_search is empty string, it should match NULL in DB if that's how it was stored.
                # The unique index on prayed_items uses (person_name, post_label, country_code).
                # We need to be careful with NULL vs empty string for post_label when deleting.
                # Assuming post_label in prayed_items is NULL if it was originally empty string or None.
                if post_label_key_search == "":
                    cursor.execute('''
                        DELETE FROM prayed_items
                        WHERE person_name = ? AND post_label IS NULL AND country_code = ?
                    ''', (person_name, item_country_code_from_form))
                else:
                    cursor.execute('''
                        DELETE FROM prayed_items
                        WHERE person_name = ? AND post_label = ? AND country_code = ?
                    ''', (person_name, post_label_key_search, item_country_code_from_form))

                logging.info(f"Item {person_name} (Post: {post_label_key_search}) from {item_country_code_from_form} removed from prayed_items DB table.")

                db_conn.commit()

                # 3. Remove from in-memory prayed_for_data
                if item_index_to_remove_from_memory != -1 and item_country_code_from_form in prayed_for_data:
                    prayed_for_data[item_country_code_from_form].pop(item_index_to_remove_from_memory)
                    logging.info(f"Attempted pop from in-memory prayed_for_data for {item_to_put_back_from_memory.get('person_name')}.")
                    logging.info(f"New length of prayed_for_data['{item_country_code_from_form}']: {len(prayed_for_data[item_country_code_from_form])}.")
                elif item_country_code_from_form not in prayed_for_data:
                    logging.warning(f"Cannot pop from prayed_for_data: country code {item_country_code_from_form} not found.")
                else: # item_index_to_remove_from_memory was -1
                    logging.warning(f"Did not pop from prayed_for_data for {item_to_put_back_from_memory.get('person_name')} as item_index_to_remove_from_memory was -1.")
                # Existing logging for successful removal is now covered by the above.

                hex_map_gdf = HEX_MAP_DATA_STORE.get(item_country_code_from_form)
                post_label_df = POST_LABEL_MAPPINGS_STORE.get(item_country_code_from_form)
                current_sqlite_queue_for_map_put_back = get_current_queue_items_from_db() # Fetch updated queue

                if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None:
                    plot_hex_map_with_hearts(
                        hex_map_gdf,
                        post_label_df,
                        prayed_for_data[item_country_code_from_form],
                        current_sqlite_queue_for_map_put_back,
                        item_country_code_from_form
                    )

            except sqlite3.IntegrityError as ie: # Specifically for INSERT into prayer_queue
                logging.warning(f"IntegrityError when re-adding {person_name} to prayer_queue (likely already there): {ie}")
                # If it's already in prayer_queue, we probably should not proceed with removing from prayed_items
                # or prayed_for_data, as it implies a double "put_back" or inconsistent state.
                # For now, just log and don't change other states if this specific error occurs.
                if db_conn: db_conn.rollback()
            except sqlite3.Error as e:
                logging.error(f"SQLite error in /put_back_in_queue for {person_name}: {e}")
                if db_conn: db_conn.rollback()
            except Exception as e_main:
                logging.error(f"Unexpected error in /put_back_in_queue: {e_main}", exc_info=True)
                if db_conn: db_conn.rollback()
            finally:
                if db_conn: db_conn.close()
        else:
            logging.warning(f"Could not find item for {person_name} (Post: {post_label_key_search}) in memory for {item_country_code_from_form} to put back in /put_back.")

    # Redirect logic (unchanged but now at the end of all operations)
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

# Start data initialization in a background thread
logging.info("Creating and starting the initialize_app_data background thread.")
init_thread = threading.Thread(target=initialize_app_data, name="InitDataThread")
init_thread.daemon = True # Make it a daemon so it doesn't block app exit if it hangs, similar to update_queue
init_thread.start()

if __name__ == '__main__':
    # Note: Data initialization is now called globally when the module loads.
    # The initialize_app_data() call is NOT here anymore.
    try:
        # When running locally, Flask's dev server will also run initialize_app_data() once on import.
        port = int(os.environ.get('PORT', 5000))
        app.run(debug=True, host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print('You pressed Ctrl+C! Exiting gracefully...')
        sys.exit(0)
