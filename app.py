from flask import Flask, render_template, jsonify, request, redirect, url_for
import pandas as pd
import psycopg2  # For PostgreSQL
from psycopg2.extras import DictCursor  # To fetch rows as dictionaries
import threading
import time
import logging
from datetime import datetime
import json
import sys
import numpy as np
import os  # Already imported, but ensure it's used for os.environ.get
import random

from hex_map import load_hex_map, load_post_label_mapping, plot_hex_map_with_hearts
from utils import format_pretty_timestamp

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_DATA_DIR = os.path.join(APP_ROOT, 'data')

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
LOG_DIR_APP = os.path.join(APP_ROOT, 'logs_app')
os.makedirs(LOG_DIR_APP, exist_ok=True)
LOG_FILE_PATH_APP = os.path.join(LOG_DIR_APP, "app.log")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH_APP),
        logging.StreamHandler()
    ]
)

logging.info(f"APP_ROOT set to: {APP_ROOT}")
logging.info(f"APP_DATA_DIR (for CSVs, etc.) set to: {APP_DATA_DIR}")
logging.info(f"DATABASE_URL (from env): {'********' if DATABASE_URL else 'NOT SET'}")
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
        'name': 'Israel',
        'flag': '🇮🇱'
    },
    'iran': {
        'csv_path': os.path.join(APP_DATA_DIR, '20240510_iran.csv'),
        'geojson_path': os.path.join(APP_DATA_DIR, 'IRN_IslamicParliamentofIran_290_v2.geojson'),
        'map_shape_path': os.path.join(APP_DATA_DIR, 'IRN_IslamicParliamentofIran_290_v2.geojson'),
        'post_label_mapping_path': None,
        'total_representatives': 290,
        'name': 'Iran',
        'flag': '🇮🇷'
    }
}

HEART_IMG_PATH = 'static/heart_icons/heart_red.png'

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
    }
}

# data_queue = Queue.Queue() # Removed, SQLite is now used for queueing
# logging.info(f"Global data_queue object created with id: {id(data_queue)}") # Removed

# Global data structures
prayed_for_data = {country: [] for country in COUNTRIES_CONFIG.keys()}
deputies_data = {
    country: {'with_images': [], 'without_images': []}
    for country in COUNTRIES_CONFIG.keys()
}
HEX_MAP_DATA_STORE = {}
POST_LABEL_MAPPINGS_STORE = {}


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
        with conn.cursor() as cursor:
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

            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_unique
                ON prayer_candidates (person_name, post_label, country_code);
            ''')
            logging.info("Ensured idx_candidates_unique index exists.")

            conn.commit()
            logging.info("Successfully initialized PostgreSQL database tables and indexes.")
    except psycopg2.Error as e:
        logging.error(f"Error initializing PostgreSQL database: {e}")
        if conn:
            conn.rollback()
    except ValueError as ve:
        logging.error(str(ve))
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
    """Fetches all items with status 'queued'."""
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
            items = [dict(row) for row in rows]
            logging.info(f"Fetched {len(items)} queued items.")
    except psycopg2.Error as e:
        logging.error(f"Error fetching queue items: {e}")
    finally:
        if conn:
            conn.close()
    return items


# Function to fetch the CSV
def fetch_csv(country_code):
    logging.debug(f"Fetching CSV data for {country_code}")
    csv_path = COUNTRIES_CONFIG[country_code]['csv_path']
    try:
        df = pd.read_csv(csv_path)
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
    for _, row in csv_data.iterrows():
        image_url = row.get('image_url')
        processed_row = row.to_dict()
        if not image_url:
            country_deputies_without_images.append(processed_row)
            continue
        processed_row['Image'] = image_url
        country_deputies_with_images.append(processed_row)
        logging.debug(f"Image URL for {row.get('person_name')}: {image_url}")
    deputies_data[country_code]['with_images'] = country_deputies_with_images
    deputies_data[country_code]['without_images'] = country_deputies_without_images
    if country_deputies_without_images:
        names = ', '.join(dep.get('person_name', 'N/A') for dep in country_deputies_without_images)
        logging.info(f"No images for: {names}")

# Removed old global csv_data, deputies_with_images, deputies_without_images,
# and their initial loading/processing. This is now handled in the
# __main__ block or by specific calls.

# Function to periodically update the queue
def update_queue():
    """Periodically repopulates the queue from CSV into PostgreSQL."""
    logging.info("update_queue started.")
    if not DATABASE_URL:
        logging.error("DATABASE_URL not set. Aborting queue update.")
        return

    conn = None
    try:
        logging.info("Connecting to PostgreSQL for queue update.")
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            # Delete existing queued
            cursor.execute("DELETE FROM prayer_candidates WHERE status = 'queued'")
            logging.info(f"Deleted {cursor.rowcount} existing queued items.")

            # Fetch already prayed
            cursor.execute("""
                SELECT person_name, post_label, country_code 
                FROM prayer_candidates 
                WHERE status = 'prayed'
            """)
            already = { (r['person_name'], r['post_label'] or "", r['country_code']) for r in cursor.fetchall() }
            logging.info(f"{len(already)} already prayed records loaded.")

            all_candidates = []
            for country in COUNTRIES_CONFIG:
                df_raw = fetch_csv(country)
                if df_raw.empty:
                    logging.warning(f"No CSV data for {country}, skipping.")
                    continue

                total = COUNTRIES_CONFIG[country]['total_representatives']
                if len(df_raw) > total:
                    df_sampled = df_raw.sample(n=total).reset_index(drop=True)
                else:
                    df_sampled = df_raw.sample(frac=1).reset_index(drop=True)
                logging.info(f"Selected {len(df_sampled)} for {country} before filtering.")

                for _, row in df_sampled.iterrows():
                    name = row.get('person_name')
                    if not name:
                        logging.debug("Skipped row with no person_name.")
                        continue

                    post_label = row.get('post_label') or ""
                    key = (name, post_label, country)
                    if key in already:
                        logging.debug(f"Skipping already prayed {key}.")
                        continue

                    item = row.to_dict()
                    item['country_code'] = country
                    item['party'] = item.get('party') or 'Other'
                    thumb = item.get('image_url') or HEART_IMG_PATH
                    item['thumbnail'] = thumb
                    all_candidates.append(item)

            logging.info(f"{len(all_candidates)} new candidates after filtering.")

            random.shuffle(all_candidates)

            # Precompute available hex_ids per country
            avail_hex = {}
            for c in ['israel', 'iran']:
                gdf = HEX_MAP_DATA_STORE.get(c)
                if gdf is not None and 'id' in gdf.columns:
                    total_ids = set(gdf['id'])
                    cursor.execute("""
                        SELECT hex_id FROM prayer_candidates
                        WHERE country_code = %s AND hex_id IS NOT NULL
                    """, (c,))
                    used = {r['hex_id'] for r in cursor.fetchall()}
                    free = list(total_ids - used)
                    random.shuffle(free)
                    avail_hex[c] = free
                    logging.info(f"For {c}: {len(total_ids)} total, {len(used)} used, {len(free)} free.")
                else:
                    avail_hex[c] = []

            # Assign hex_id
            for item in all_candidates:
                c = item['country_code']
                item['hex_id'] = None
                if c in avail_hex and avail_hex[c]:
                    item['hex_id'] = avail_hex[c].pop()

            # Insert into DB
            added = 0
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for item in all_candidates:
                cursor.execute('''
                    INSERT INTO prayer_candidates
                        (person_name, post_label, country_code, party, thumbnail, status, status_timestamp, hex_id)
                    VALUES (%s,%s,%s,%s,%s,'queued',%s,%s)
                    ON CONFLICT (person_name, post_label, country_code) DO NOTHING
                ''', (
                    item['person_name'], item.get('post_label'), item['country_code'],
                    item['party'], item['thumbnail'], now, item.get('hex_id')
                ))
                if cursor.rowcount > 0:
                    added += 1

            logging.info(f"Inserted {added} new queued items.")
            cursor.execute("SELECT COUNT(*) FROM prayer_candidates WHERE status = 'queued'")
            total_q = cursor.fetchone()[0]
            logging.info(f"Now {total_q} items queued in DB.")

        conn.commit()
        logging.info("update_queue DB commit successful.")

    except Exception as e:
        logging.error(f"Error in update_queue: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
            logging.debug("DB connection closed in update_queue.")

# All routes previously in app.py are now moved to their respective blueprints
# within the 'project/blueprints/' directory.
# The Flask 'app' instance is created by the factory in 'project/__init__.py',
# and blueprints are registered there.

# Utility functions like load_prayed_for_data_from_db, get_current_queue_items_from_db, etc.,
# remain in this file to be imported by blueprints or services if needed directly,
# though ideally, they would also be part of a service layer. For now, they stay here.

def load_prayed_for_data_from_db():
    """Loads all 'prayed' items into memory."""
    global prayed_for_data
    for country in COUNTRIES_CONFIG:
        prayed_for_data[country] = []

    if not DATABASE_URL:
        logging.error("DATABASE_URL not set, cannot load prayed data.")
        return

    conn = None
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
            count = 0
            for row in rows:
                item = dict(row)
                cc = item['country_code']
                if cc in prayed_for_data:
                    prayed_for_data[cc].append(item)
                    count += 1
                else:
                    logging.warning(f"Unknown country {cc} in prayed data.")
            logging.info(f"Loaded {count} prayed items into memory.")
    except Exception as e:
        logging.error(f"Error loading prayed data: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


def reload_single_country_prayed_data_from_db(country):
    """Reloads 'prayed' items for one country."""
    global prayed_for_data
    if country not in prayed_for_data:
        logging.warning(f"Invalid country code: {country}")
        return

    prayed_for_data[country] = []
    if not DATABASE_URL:
        logging.error("DATABASE_URL not set, cannot reload prayed data.")
        return

    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("""
                SELECT person_name, post_label, country_code, party, thumbnail,
                       status_timestamp AS timestamp, hex_id
                FROM prayer_candidates
                WHERE status = 'prayed' AND country_code = %s
            """, (country,))
            rows = cursor.fetchall()
            for row in rows:
                prayed_for_data[country].append(dict(row))
            logging.info(f"Reloaded {len(rows)} prayed items for {country}.")
    except Exception as e:
        logging.error(f"Error reloading prayed data for {country}: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

# The Flask app is created by a factory in project/__init__.py
# All route functions below assume that factory sets up `app`

@app.route('/')
def home():
    load_prayed_for_data_from_db()
    total_prayed = sum(len(v) for v in prayed_for_data.values())
    total_all = sum(cfg['total_representatives'] for cfg in COUNTRIES_CONFIG.values())
    remaining = total_all - total_prayed

    queue = get_current_queue_items_from_db()
    current = queue[0] if queue else None

    map_country = current['country_code'] if current else list(COUNTRIES_CONFIG.keys())[0]

    hex_gdf = HEX_MAP_DATA_STORE.get(map_country)
    post_df = POST_LABEL_MAPPINGS_STORE.get(map_country)

    if hex_gdf is not None and post_df is not None:
        plot_hex_map_with_hearts(
            hex_gdf,
            post_df,
            prayed_for_data[map_country],
            queue,
            map_country
        )
    else:
        logging.warning(f"Cannot plot map for {map_country}: data missing.")

    deputies_with = deputies_data[map_country]['with_images']
    deputies_without = deputies_data[map_country]['without_images']

    return render_template(
        'index.html',
        remaining=remaining,
        current=current,
        queue=queue,
        deputies_with_images=deputies_with,
        deputies_without_images=deputies_without,
        current_country_name=COUNTRIES_CONFIG[map_country]['name'],
        all_countries=COUNTRIES_CONFIG,
        default_country_code=list(COUNTRIES_CONFIG.keys())[0],
        initial_map_country_code=map_country
    )

@app.route('/generate_map_for_country/<country_code>')
def generate_map_for_country(country_code):
    if country_code not in COUNTRIES_CONFIG:
        return jsonify(error='Invalid country code'), 404

    hex_gdf = HEX_MAP_DATA_STORE.get(country_code)
    post_df = POST_LABEL_MAPPINGS_STORE.get(country_code)
    prayed = prayed_for_data.get(country_code, [])
    queue = get_current_queue_items_from_db()

    if hex_gdf is None or post_df is None:
        return jsonify(error=f'Map data not available for {country_code}'), 500

    plot_hex_map_with_hearts(hex_gdf, post_df, prayed, queue, country_code)
    return jsonify(status=f'Map generated for {country_code}'), 200


@app.route('/queue')
def queue_page():
    items = get_current_queue_items_from_db()
    logging.info(f"/queue: {len(items)} items")
    return render_template('queue.html', queue=items, all_countries=COUNTRIES_CONFIG, HEART_IMG_PATH=HEART_IMG_PATH)

@app.route('/queue/json')
def get_queue_json():
    items = get_current_queue_items_from_db()
    for it in items:
        cc = it.get('country_code')
        it['country_name'] = COUNTRIES_CONFIG.get(cc, {}).get('name', 'Unknown Country')
    return jsonify(items)

@app.route('/process_item', methods=['POST'])
def process_item():
    item_id_str = request.form.get('item_id')
    if not item_id_str:
        return jsonify(error="Missing item_id"), 400
    try:
        item_id = int(item_id_str)
    except ValueError:
        return jsonify(error="Invalid item_id format"), 400

    if not DATABASE_URL:
        return jsonify(error="Database not configured"), 500

    conn = None
    processed = False
    details = {}

    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM prayer_candidates WHERE id = %s AND status = 'queued'",
                (item_id,)
            )
            row = cursor.fetchone()
            if row:
                rec = dict(row)
                cursor.execute("""
                    UPDATE prayer_candidates
                    SET status = 'prayed', status_timestamp = %s
                    WHERE id = %s
                """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), item_id))
                if cursor.rowcount > 0:
                    conn.commit()
                    processed = True
                    details = {
                        'person_name': rec['person_name'],
                        'post_label': rec.get('post_label'),
                        'country_code': rec['country_code']
                    }
                else:
                    conn.rollback()
    except Exception as e:
        logging.error(f"/process_item error: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

    if processed:
        reload_single_country_prayed_data_from_db(details['country_code'])
        hex_gdf = HEX_MAP_DATA_STORE.get(details['country_code'])
        post_df = POST_LABEL_MAPPINGS_STORE.get(details['country_code'])
        queue = get_current_queue_items_from_db()
        if hex_gdf and post_df:
            plot_hex_map_with_hearts(
                hex_gdf,
                post_df,
                prayed_for_data[details['country_code']],
                queue,
                details['country_code']
            )
    return ('', 204)

@app.route('/statistics/', defaults={'country_code': None})
@app.route('/statistics/<country_code>')
def statistics(country_code):
    load_prayed_for_data_from_db()
    if country_code is None:
        country_code = list(COUNTRIES_CONFIG.keys())[0]
        return redirect(url_for('statistics', country_code=country_code))

    if country_code not in COUNTRIES_CONFIG:
        return redirect(url_for('statistics', country_code=list(COUNTRIES_CONFIG.keys())[0]))

    counts = {}
    info = party_info.get(country_code, {})
    for item in prayed_for_data[country_code]:
        short = info.get(item.get('party'), info.get('Other'))['short_name']
        counts[short] = counts.get(short, 0) + 1

    sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return render_template(
        'statistics.html',
        sorted_party_counts=sorted_counts,
        current_party_info=info,
        all_countries=COUNTRIES_CONFIG,
        country_code=country_code,
        country_name=COUNTRIES_CONFIG[country_code]['name']
    )


@app.route('/statistics/data/<country_code>')
def statistics_data(country_code):
    load_prayed_for_data_from_db()
    if country_code not in COUNTRIES_CONFIG:
        return jsonify({"error": "Country not found"}), 404

    counts = {}
    info = party_info.get(country_code, {})
    for item in prayed_for_data[country_code]:
        short = info.get(item.get('party'), info.get('Other'))['short_name']
        counts[short] = counts.get(short, 0) + 1

    return jsonify(counts)

@app.route('/statistics/timedata/<country_code>')
def statistics_timedata(country_code):
    load_prayed_for_data_from_db()
    if country_code not in COUNTRIES_CONFIG:
        return jsonify({"error": "Country not found"}), 404

    timestamps = []
    values = []
    for item in prayed_for_data[country_code]:
        timestamps.append(item.get('timestamp'))
        values.append({
            'place': item.get('post_label'),
            'person': item.get('person_name'),
            'party': item.get('party')
        })
    return jsonify({'timestamps': timestamps, 'values': values, 'country_name': COUNTRIES_CONFIG[country_code]['name']})


@app.route('/prayed/', defaults={'country_code': None})
@app.route('/prayed/<country_code>')
def prayed_list(country_code):
    load_prayed_for_data_from_db()
    if country_code is None or country_code not in COUNTRIES_CONFIG:
        return redirect(url_for('prayed_list', country_code=list(COUNTRIES_CONFIG.keys())[0]))

    items = []
    info = party_info.get(country_code, {})
    for rec in prayed_for_data[country_code]:
        item = rec.copy()
        item['formatted_timestamp'] = format_pretty_timestamp(item.get('timestamp'))
        pdata = info.get(item.get('party'), info.get('Other'))
        item['party_class'] = pdata['short_name'].lower().replace(' ', '-').replace('&', 'and')
        item['party_color'] = pdata['color']
        items.append(item)

    return render_template(
        'prayed.html',
        prayed_for_list=items,
        country_code=country_code,
        country_name=COUNTRIES_CONFIG[country_code]['name'],
        all_countries=COUNTRIES_CONFIG
    )


@app.route('/statistics/overall')
def statistics_overall():
    load_prayed_for_data_from_db()
    return render_template(
        'statistics.html',
        country_code='overall',
        country_name='Overall',
        sorted_party_counts={},
        current_party_info={},
        all_countries=COUNTRIES_CONFIG
    )

@app.route('/statistics/data/overall')
def statistics_data_overall():
    load_prayed_for_data_from_db()
    total = sum(len(v) for v in prayed_for_data.values())
    return jsonify({'Overall': total})


@app.route('/statistics/timedata/overall')
def statistics_timedata_overall():
    load_prayed_for_data_from_db()
    all_items = []
    for v in prayed_for_data.values():
        all_items.extend(v)
    all_items.sort(key=lambda x: x.get('timestamp', ''))
    timestamps = [i.get('timestamp') for i in all_items if i.get('timestamp')]
    values = [
        {
            'place': i.get('post_label'),
            'person': i.get('person_name'),
            'country': COUNTRIES_CONFIG[i['country_code']]['name']
        }
        for i in all_items
    ]
    return jsonify({'timestamps': timestamps, 'values': values, 'country_name': 'Overall'})


@app.route('/prayed/overall')
def prayed_list_overall():
    load_prayed_for_data_from_db()
    overall = []
    for cc, items in prayed_for_data.items():
        for i in items:
            d = i.copy()
            d['country_name_display'] = COUNTRIES_CONFIG.get(cc, {}).get('name', 'Unknown Country')
            d['formatted_timestamp'] = format_pretty_timestamp(i.get('timestamp'))
            overall.append(d)
    overall.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return render_template(
        'prayed.html',
        prayed_for_list=overall,
        country_code='overall',
        country_name='Overall',
        all_countries=COUNTRIES_CONFIG,
        current_party_info={}
    )

@app.route('/purge')
def purge_queue():
    conn = None
    if DATABASE_URL:
        try:
            conn = get_db_conn()
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM prayer_candidates")
                conn.commit()
                logging.info(f"Purged {cursor.rowcount} items from DB.")
        except Exception as e:
            logging.error(f"Error purging DB: {e}", exc_info=True)
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    for country in COUNTRIES_CONFIG:
        prayed_for_data[country] = []
    logging.info("Cleared in-memory prayed_for_data for all countries.")

    logging.info("Repopulating queue after purge.")
    update_queue()

    default = list(COUNTRIES_CONFIG.keys())[0]
    hex_gdf = HEX_MAP_DATA_STORE.get(default)
    post_df = POST_LABEL_MAPPINGS_STORE.get(default)
    if hex_gdf is not None and post_df is not None:
        plot_hex_map_with_hearts(hex_gdf, post_df, [], [], default)

    return redirect(url_for('home'))


@app.route('/refresh')
def refresh_data():
    logging.info("Refresh called – queue update runs in background.")
    return redirect(url_for('home'))


@app.route('/put_back', methods=['POST'])
def put_back_in_queue():
    person_name = request.form.get('person_name', '').strip()
    post_label = request.form.get('post_label')
    country = request.form.get('country_code')
    redirect_country = country

    if not country or country not in COUNTRIES_CONFIG:
        logging.error(f"Invalid country_code: {country}")
        return redirect(url_for('prayed_list', country_code=list(COUNTRIES_CONFIG.keys())[0]))

    is_null = not post_label or not post_label.strip()

    # Diagnostic block omitted for brevity...

    conn = None
    updated = False
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            sql = "SELECT id, hex_id FROM prayer_candidates WHERE person_name = %s AND country_code = %s AND status = 'prayed'"
            params = [person_name, country]
            if is_null:
                sql += " AND post_label IS NULL"
            else:
                sql += " AND post_label = %s"
                params.append(post_label)
            cursor.execute(sql, tuple(params))
            rec = cursor.fetchone()
            if rec:
                rec_id, hex_id = rec['id'], rec['hex_id']
                # Reassign hex_id if needed...
                cursor.execute("""
                    UPDATE prayer_candidates
                    SET status = 'queued', status_timestamp = %s, hex_id = %s
                    WHERE id = %s
                """, (now, hex_id, rec_id))
                if cursor.rowcount > 0:
                    conn.commit()
                    updated = True
    except Exception as e:
        logging.error(f"/put_back error: {e}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

    if updated:
        reload_single_country_prayed_data_from_db(country)
        hex_gdf = HEX_MAP_DATA_STORE.get(country)
        post_df = POST_LABEL_MAPPINGS_STORE.get(country)
        queue = get_current_queue_items_from_db()
        if hex_gdf and post_df:
            plot_hex_map_with_hearts(hex_gdf, post_df, prayed_for_data[country], queue, country)

    return redirect(url_for('prayed_list', country_code=redirect_country))

if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', 5000))
        app.run(debug=True, host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print('You pressed Ctrl+C! Exiting gracefully...')
        sys.exit(0)
