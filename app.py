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

# Removed migrate_json_logs_to_db() function as it was SQLite-specific and obsolete.

def get_current_queue_items_from_db():
    """Fetches all items from the prayer_candidates table with status 'queued', for PostgreSQL."""
    items = []
    conn = None
    if not DATABASE_URL:  # Ensure this line and below are consistently indented
        logging.error("DATABASE_URL not set, cannot fetch queue items.")
        return items
    try:  # This try should be at the same indentation level as the 'if not DATABASE_URL:' above
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
    try: # This try block should be at the same indentation level as the 'if' block above it.
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
        if conn:
            conn.rollback()
    except Exception as e_gen: # General exception
        logging.error(f"[update_queue] An critical error occurred during execution: {e_gen}", exc_info=True)
        if conn:
            conn.rollback()
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

# All routes previously in app.py are now moved to their respective blueprints
# within the 'project/blueprints/' directory.
# The Flask 'app' instance is created by the factory in 'project/__init__.py',
# and blueprints are registered there.

# The __main__ block is removed as the application should be run via 'run.py'
# or a WSGI server like Gunicorn pointing to the app factory.
