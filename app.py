from flask import Flask, render_template, jsonify, request, redirect, url_for
import pandas as pd
# import requests # No longer needed as fetch_csv reads local files
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
LOG_DIR = os.path.join(APP_ROOT, 'data', 'logs')
os.makedirs(LOG_DIR, exist_ok=True) # Create log directory immediately

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
        'log_file': os.path.join(LOG_DIR, 'prayed_for_israel.json'),
        'name': 'Israel',
        'flag': '🇮🇱'
    },
    'iran': {
        'csv_path': os.path.join(APP_ROOT, 'data/20240510_iran.csv'),
        'geojson_path': os.path.join(APP_ROOT, 'data/IRN_IslamicParliamentofIran_290_v2.geojson'),
        'map_shape_path': os.path.join(APP_ROOT, 'data/IRN_IslamicParliamentofIran_290_v2.geojson'),
        'post_label_mapping_path': None,
        'total_representatives': 290,
        'log_file': os.path.join(LOG_DIR, 'prayed_for_iran.json'),
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

data_queue = Queue.Queue()
logging.info(f"Global data_queue object created with id: {id(data_queue)}")

# Global data structures
prayed_for_data = {country: [] for country in COUNTRIES_CONFIG.keys()}
queued_entries_data = {country: set() for country in COUNTRIES_CONFIG.keys()}
deputies_data = {
    country: {'with_images': [], 'without_images': []}
    for country in COUNTRIES_CONFIG.keys()
}
HEX_MAP_DATA_STORE = {}
POST_LABEL_MAPPINGS_STORE = {}

# Old global paths and direct loads are removed as they are now per-country
# heart_img_path remains global as specified.

def initialize_app_data():
    # The content from the existing `if __name__ == '__main__':` block's loop
    # and the thread starting line will go here.
    logging.info("Starting application data initialization...")

    for country_code_init in COUNTRIES_CONFIG.keys():
        logging.info(f"Initializing data for country: {country_code_init}")
        logging.info(f"Using CSV path: {COUNTRIES_CONFIG[country_code_init]['csv_path']}")
        logging.info(f"Using GeoJSON path: {COUNTRIES_CONFIG[country_code_init]['geojson_path']}")
        logging.info(f"Using log file path: {COUNTRIES_CONFIG[country_code_init]['log_file']}")

        # Ensure log file exists and read initial log data
        log_fp = COUNTRIES_CONFIG[country_code_init]['log_file']
        if not os.path.exists(log_fp):
             logging.info(f"Log file {log_fp} not found, creating empty one.")
             with open(log_fp, 'w') as f:
                json.dump([], f)
        read_log(country_code_init) # read_log already logs its actions

        # Fetch and process CSV data for deputies
        df_init = fetch_csv(country_code_init) # fetch_csv logs its actions
        if not df_init.empty:
            process_deputies(df_init, country_code_init) # process_deputies logs
            logging.info(f"Processed deputies for {country_code_init}: {len(deputies_data[country_code_init]['with_images'])} with images, {len(deputies_data[country_code_init]['without_images'])} without.")
        else:
            logging.warning(f"CSV data for {country_code_init} was empty. No deputies processed.")

        # Load map shape data
        map_path = COUNTRIES_CONFIG[country_code_init]['map_shape_path']
        if os.path.exists(map_path):
            HEX_MAP_DATA_STORE[country_code_init] = load_hex_map(map_path)
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
        else:
            logging.info(f"No post label mapping file specified for country {country_code_init}. Assigning empty DataFrame.")

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
            try:
                logging.info(f"update_queue [cycle start]: using data_queue id: {id(data_queue)}, current size: {data_queue.qsize()}")
                all_potential_candidates = []
                # Phase 1: Collect all potential candidates from all countries
                for country_code_collect in COUNTRIES_CONFIG.keys():
                    df_update = fetch_csv(country_code_collect)
                    if df_update.empty:
                        logging.debug(f"No CSV data for {country_code_collect} in this cycle.")
                        continue

                    df_update = df_update.sample(frac=1).reset_index(drop=True)
                    current_prayed_for_ids = {(item['person_name'], item.get('post_label', '')) for item in prayed_for_data[country_code_collect]}
                    country_candidates_selected_this_cycle = set()

                    for index, row in df_update.iterrows():
                        if row.get('person_name'):
                            item = row.to_dict()
                            item['country_code'] = country_code_collect
                            if not item.get('party'):
                                item['party'] = 'Other'
                            item_post_label = item.get('post_label') if item.get('post_label') is not None else ""
                            entry_id = (item['person_name'], item_post_label)
                            if entry_id not in current_prayed_for_ids and \
                               entry_id not in country_candidates_selected_this_cycle:
                                image_url = item.get('image_url', HEART_IMG_PATH)
                                if not image_url:
                                    image_url = HEART_IMG_PATH
                                item['thumbnail'] = image_url
                                all_potential_candidates.append(item)
                                country_candidates_selected_this_cycle.add(entry_id)
                        else:
                            logging.debug(f"Skipped entry due to missing person_name for {country_code_collect} at index {index}: {row.to_dict()}")

                logging.info(f"Collected {len(all_potential_candidates)} total potential new candidates from all countries this cycle.")
                random.shuffle(all_potential_candidates)

                items_added_to_global_queue_this_cycle = 0
                for item_to_add in all_potential_candidates:
                    current_item_country_code = item_to_add['country_code']
                    current_entry_id = (item_to_add['person_name'], item_to_add.get('post_label') if item_to_add.get('post_label') is not None else "")
                    if current_entry_id not in queued_entries_data[current_item_country_code]:
                        logging.debug(f"update_queue [before put]: data_queue id: {id(data_queue)}")
                        data_queue.put(item_to_add)
                        queued_entries_data[current_item_country_code].add(current_entry_id)
                        logging.info(f"Added to queue: {item_to_add['person_name']} (Party: {item_to_add['party']}) from {current_item_country_code}")
                        items_added_to_global_queue_this_cycle += 1

                if items_added_to_global_queue_this_cycle > 0:
                    logging.info(f"Added {items_added_to_global_queue_this_cycle} new items to the global data_queue this cycle.")

                # This is the new logging line that should be at the end of the try block
                logging.info(f"Update_queue cycle complete. Current global queue size: {data_queue.qsize()}")

            except Exception as e:
                logging.error(f"Unexpected error in update_queue thread: {e}", exc_info=True)

            time.sleep(90)

def read_log(country_code):
    log_file_path = COUNTRIES_CONFIG[country_code]['log_file']
    logging.info(f"Attempting to read log file: {log_file_path}")
    try:
        with open(log_file_path, 'r') as f:
            prayed_for_data[country_code] = json.load(f)
            logging.info(f"Successfully loaded {len(prayed_for_data[country_code])} items from log file {log_file_path}")
    except FileNotFoundError:
        logging.warning(f"Log file not found at {log_file_path}. Initializing prayed_for_data for {country_code} as empty list.")
        prayed_for_data[country_code] = [] # Initialize if not found for this country
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {log_file_path}. Initializing as empty list.")
        prayed_for_data[country_code] = []

def write_log(country_code):
    log_file_path = COUNTRIES_CONFIG[country_code]['log_file']
    logging.info(f"Attempting to write {len(prayed_for_data[country_code])} items to log file: {log_file_path}")
    try:
        with open(log_file_path, 'w') as f:
            json.dump(prayed_for_data[country_code], f)
        logging.info(f"Successfully wrote to log file: {log_file_path}")
    except (IOError, OSError) as e:
        logging.error(f"Error writing log file {log_file_path}: {e}")

@app.route('/')
def home():
    logging.info(f"home(): data_queue id: {id(data_queue)}, qsize: {data_queue.qsize()}, empty: {data_queue.empty()}")
    total_all_countries = sum(cfg['total_representatives'] for cfg in COUNTRIES_CONFIG.values())
    total_prayed_for_all_countries = sum(len(prayed_for_data[country]) for country in COUNTRIES_CONFIG.keys())
    current_remaining = total_all_countries - total_prayed_for_all_countries
    current_item_display = None
    map_to_display_country = list(COUNTRIES_CONFIG.keys())[0] # Default to first country

    if not data_queue.empty():
        current_item_display = data_queue.queue[0]
        # Ensure the item has a country_code, otherwise default
        map_to_display_country = current_item_display.get('country_code', map_to_display_country)

    # Ensure logs are read for the map display country before attempting to plot
    # This is important if map_to_display_country could be different from the default
    if map_to_display_country not in prayed_for_data or not prayed_for_data[map_to_display_country]:
        read_log(map_to_display_country) # Load if not already loaded or empty

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
            prayed_for_data[map_to_display_country], # Pass the list of dicts
            list(data_queue.queue), # Pass the global queue list
            map_to_display_country # Pass the country code
        )
    else:
        logging.warning(f"Cannot plot initial map for {map_to_display_country}. Data missing.")

    display_deputies_with_images = deputies_data.get(map_to_display_country, {}).get('with_images', [])
    display_deputies_without_images = deputies_data.get(map_to_display_country, {}).get('without_images', [])

    default_country_code = list(COUNTRIES_CONFIG.keys())[0] if COUNTRIES_CONFIG else None

    return render_template('index.html',
                           remaining=current_remaining,
                           current=current_item_display,
                           queue=list(data_queue.queue),
                           deputies_with_images=display_deputies_with_images,
                           deputies_without_images=display_deputies_without_images,
                           current_country_name=COUNTRIES_CONFIG[map_to_display_country]['name'],
                           all_countries=COUNTRIES_CONFIG, # Pass all country configs
                           default_country_code=default_country_code, # Pass default country code for links
                           initial_map_country_code=map_to_display_country # Pass current map country for JS
                           )

@app.route('/generate_map_for_country/<country_code>')
def generate_map_for_country(country_code):
    if country_code not in COUNTRIES_CONFIG:
        logging.error(f"Invalid country code '{country_code}' for map generation.")
        return jsonify(error='Invalid country code'), 404

    # Ensure logs are read for the country before plotting, as prayed_for_data is used
    if country_code not in prayed_for_data or not prayed_for_data[country_code]:
        read_log(country_code)

    hex_map_gdf = HEX_MAP_DATA_STORE.get(country_code)
    post_label_df = POST_LABEL_MAPPINGS_STORE.get(country_code)
    prayed_list_for_map = prayed_for_data.get(country_code, [])
    current_queue_for_map = list(data_queue.queue)

    if hex_map_gdf is None or hex_map_gdf.empty : # Check for None or empty GeoDataFrame
        logging.error(f"Map data (GeoDataFrame) not available for {country_code} in generate_map_for_country.")
        return jsonify(error=f'Map data not available for {country_code}'), 500
    # post_label_df can be None or empty for random allocation countries, plot_hex_map_with_hearts handles this.

    logging.info(f"Generating map for country: {country_code} on demand.")
    plot_hex_map_with_hearts(hex_map_gdf, post_label_df, prayed_list_for_map, current_queue_for_map, country_code)

    return jsonify(status=f'Map generated for {country_code}'), 200


@app.route('/queue')
def queue_page():
    # This page might need a country filter or display all items with country indication
    items = list(data_queue.queue)
    # Add country name to each item for display
    # This is already done in the /queue/json route, and templates can use all_countries for lookup
    # However, if direct modification of items is preferred here, it can be kept.
    # For consistency with instructions, let's ensure all_countries is passed for template-side lookup.
    logging.info(f"Queue items for /queue page: {items}")
    return render_template('queue.html', queue=items, all_countries=COUNTRIES_CONFIG, HEART_IMG_PATH=HEART_IMG_PATH)

@app.route('/queue/json')
def get_queue_json():
    logging.info(f"get_queue_json(): data_queue id: {id(data_queue)}, qsize: {data_queue.qsize()}, empty: {data_queue.empty()}")
    items = list(data_queue.queue)
    # Add country name to each item
    for item in items:
        item['country_name'] = COUNTRIES_CONFIG[item['country_code']]['name']
    logging.info(f"Queue items: {items}")
    return jsonify(items)

@app.route('/process_item', methods=['POST'])
def process_item():
    if not data_queue.empty():
        item = data_queue.get() # Item should have 'country_code' from update_queue
        country_code_item = item['country_code']
        item['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        prayed_for_data[country_code_item].append(item)

        # Determine post_label for removal from queued_entries_data
        item_post_label_key = item.get('post_label') if item.get('post_label') is not None else ""
        entry_id_to_remove = (item['person_name'], item_post_label_key)

        if entry_id_to_remove in queued_entries_data[country_code_item]:
             queued_entries_data[country_code_item].remove(entry_id_to_remove)

        write_log(country_code_item)
        logging.info(f"Processed item: {item['person_name']} from {COUNTRIES_CONFIG[country_code_item]['name']}")

        # Plot map for the specific country
        hex_map_gdf = HEX_MAP_DATA_STORE.get(country_code_item)
        post_label_df = POST_LABEL_MAPPINGS_STORE.get(country_code_item)
        if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None:
            # Pass the list of prayed items for the country, the global queue, and the country code
            plot_hex_map_with_hearts(
                hex_map_gdf, # Use the fetched GeoDataFrame
                post_label_df, # Use the fetched DataFrame
                prayed_for_data[country_code_item], # Pass the list of dicts
                list(data_queue.queue), # Pass the global queue list
                country_code_item # Pass the country code
            )
        else:
            logging.warning(f"Map data for {country_code_item} not loaded. Skipping map plot.")

    return '', 204

@app.route('/statistics/', defaults={'country_code': None})
@app.route('/statistics/<country_code>')
def statistics(country_code):
    if country_code is None:
        country_code = list(COUNTRIES_CONFIG.keys())[0]
        return redirect(url_for('statistics', country_code=country_code))

    if country_code not in COUNTRIES_CONFIG:
        # Optionally, redirect to a default country's stats page or return 404
        # For now, redirecting to default as an example
        logging.warning(f"Invalid country code '{country_code}' for statistics. Redirecting to default.")
        default_country_code = list(COUNTRIES_CONFIG.keys())[0]
        return redirect(url_for('statistics', country_code=default_country_code))

    read_log(country_code)
    party_counts = {}
    current_country_party_info = party_info.get(country_code, {}) # Get specific country's party info

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

    read_log(country_code)
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

    read_log(country_code)
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
        return redirect(url_for('prayed_list', country_code=default_country_code)) # Or return 404

    read_log(country_code)

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
    global data_queue
    with data_queue.mutex:
        data_queue.queue.clear()
    for country_code_purge in COUNTRIES_CONFIG.keys():
        prayed_for_data[country_code_purge] = []
        queued_entries_data[country_code_purge].clear()
        # Ensure log files are emptied by writing an empty list to them
        log_fp_purge = COUNTRIES_CONFIG[country_code_purge]['log_file']
        with open(log_fp_purge, 'w') as f:
            json.dump([], f)

    # Reset map for the default/first country after purge
    default_country_purge = list(COUNTRIES_CONFIG.keys())[0]
    hex_map_gdf = HEX_MAP_DATA_STORE.get(default_country_purge)
    post_label_df = POST_LABEL_MAPPINGS_STORE.get(default_country_purge)
    if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None:
        plot_hex_map_with_hearts(
            hex_map_gdf, # Use the fetched GeoDataFrame
            post_label_df, # Use the fetched DataFrame
            [], # Empty list for prayed_for_items
            [], # Empty list for queue_items
            default_country_purge # Pass the default country code
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

    # Default redirect in case of issues or item not found
    redirect_target_country_code = item_country_code_from_form

    if not item_country_code_from_form or item_country_code_from_form not in COUNTRIES_CONFIG:
        logging.error(f"Invalid or missing country_code '{item_country_code_from_form}' in put_back request form.")
        # Fallback redirect logic will handle this
    else:
        post_label_key_search = post_label_form if post_label_form is not None else ""
        read_log(item_country_code_from_form) # Read log for the specific country from form

        found_item_to_put_back = None
        items_list = prayed_for_data.get(item_country_code_from_form, [])
        item_index_to_remove = -1

        for i, item_in_log in enumerate(items_list):
            item_in_log_post_label = item_in_log.get('post_label') if item_in_log.get('post_label') is not None else ""
            if item_in_log['person_name'] == person_name and item_in_log_post_label == post_label_key_search:
                found_item_to_put_back = item_in_log # Use the item from the log
                item_index_to_remove = i
                break

        if found_item_to_put_back:
            # Ensure 'country_code' in the item being put back is correct (should be from the form/log)
            found_item_to_put_back['country_code'] = item_country_code_from_form

            data_queue.put(found_item_to_put_back)

            if item_index_to_remove != -1:
                prayed_for_data[item_country_code_from_form].pop(item_index_to_remove)

            queued_entries_data[item_country_code_from_form].add((person_name, post_label_key_search))
            write_log(item_country_code_from_form)

            hex_map_gdf = HEX_MAP_DATA_STORE.get(item_country_code_from_form)
            post_label_df = POST_LABEL_MAPPINGS_STORE.get(item_country_code_from_form)
            if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None:
                plot_hex_map_with_hearts(
                    hex_map_gdf,
                    post_label_df,
                    prayed_for_data[item_country_code_from_form],
                    list(data_queue.queue),
                    item_country_code_from_form
                )
            logging.info(f"Item {person_name} ({post_label_key_search}) from {item_country_code_from_form} put back in queue.")
        else:
            logging.warning(f"Could not find item for {person_name} ({post_label_key_search}) in {item_country_code_from_form} to put back in queue.")

    # Enhanced redirect logic
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
