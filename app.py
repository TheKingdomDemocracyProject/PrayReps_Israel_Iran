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

from hex_map import load_hex_map, load_post_label_mapping, plot_hex_map_with_hearts
from utils import format_pretty_timestamp

app = Flask(__name__)

# Configuration
COUNTRIES_CONFIG = {
    'israel': {
        'csv_path': 'data/20221101_israel.csv',
        'geojson_path': 'data/ISR_Parliament_120.geojson',
        'map_shape_path': 'data/ISR_Parliament_120.geojson',
        'post_label_mapping_path': None,
        'total_representatives': 120,
        'log_file': 'prayed_for_israel.json',
        'name': 'Israel'
    },
    'iran': {
        'csv_path': 'data/20240510_iran.csv',
        'geojson_path': 'data/IRN_IslamicParliamentofIran_290_v2.geojson',
        'map_shape_path': 'data/IRN_IslamicParliamentofIran_290_v2.geojson',
        'post_label_mapping_path': None,
        'total_representatives': 290,
        'log_file': 'prayed_for_iran.json',
        'name': 'Iran'
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
processed_items = [] # This seems unused in the provided snippets, consider removing later if confirmed.

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

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler("app.log"),
    logging.StreamHandler()
])

# Function to fetch the CSV
def fetch_csv(country_code):
    logging.info(f"Fetching CSV data for {country_code}")
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
        while True:
            for country_code_update in COUNTRIES_CONFIG.keys():
                df_update = fetch_csv(country_code_update)
                if df_update.empty:
                    logging.warning(f"Skipping update for {country_code_update} as DataFrame is empty.")
                    continue
                # Use country-specific prayed_for_data and queued_entries_data
                current_prayed_for_ids = {(item['person_name'], item.get('post_label','')) for item in prayed_for_data[country_code_update]}
                df_update = df_update.sample(frac=1).reset_index(drop=True)
                for index, row in df_update.iterrows():
                    if row.get('person_name'): # Changed condition: only person_name is essential initially
                        item = row.to_dict()

                        # Default party to 'Other' if missing or empty
                        if not item.get('party'): # Handles None or empty string
                            item['party'] = 'Other'

                        item['country_code'] = country_code_update # Tag item with its country
                        item_post_label = item.get('post_label') if item.get('post_label') is not None else ""
                        entry_id = (item['person_name'], item_post_label)

                        # Use country-specific queued_entries_data
                        if entry_id not in current_prayed_for_ids and entry_id not in queued_entries_data[country_code_update]:
                            image_url = item.get('image_url', HEART_IMG_PATH) # Use global HEART_IMG_PATH
                            if not image_url: # Ensure there's a fallback
                                image_url = HEART_IMG_PATH
                            item['thumbnail'] = image_url
                            data_queue.put(item) # Global queue, items are tagged with country_code
                            queued_entries_data[country_code_update].add(entry_id)
                            logging.info(f"Added to queue: {item['person_name']} (Party: {item['party']}) from {country_code_update}")
                    else:
                        logging.debug(f"Skipped entry for {country_code_update} due to missing person_name at index {index}: {row.to_dict()}")
            logging.debug(f"Global queue size: {data_queue.qsize()}")
            time.sleep(90)  # Check all countries every 90 seconds

def read_log(country_code):
    log_file_path = COUNTRIES_CONFIG[country_code]['log_file']
    try:
        with open(log_file_path, 'r') as f:
            prayed_for_data[country_code] = json.load(f)
    except FileNotFoundError:
        prayed_for_data[country_code] = [] # Initialize if not found for this country
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {log_file_path}. Initializing as empty list.")
        prayed_for_data[country_code] = []

def write_log(country_code):
    log_file_path = COUNTRIES_CONFIG[country_code]['log_file']
    with open(log_file_path, 'w') as f:
        json.dump(prayed_for_data[country_code], f)

@app.route('/')
def home():
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
                           default_country_code=default_country_code # Pass default country code for links
                           )


@app.route('/queue')
def queue_page():
    # This page might need a country filter or display all items with country indication
    items = list(data_queue.queue)
    # Add country name to each item for display
    # This is already done in the /queue/json route, and templates can use all_countries for lookup
    # However, if direct modification of items is preferred here, it can be kept.
    # For consistency with instructions, let's ensure all_countries is passed for template-side lookup.
    logging.info(f"Queue items for /queue page: {items}")
    return render_template('queue.html', queue=items, all_countries=COUNTRIES_CONFIG)

@app.route('/queue/json')
def get_queue_json():
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
    # country_code_form is crucial to identify which country's list to modify
    country_code_form = request.form.get('country_code')

    if not country_code_form or country_code_form not in COUNTRIES_CONFIG:
        logging.error(f"Invalid or missing country_code '{country_code_form}' in put_back request.")
        # Redirect to prayed_list, maybe with an error message in future
        return redirect(url_for('prayed_list'))

    post_label_key_search = post_label_form if post_label_form is not None else ""

    # Read the log for the specific country to ensure data is current
    read_log(country_code_form)

    found_item_to_put_back = None
    # Search in the specified country's prayed_for_data
    # Need to handle cases where prayed_for_data[country_code_form] might be empty or not yet populated
    items_list = prayed_for_data.get(country_code_form, [])
    item_index_to_remove = -1

    for i, item in enumerate(items_list):
        # Ensure comparison is robust, especially for post_label which can be None or empty string
        item_post_label = item.get('post_label') if item.get('post_label') is not None else ""
        if item['person_name'] == person_name and item_post_label == post_label_key_search:
            found_item_to_put_back = item
            item_index_to_remove = i
            break # Found the item

    if found_item_to_put_back:
        # Ensure 'country_code' is in the item before putting back to queue
        if 'country_code' not in found_item_to_put_back:
            found_item_to_put_back['country_code'] = country_code_form

        data_queue.put(found_item_to_put_back) # Add item back to the global queue

        # Remove from the specific country's prayed list by index
        if item_index_to_remove != -1: # Should always be true if found_item_to_put_back is not None
            prayed_for_data[country_code_form].pop(item_index_to_remove)

        # Add to the specific country's queued entries set
        queued_entries_data[country_code_form].add((person_name, post_label_key_search))
        write_log(country_code_form) # Write log for the specific country

        # Update hex map for the specific country
        hex_map_gdf = HEX_MAP_DATA_STORE.get(country_code_form)
        post_label_df = POST_LABEL_MAPPINGS_STORE.get(country_code_form)
        if hex_map_gdf is not None and not hex_map_gdf.empty and post_label_df is not None:
            plot_hex_map_with_hearts(
                hex_map_gdf, # Use the fetched GeoDataFrame
                post_label_df, # Use the fetched DataFrame
                prayed_for_data[country_code_form],
                list(data_queue.queue),
                country_code_form
            )
    else:
        logging.warning(f"Could not find item for {person_name}, {post_label_form} in {COUNTRIES_CONFIG[country_code_form]['name']} to put back in queue.")

    # Redirect back to the prayed list, possibly for the same country
    return redirect(url_for('prayed_list', country=country_code_form))


if __name__ == '__main__':
    # Initial Data Loading
    for country_code_init in COUNTRIES_CONFIG.keys():
        # Ensure log file exists and read initial log data
        log_fp = COUNTRIES_CONFIG[country_code_init]['log_file']
        if not os.path.exists(log_fp):
             with open(log_fp, 'w') as f:
                json.dump([], f)
        read_log(country_code_init)

        # Fetch and process CSV data for deputies
        df_init = fetch_csv(country_code_init)
        if not df_init.empty:
            process_deputies(df_init, country_code_init)

        # Load map shape data
        map_path = COUNTRIES_CONFIG[country_code_init]['map_shape_path']
        if os.path.exists(map_path):
            HEX_MAP_DATA_STORE[country_code_init] = load_hex_map(map_path)
        else:
            logging.error(f"Map file not found: {map_path} for country {country_code_init}")
            HEX_MAP_DATA_STORE[country_code_init] = None # Ensure key exists

        # Load post label mapping data
        post_label_path = COUNTRIES_CONFIG[country_code_init].get('post_label_mapping_path') # Use .get() for safety
        if post_label_path and os.path.exists(post_label_path):
            POST_LABEL_MAPPINGS_STORE[country_code_init] = load_post_label_mapping(post_label_path)
        elif post_label_path:  # Only log error if a path was actually specified but not found
            logging.error(f"Post label mapping file not found: {post_label_path} for country {country_code_init}")
            POST_LABEL_MAPPINGS_STORE[country_code_init] = pd.DataFrame()  # Assign empty DataFrame
        else:  # Path is None or empty
            logging.info(f"No post label mapping file specified for country {country_code_init}. Assigning empty DataFrame.")
            POST_LABEL_MAPPINGS_STORE[country_code_init] = pd.DataFrame()  # Assign empty DataFrame for None path

    # Start the queue updating thread
    threading.Thread(target=update_queue, daemon=True).start()

    try:
        # Run the Flask app with debug mode enabled
        app.run(debug=True)
    except KeyboardInterrupt:
        print('You pressed Ctrl+C! Exiting gracefully...')
        sys.exit(0)
