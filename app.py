from flask import Flask, render_template, jsonify, request, redirect, url_for
import pandas as pd
import psycopg2 # For PostgreSQL
from psycopg2.extras import DictCursor # To fetch rows as dictionaries
import threading
import time
# import queue as Queue # Removed as unused
import logging
from datetime import datetime
import json
import sys
import numpy as np
import os # Already imported, but ensure it's used for os.environ.get
import random

from hex_map import load_hex_map, load_post_label_mapping, plot_hex_map_with_hearts
from utils import format_pretty_timestamp

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# Path for CSVs and other app-bundled data files (remains relative to app)
APP_DATA_DIR = os.path.join(APP_ROOT, 'data')

# DATABASE_URL will be fetched from environment variables, set by Render
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    logging.error("CRITICAL: DATABASE_URL environment variable not set.")
    # Fallback for local development if needed, but not for production
    # For local dev, you might set this env var or use a local default:
    # DATABASE_URL = "postgresql://user:password@host:port/dbname"
    # sys.exit("DATABASE_URL is not set, application cannot start.") # Or handle more gracefully

# Configure logging (LOG_DIR is no longer tied to persistent disk for SQLite)
# For Render, logs are typically handled by the platform via stdout/stderr.
# If file logging is still desired for some reason, a path needs to be defined.
# For simplicity with PaaS, often stdout/stderr is preferred.
# Let's keep file logging for now but make the path simpler or configurable.
# If running locally without /mnt/data, this path would fail.
# We'll use a local log directory for now if PERSISTENT_LOG_DIR was removed.
# However, the previous PERSISTENT_LOG_DIR was for SQLite logs.
# For general app logs, let's use a local 'logs' directory if not on Render.
# On Render, it will use /mnt/data/logs as previously configured if that mount exists
# and is writable. But since we removed disk, let's simplify logging for now.

# Simplified logging setup:
LOG_DIR_APP = os.path.join(APP_ROOT, 'logs_app') # Local logs directory
os.makedirs(LOG_DIR_APP, exist_ok=True)
LOG_FILE_PATH_APP = os.path.join(LOG_DIR_APP, "app.log")

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler(LOG_FILE_PATH_APP),
    logging.StreamHandler() # Keep streaming to console
])

logging.info(f"APP_ROOT set to: {APP_ROOT}")
logging.info(f"APP_DATA_DIR (for CSVs, etc.) set to: {APP_DATA_DIR}")
logging.info(f"DATABASE_URL (from env): {'********' if DATABASE_URL else 'NOT SET'}") # Avoid logging full URL
logging.info(f"LOG_FILE_PATH_APP set to: {LOG_FILE_PATH_APP}")

# app = Flask(__name__) # Removed: App will be created by factory in project/__init__.py

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

def get_db_conn():
    """Establishes a connection to the PostgreSQL database."""
    if not DATABASE_URL:
        logging.error("DATABASE_URL is not set. Cannot connect to the database.")
        raise ValueError("DATABASE_URL not configured")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.Error as e:
        logging.error(f"Error connecting to PostgreSQL database: {e}")
        raise

def init_db():
    """Initializes the PostgreSQL database and creates tables if they don't exist."""
    logging.info("Initializing PostgreSQL database schema...")
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor() as cursor: # Using 'with' ensures cursor is closed
            # Old tables (prayer_queue, prayed_items) are removed as they are obsolete
            # and migrations for them will be removed.

            # Create prayer_candidates table (primary table for PostgreSQL)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS prayer_candidates (
                    id SERIAL PRIMARY KEY,
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
            logging.info("Ensured prayer_candidates table exists.")

            # Create unique index for prayer_candidates
            # PostgreSQL syntax for unique index is similar.
            # Using 'CREATE UNIQUE INDEX IF NOT EXISTS' for idempotency.
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_unique
                ON prayer_candidates (person_name, post_label, country_code);
            ''')
            logging.info("Ensured idx_candidates_unique index exists on prayer_candidates table.")

            conn.commit()
            logging.info("Successfully initialized PostgreSQL database tables and indexes.")
    except psycopg2.Error as e:
        logging.error(f"Error initializing PostgreSQL database: {e}")
        if conn:
            conn.rollback() # Rollback on error
    except ValueError as ve: # Catch DATABASE_URL not set error
        logging.error(str(ve)) # Log the error from get_db_conn
        # Application might not be able to proceed without DB.
    finally:
        if conn:
            conn.close()

# Old migration functions (migrate_to_single_table_schema, migrate_json_logs_to_db)
# are removed as they were SQLite specific and are not needed for the new PostgreSQL setup.

# initialize_app_data() function definition removed.
# Its logic is now orchestrated by project/data_initializer.py:initialize_application(),
# which calls utility functions (init_db, load_prayed_for_data_from_db, update_queue, etc.)
# still residing in this file (app.py), and also populates static data stores.

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
    """Fetches all items from the prayer_candidates table with status 'queued', for PostgreSQL."""
    items = []
    conn = None
    if not DATABASE_URL:
        logging.error("DATABASE_URL not set, cannot fetch queue items.")
        return items
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("""
                SELECT id, person_name, post_label, country_code, party, thumbnail,
                       initial_add_timestamp AS added_timestamp, hex_id
                FROM prayer_candidates
                WHERE status = 'queued'
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            # DictCursor already returns list of dict-like objects
            items = [dict(row) for row in rows]
            logging.info(f"Fetched {len(items)} items with status 'queued' from prayer_candidates (PostgreSQL).")
    except psycopg2.Error as e:
        logging.error(f"PostgreSQL error in get_current_queue_items_from_db: {e}")
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
    # Removed 'with app.app_context():' as this function will be called
    # from initialize_app_data, which is itself called within an app context
    # established by create_app.
    logging.info("Update_queue function execution started.")
    conn = None
    if not DATABASE_URL:
            logging.error("[update_queue] DATABASE_URL not set. Aborting queue update.")
            return
        try:
            logging.info("[update_queue] Attempting to connect to PostgreSQL DB.")
            conn = get_db_conn()
            with conn.cursor(cursor_factory=DictCursor) as cursor:

                # PREEMPTIVELY DELETE EXISTING 'QUEUED' ITEMS
                logging.info("[update_queue] Deleting existing 'queued' items from prayer_candidates table before repopulation.")
                cursor.execute("DELETE FROM prayer_candidates WHERE status = 'queued'")
                logging.info(f"[update_queue] Deleted {cursor.rowcount} existing 'queued' items.")
                # No separate commit here for delete; will commit at the end of all operations.

                logging.info("[update_queue] Proceeding with data population from CSVs.")

                # Fetch identifiers of already prayed individuals
                cursor.execute("SELECT person_name, post_label, country_code FROM prayer_candidates WHERE status = 'prayed'")
                already_prayed_records = cursor.fetchall()
                already_prayed_ids = set()
                for record in already_prayed_records:
                    pn = record['person_name']
                    pl = record['post_label'] if record['post_label'] is not None else ""
                    cc = record['country_code']
                    already_prayed_ids.add((pn, pl, cc))
                logging.info(f"[update_queue] Found {len(already_prayed_ids)} individuals already marked as 'prayed'.")

                all_potential_candidates = []
                # Phase 1: Collect all potential candidates from all countries
                for country_code_collect in COUNTRIES_CONFIG.keys():
                    df_raw = fetch_csv(country_code_collect)
                    if df_raw.empty:
                        logging.warning(f"CSV data for {country_code_collect} is empty. Skipping for initial seeding.")
                        continue

                    num_to_select = COUNTRIES_CONFIG[country_code_collect].get('total_representatives')
                    if num_to_select is None:
                        df_sampled = df_raw.sample(frac=1).reset_index(drop=True)
                    elif len(df_raw) > num_to_select:
                        df_sampled = df_raw.sample(n=num_to_select).reset_index(drop=True)
                    else:
                        df_sampled = df_raw.sample(frac=1).reset_index(drop=True)
                    logging.info(f"Selected {len(df_sampled)} individuals from {country_code_collect} CSV (before filtering prayed).")

                    for index, row in df_sampled.iterrows():
                        if row.get('person_name'):
                            item = row.to_dict()
                            item['country_code'] = country_code_collect
                            item['party'] = item.get('party') or 'Other'

                            current_person_name = item['person_name']
                            current_post_label_raw = item.get('post_label')
                            post_label_for_check = ""
                            if isinstance(current_post_label_raw, str) and current_post_label_raw.strip():
                                post_label_for_check = current_post_label_raw
                            elif current_post_label_raw is None:
                                post_label_for_check = ""

                            candidate_id_tuple = (current_person_name, post_label_for_check, item['country_code'])

                            if candidate_id_tuple not in already_prayed_ids:
                                if isinstance(current_post_label_raw, str) and not current_post_label_raw.strip():
                                    item['post_label'] = None
                                elif current_post_label_raw is None:
                                    item['post_label'] = None

                                image_url = item.get('image_url', HEART_IMG_PATH)
                                if not image_url: image_url = HEART_IMG_PATH
                                item['thumbnail'] = image_url
                                all_potential_candidates.append(item)
                            else:
                                logging.debug(f"[update_queue] Skipped {candidate_id_tuple} from CSV for {country_code_collect}; already prayed for.")
                        else:
                            logging.debug(f"Skipped entry due to missing person_name for {country_code_collect} at index {index} in sampled data: {row.to_dict()}")

                logging.info(f"[update_queue] Collected {len(all_potential_candidates)} new potential candidates after filtering out prayed ones.")
                random.shuffle(all_potential_candidates)

                items_added_to_db_this_cycle = 0
                available_hex_ids_by_country = {}
                random_allocation_countries = ['israel', 'iran']

                for country_code_hex_prep in random_allocation_countries:
                    if country_code_hex_prep not in COUNTRIES_CONFIG: continue
                    hex_map_gdf_prep = HEX_MAP_DATA_STORE.get(country_code_hex_prep)
                    if hex_map_gdf_prep is not None and not hex_map_gdf_prep.empty and 'id' in hex_map_gdf_prep.columns:
                        all_map_hex_ids = set(hex_map_gdf_prep['id'].unique())
                        cursor.execute("""
                            SELECT hex_id FROM prayer_candidates
                            WHERE country_code = %s AND hex_id IS NOT NULL AND (status = 'prayed' OR status = 'queued')
                        """, (country_code_hex_prep,))
                        used_hex_ids = {r['hex_id'] for r in cursor.fetchall()}
                        current_available_hex_ids = list(all_map_hex_ids - used_hex_ids)
                        random.shuffle(current_available_hex_ids)
                        available_hex_ids_by_country[country_code_hex_prep] = current_available_hex_ids
                        logging.info(f"[update_queue] For {country_code_hex_prep}: {len(all_map_hex_ids)} total, {len(used_hex_ids)} used, {len(current_available_hex_ids)} available hexes.")
                    else:
                        logging.warning(f"[update_queue] Hex map data or 'id' column not available for {country_code_hex_prep}.")
                        available_hex_ids_by_country[country_code_hex_prep] = []

                for item_to_process_for_hex in all_potential_candidates:
                    item_country_code = item_to_process_for_hex['country_code']
                    item_to_process_for_hex['hex_id'] = None
                    if item_country_code in random_allocation_countries and available_hex_ids_by_country.get(item_country_code):
                        item_to_process_for_hex['hex_id'] = available_hex_ids_by_country[item_country_code].pop()

                for item_to_add in all_potential_candidates:
                    person_name = item_to_add['person_name']
                    post_label = item_to_add.get('post_label') # Already correctly None if it should be
                    country_code_add = item_to_add['country_code']
                    party_add = item_to_add['party']
                    thumbnail_add = item_to_add['thumbnail']
                    hex_id_to_insert = item_to_add.get('hex_id')
                    current_ts_for_status = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    logging.debug(f"[update_queue] Preparing to insert (PG): Name='{person_name}', Country='{country_code_add}', HexID='{hex_id_to_insert}', PostLabel='{post_label}', Party='{party_add}'")
                    try:
                        # PostgreSQL uses ON CONFLICT ... DO NOTHING for INSERT OR IGNORE
                        # The conflict target must be the column(s) in the unique index.
                        cursor.execute('''
                            INSERT INTO prayer_candidates
                                (person_name, post_label, country_code, party, thumbnail, status, status_timestamp, hex_id)
                            VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s)
                            ON CONFLICT (person_name, post_label, country_code) DO NOTHING
                        ''', (person_name, post_label, country_code_add, party_add, thumbnail_add, current_ts_for_status, hex_id_to_insert))
                        if cursor.rowcount > 0:
                            items_added_to_db_this_cycle += 1
                    except psycopg2.Error as e_insert:
                        logging.error(f"PostgreSQL error during initial seeding for {person_name} ({post_label}): {e_insert}")

                if items_added_to_db_this_cycle > 0:
                    logging.info(f"[update_queue] Successfully prepared to insert {items_added_to_db_this_cycle} new items into prayer_candidates (PostgreSQL).")
                logging.info(f"[update_queue] Attempted to insert candidates. Number of rows affected reported by cursor: {items_added_to_db_this_cycle} (Note: ON CONFLICT DO NOTHING might show 0 if all conflicted).")

                cursor.execute("SELECT COUNT(id) FROM prayer_candidates WHERE status = 'queued'")
                count_result = cursor.fetchone()
                current_db_candidates_size = count_result[0] if count_result else 0
                logging.info(f"Initial seeding process complete. Current 'queued' items in prayer_candidates (PostgreSQL): {current_db_candidates_size}")

            conn.commit() # Commit all operations (delete and inserts)
            logging.info(f"[update_queue] Database commit successful for update_queue operations.")

        except psycopg2.Error as e: # psycopg2 specific error
            logging.error(f"[update_queue] A PostgreSQL error occurred: {e}", exc_info=True)
            if conn: conn.rollback()
        except Exception as e_gen: # General exception
            logging.error(f"[update_queue] An critical error occurred during execution: {e_gen}", exc_info=True)
            if conn: conn.rollback()
        finally:
            logging.info("[update_queue] Reached finally block, will close PostgreSQL connection if open.")
            if conn:
                conn.close()
                logging.debug("PostgreSQL connection closed in update_queue.")
        # The while True loop and time.sleep(90) are removed.

# All routes previously in app.py are now moved to their respective blueprints
# within the 'project/blueprints/' directory.
# The Flask 'app' instance is created by the factory in 'project/__init__.py',
# and blueprints are registered there.

# Utility functions like load_prayed_for_data_from_db, get_current_queue_items_from_db, etc.,
# remain in this file to be imported by blueprints or services if needed directly,
# though ideally, they would also be part of a service layer. For now, they stay here.

def load_prayed_for_data_from_db():
    """Loads all prayed-for items from the PostgreSQL database into the global prayed_for_data."""
    global prayed_for_data
    for country in COUNTRIES_CONFIG.keys():
        prayed_for_data[country] = []

    conn = None
    if not DATABASE_URL:
        logging.error("DATABASE_URL not set, cannot load prayed for data.")
        return
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("""
                SELECT person_name, post_label, country_code, party, thumbnail,
                       status_timestamp AS timestamp, hex_id
                FROM prayer_candidates
                WHERE status = 'prayed'
            """)
            rows = cursor.fetchall()
            loaded_count = 0
            for row_data in rows:
                item = dict(row_data)
                country_code_load = item.get('country_code')
                if country_code_load in prayed_for_data:
                    prayed_for_data[country_code_load].append(item)
                    loaded_count +=1
                else:
                    logging.warning(f"Found item in prayer_candidates (status='prayed') with unknown country_code: {country_code_load} - Item: {item.get('person_name')}")
            logging.info(f"Loaded {loaded_count} items with status 'prayed' from prayer_candidates (PostgreSQL) into memory.")
        # Optional: detailed logging per country
        # for country_code_key in prayed_for_data:
        #      logging.debug(f"Country {country_code_key} has {len(prayed_for_data[country_code_key])} prayed items in memory after DB load.")
    except psycopg2.Error as e:
        logging.error(f"PostgreSQL error in load_prayed_for_data_from_db: {e}")
    except Exception as e_gen:
        logging.error(f"Unexpected error in load_prayed_for_data_from_db: {e_gen}", exc_info=True)
    finally:
        if conn:
            conn.close()

def reload_single_country_prayed_data_from_db(country_code_to_reload):
    """Reloads prayed-for items for a single country from PostgreSQL into global prayed_for_data."""
    global prayed_for_data
    if country_code_to_reload not in prayed_for_data:
        logging.warning(f"[reload_single_country_prayed_data_from_db] Invalid country_code: {country_code_to_reload}")
        return

    logging.info(f"[reload_single_country_prayed_data_from_db] Reloading prayed_for_data for country: {country_code_to_reload} (PostgreSQL)")
    prayed_for_data[country_code_to_reload] = []

    conn = None
    if not DATABASE_URL:
        logging.error(f"DATABASE_URL not set, cannot reload prayed for data for {country_code_to_reload}.")
        return
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("""
                SELECT person_name, post_label, country_code, party, thumbnail,
                       status_timestamp AS timestamp, hex_id
                FROM prayer_candidates
                WHERE status = 'prayed' AND country_code = %s
            """, (country_code_to_reload,))
            rows = cursor.fetchall()
            loaded_count = 0
            for row_data in rows:
                item = dict(row_data)
                prayed_for_data[country_code_to_reload].append(item)
                loaded_count += 1
            logging.info(f"[reload_single_country_prayed_data_from_db] Reloaded {loaded_count} 'prayed' items for {country_code_to_reload} (PostgreSQL).")
    except psycopg2.Error as e:
        logging.error(f"[reload_single_country_prayed_data_from_db] PostgreSQL error for {country_code_to_reload}: {e}")
    except Exception as e_gen:
        logging.error(f"[reload_single_country_prayed_data_from_db] Unexpected error for {country_code_to_reload}: {e_gen}", exc_info=True)
    finally:
        if conn:
            conn.close()

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
    item_id_to_process = None

    if not item_id_to_process_str:
        logging.error("/process_item: Missing 'item_id' in POST request.")
        return jsonify(error="Missing item_id"), 400
    try:
        item_id_to_process = int(item_id_to_process_str)
    except ValueError:
        logging.error(f"/process_item: Invalid 'item_id' format: {item_id_to_process_str}.")
        return jsonify(error="Invalid item_id format"), 400

    if not DATABASE_URL:
        logging.error("/process_item: DATABASE_URL not set.")
        return jsonify(error="Database not configured"), 500

    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            # Fetch the item's details first
            cursor.execute("SELECT * FROM prayer_candidates WHERE id = %s AND status = 'queued'", (item_id_to_process,))
            row = cursor.fetchone()

            if row:
                item_to_process = dict(row)
                person_name_to_log = item_to_process.get('person_name', 'N/A')
                country_code_item = item_to_process['country_code']
                logging.info(f"Attempting to process item ID={item_id_to_process} (Name='{person_name_to_log}', HexID={item_to_process.get('hex_id')}) for PostgreSQL.")

                new_status_timestamp = datetime.now()
                # Using %s for placeholders in PostgreSQL
                cursor.execute("""
                    UPDATE prayer_candidates
                    SET status = 'prayed', status_timestamp = %s
                    WHERE id = %s AND status = 'queued'
                """, (new_status_timestamp.strftime('%Y-%m-%d %H:%M:%S'), item_id_to_process))

                if cursor.rowcount > 0:
                    conn.commit()
                    logging.info(f"[process_item] Successfully committed DB update for item ID={item_id_to_process} to 'prayed' (PostgreSQL).")
                    item_processed = True
                    processed_item_details = {
                        'person_name': item_to_process['person_name'],
                        'post_label': item_to_process.get('post_label'),
                        'country_code': country_code_item,
                        'party': item_to_process.get('party'),
                        'thumbnail': item_to_process.get('thumbnail'),
                        'timestamp': new_status_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        'hex_id': item_to_process.get('hex_id')
                    }
                else:
                    conn.rollback() # Rollback if update didn't affect rows (e.g. item status changed)
                    logging.warning(f"Item ID={item_id_to_process} (Name='{person_name_to_log}') was not updated to 'prayed' (PostgreSQL); status may have changed or item no longer exists as 'queued'.")
            else:
                logging.warning(f"/process_item: Item with ID={item_id_to_process} not found or not in 'queued' state (PostgreSQL).")

    except psycopg2.Error as e:
        logging.error(f"PostgreSQL error in /process_item for ID={item_id_to_process}: {e}", exc_info=True)
        if conn: conn.rollback()
    except Exception as e_gen: # Renamed 'e' to 'e_gen' to avoid conflict if psycopg2.Error is aliased as e
        logging.error(f"Unexpected error in /process_item for ID={item_id_to_process}: {e_gen}", exc_info=True)
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
    if not DATABASE_URL:
        logging.error("/purge_queue: DATABASE_URL not set.")
        # Potentially redirect with error, or just log and proceed to clear memory / repopulate (which will fail on DB ops)
        # For now, let it try to connect and fail, to keep behavior somewhat consistent.
        pass # Fall through to try-catch block

    try:
        conn = get_db_conn()
        with conn.cursor() as cursor: # No DictCursor needed for DELETE
            cursor.execute("DELETE FROM prayer_candidates")
            conn.commit()
            logging.info(f"Purged {cursor.rowcount} items from PostgreSQL prayer_candidates table.")
    except psycopg2.Error as e:
        logging.error(f"PostgreSQL error during purge of prayer_candidates table: {e}")
        if conn:
            conn.rollback()
    except Exception as e_gen: # Catch other errors like get_db_conn failing
        logging.error(f"Unexpected error during purge_queue DB operations: {e_gen}", exc_info=True)
        if conn: # conn might not be set if get_db_conn failed
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

        # --- START OF DIAGNOSTIC BLOCK (Adapted for PostgreSQL) ---
        # This diagnostic block can be helpful but adds overhead. Consider removing or commenting out for production.
        diag_conn = None
        if DATABASE_URL: # Only run if DB is configured
            try:
                diag_conn = get_db_conn()
                with diag_conn.cursor(cursor_factory=DictCursor) as diag_cursor:
                    diag_select_sql = "SELECT * FROM prayer_candidates WHERE person_name = %s AND country_code = %s"
                    diag_params = [person_name, item_country_code_from_form]

                    if is_post_label_null_in_db_query:
                        diag_select_sql += " AND post_label IS NULL"
                    else:
                        diag_select_sql += " AND post_label = %s"
                        diag_params.append(query_post_label_value_for_db)

                    logging.debug(f"[DIAGNOSTIC PG] Executing SELECT: {diag_select_sql} with params {diag_params}")
                    diag_cursor.execute(diag_select_sql, tuple(diag_params))
                    diagnostic_row = diag_cursor.fetchone()

                    if diagnostic_row:
                        logging.info(f"[DIAGNOSTIC PG] Found existing record for {person_name} (PostLabel form: '{post_label_form}', Queried as: {log_display_post_label}, Country: {item_country_code_from_form}): Status='{diagnostic_row['status']}', DB PostLabel='{diagnostic_row['post_label']}', ID='{diagnostic_row['id']}'")
                    else:
                        logging.warning(f"[DIAGNOSTIC PG] No record found for {person_name} (PostLabel form: '{post_label_form}', Queried as: {log_display_post_label}, Country: {item_country_code_from_form}).")
            except psycopg2.Error as e_diag:
                logging.error(f"[DIAGNOSTIC PG] PostgreSQL error: {e_diag}", exc_info=True)
            except Exception as e_diag_generic:
                logging.error(f"[DIAGNOSTIC PG] Generic error: {e_diag_generic}", exc_info=True)
            finally:
                if diag_conn: diag_conn.close()
        # --- END OF DIAGNOSTIC BLOCK ---

        # Database operation
        db_conn = None
        updated_in_db = False
        if not DATABASE_URL:
            logging.error("/put_back_in_queue: DATABASE_URL not set. Cannot perform DB operation.")
        else:
            try:
                db_conn = get_db_conn()
                with db_conn.cursor(cursor_factory=DictCursor) as cursor: # Ensure DictCursor for fetching item_to_update_details
                    new_status_timestamp = datetime.now()

                    select_sql_for_put_back = "SELECT id, hex_id FROM prayer_candidates WHERE person_name = %s AND country_code = %s AND status = 'prayed'"
                    params_for_put_back = [person_name, item_country_code_from_form]
                    if is_post_label_null_in_db_query:
                        select_sql_for_put_back += " AND post_label IS NULL"
                    else:
                        select_sql_for_put_back += " AND post_label = %s"
                        params_for_put_back.append(query_post_label_value_for_db)

                    cursor.execute(select_sql_for_put_back, tuple(params_for_put_back))
                    item_to_update_details = cursor.fetchone()

                    if not item_to_update_details:
                        logging.warning(f"Item {person_name} (Post: {log_display_post_label}) for {item_country_code_from_form} not found with status 'prayed' for put_back (PostgreSQL). No DB update made.")
                        # updated_in_db remains False
                    else:
                        current_hex_id = item_to_update_details['hex_id']
                        item_db_id = item_to_update_details['id']
                        hex_id_to_set = current_hex_id

                        random_allocation_countries = ['israel', 'iran']
                        if item_country_code_from_form in random_allocation_countries and not current_hex_id:
                            logging.info(f"Item {person_name} in {item_country_code_from_form} has NULL hex_id. Attempting to assign one (PostgreSQL).")
                            hex_map_gdf_put_back = HEX_MAP_DATA_STORE.get(item_country_code_from_form)
                            if hex_map_gdf_put_back is not None and not hex_map_gdf_put_back.empty and 'id' in hex_map_gdf_put_back.columns:
                                all_map_hex_ids_pb = set(hex_map_gdf_put_back['id'].unique())
                                cursor.execute("""
                                    SELECT hex_id FROM prayer_candidates
                                    WHERE country_code = %s AND hex_id IS NOT NULL AND id != %s
                                """, (item_country_code_from_form, item_db_id))
                                used_hex_ids_pb = {row['hex_id'] for row in cursor.fetchall()}
                                available_hex_ids_pb = list(all_map_hex_ids_pb - used_hex_ids_pb)
                                if available_hex_ids_pb:
                                    random.shuffle(available_hex_ids_pb)
                                    hex_id_to_set = available_hex_ids_pb.pop()
                                    logging.info(f"Assigned new hex_id {hex_id_to_set} to {person_name} during put_back (PostgreSQL).")
                                else:
                                    logging.warning(f"No available hex_ids to assign to {person_name} in {item_country_code_from_form} during put_back (PostgreSQL).")
                            else:
                                logging.warning(f"Hex map data not available for {item_country_code_from_form} during put_back hex_id assignment (PostgreSQL).")

                        cursor.execute("""
                            UPDATE prayer_candidates
                            SET status = 'queued', status_timestamp = %s, hex_id = %s
                            WHERE id = %s
                        """, (new_status_timestamp.strftime('%Y-%m-%d %H:%M:%S'), hex_id_to_set, item_db_id))

                        if cursor.rowcount > 0:
                            db_conn.commit()
                            logging.info(f"Item {person_name} (ID: {item_db_id}, Post: {log_display_post_label}) for {item_country_code_from_form} status updated to 'queued', hex_id set to {hex_id_to_set} (PostgreSQL).")
                            updated_in_db = True
                        else:
                            db_conn.rollback() # Rollback if update failed
                            logging.error(f"Failed to update item {person_name} (ID: {item_db_id}) (PostgreSQL). This should not happen if item was found.")

            except psycopg2.Error as e:
                logging.error(f"PostgreSQL error in /put_back_in_queue for {person_name}: {e}")
                if db_conn: db_conn.rollback()
            except Exception as e_gen: # Generic error catch
                 logging.error(f"Unexpected error in /put_back_in_queue for {person_name}: {e_gen}", exc_info=True)
                 if db_conn: db_conn.rollback() # Ensure rollback on generic errors too
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
# logging.info("Starting synchronous application data initialization at module load...")
# initialize_app_data() # Removed: This will be called by the app factory
# logging.info("Synchronous application data initialization finished at module load.")

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
