from flask import Flask, render_template, jsonify, request, redirect, url_for
import pandas as pd
import requests
import threading
import time
import queue as Queue
import logging
from datetime import datetime
import json
import sys
from io import StringIO
import numpy as np
import os

from hex_map import load_hex_map, load_post_label_mapping, plot_hex_map_with_hearts
from utils import format_pretty_timestamp

app = Flask(__name__)

# Simplified party_info with only relevant parties
party_info = {
    'Lëvizja Vetëvendosje!': {'short_name': 'LVV', 'color': '#CC0033'},
    'Democratic Party of Kosovo': {'short_name': 'PDK', 'color': '#2E96D2'},
    'Democratic League of Kosovo': {'short_name': 'LDK', 'color': '#F37476'},
    'Serbian List': {'short_name': 'SL', 'color': '#000080'},
    'Alliance for the Future of Kosovo': {'short_name': 'AAK', 'color': '#03112C'},
    'Alliance for the Future of Kosovo': {'short_name': 'AAK-NISMA', 'color': '#03112C'},
    'Alliance for the Future of Kosovo': {'short_name': 'NISMA', 'color': '#03112C'},
    'Kosova Demokratik Türk Partisi': {'short_name': 'KDTP', 'color': '#dd3333'},
    'New Democratic Initiative of Kosovo': {'short_name': 'IRDK', 'color': '#F58634'},
    'New Democratic Party': {'short_name': 'NDS', 'color': '#FFFF00'},
    'For Freedom, Justice and Survival': {'short_name': 'FFJS', 'color': '#5593BA'},
    'Vakat Coalition': {'short_name': 'VK', 'color': '#00923F'},
    'Romani Initiative': {'short_name': 'RI', 'color': '#f13737'},
    'Egyptian Liberal Party': {'short_name': 'PLE', 'color': '#076CA7'},
    'Social Democratic Union': {'short_name': 'SDU', 'color': '#CF312E'},
    'Ashkali Party for Integration': {'short_name': 'PAI', 'color': '#0065AD'},
    'Unique Gorani Party': {'short_name': 'JGP', 'color': '#FFCF40'},
    'United Roma Party of Kosovo': {'short_name': 'PREBK', 'color': '#009933'},
    'Other': {'short_name': 'Other', 'color': '#CCCCCC'},
    'Progressive Movement of Kosovar Roma': {'short_name': 'LPRK', 'color': '#008001'},
    'Civic Initiative for Freedom, Justice and Survival': {'short_name': 'SPO', 'color': '#3b94be'}
}

data_queue = Queue.Queue()
processed_items = []
prayed_for = []  # This will store the processed items for statistics
queued_entries = set()  # To track the unique entries in the queue

# Paths for hex map
hex_map_path = 'data/20250209_kosovo.shp'
post_label_mapping_path = 'data/post_label to 3CODE.csv'
heart_img_path = 'static/heart_icons/heart_red.png'

# Load hex map and mappings
hex_map = load_hex_map(hex_map_path)
post_label_mapping = load_post_label_mapping(post_label_mapping_path)

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
    logging.FileHandler("app.log"),
    logging.StreamHandler()
])

# Function to fetch the CSV
def fetch_csv():
    logging.info("Fetching CSV data")
    url = "data/20250209_kosovo.csv"
    response = requests.get(url)
    data = response.content.decode('utf-8')
    df = pd.read_csv(StringIO(data))
    df = df.replace({np.nan: None})  # Replace NaN with None
    logging.debug(f"Fetched data: {df.head()}")
    return df

# Process each entry to determine if an image is available
def process_deputies(csv_data):
    deputies_with_images = []
    deputies_without_images = []

    for index, row in csv_data.iterrows():
        image_url = row.get('image_url')

        if not image_url:
            logging.debug(f"No image URL for {row.get('person_name')} at index {index}")
            deputies_without_images.append(row)
            continue

        row['Image'] = image_url
        deputies_with_images.append(row)
        logging.debug(f"Image URL assigned for {row.get('person_name')}: {image_url}")

    return deputies_with_images, deputies_without_images

# Load the CSV data
csv_data = fetch_csv()
deputies_with_images, deputies_without_images = process_deputies(csv_data)

# Log the names without images
if deputies_without_images:
    logging.info(f"No images found for the following names: {', '.join([dep['person_name'] for dep in deputies_without_images if dep['person_name']])}")

# Function to periodically update the queue
def update_queue():
    with app.app_context():  # Ensure this block runs within an application context
        while True:
            df = fetch_csv()
            prayed_for_ids = {(item['person_name'], item['post_label']) for item in prayed_for}

            # Shuffle the DataFrame rows for randomization
            df = df.sample(frac=1).reset_index(drop=True)

            for index, row in df.iterrows():
                if all(row.get(field) for field in ['place', 'post_label', 'person_name', 'party']):
                    item = row.to_dict()
                    entry_id = (item['person_name'], item['post_label'])
                    if entry_id not in prayed_for_ids and entry_id not in queued_entries:
                        image_url = item.get('image_url', heart_img_path)
                        if not image_url:
                            image_url = heart_img_path
                        item['thumbnail'] = image_url
                        data_queue.put(item)
                        queued_entries.add(entry_id)
                        logging.info(f"Added to queue: {item}")
                else:
                    logging.debug(f"Skipped incomplete entry at index {index}: {row.to_dict()}")
            
            logging.debug(f"Queue size: {data_queue.qsize()}")
            time.sleep(90)  # Check every 90 seconds

def read_log():
    global prayed_for
    try:
        with open('prayed_for.json', 'r') as f:
            prayed_for = json.load(f)
    except FileNotFoundError:
        prayed_for = []

def write_log():
    with open('prayed_for.json', 'w') as f:
        json.dump(prayed_for, f)

@app.route('/')
def home():
    read_log()  # Ensure prayed_for is up to date
    remaining = 488 - len(prayed_for)
    current = None if data_queue.empty() else data_queue.queue[0]
    queue_list = list(data_queue.queue)
    plot_hex_map_with_hearts(hex_map, post_label_mapping, [item['post_label'] for item in prayed_for], [item['post_label'] for item in queue_list])  # Update hex map

    # Create URLs for images
    for deputy in deputies_with_images:
        deputy['Image'] = deputy['Image']  # Image URL is already provided
        logging.debug(f"Deputy: {deputy['person_name']}, Image URL: {deputy['Image']}")

    return render_template('index.html', remaining=remaining, current=current, queue=queue_list, deputies_with_images=deputies_with_images, deputies_without_images=deputies_without_images)

@app.route('/queue')
def queue_page():
    items = list(data_queue.queue)
    logging.info(f"Queue items: {items}")
    return render_template('queue.html', queue=items)

@app.route('/queue/json')
def get_queue_json():
    items = list(data_queue.queue)
    logging.info(f"Queue items: {items}")
    return jsonify(items)

@app.route('/process_item', methods=['POST'])
def process_item():
    if not data_queue.empty():
        item = data_queue.get()
        item['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Add timestamp
        processed_items.append(item)
        prayed_for.append(item)  # Add to prayed_for list
        queued_entries.remove((item['person_name'], item['post_label']))  # Remove from queued entries
        write_log()  # Save to log file
        logging.info(f"Processed item: {item}")
        queue_list = list(data_queue.queue)
        plot_hex_map_with_hearts(hex_map, post_label_mapping, [item['post_label'] for item in prayed_for], [item['post_label'] for item in queue_list])  # Update hex map
    return '', 204

@app.route('/statistics')
def statistics():
    read_log()
    party_counts = {}
    for item in prayed_for:
        party = item.get('party', 'Other')
        short_name = party_info.get(party, party_info['Other'])['short_name']
        party_counts[short_name] = party_counts.get(short_name, 0) + 1

    sorted_party_counts = sorted(party_counts.items(), key=lambda x: x[1], reverse=True)
    return render_template('statistics.html', sorted_party_counts=sorted_party_counts, party_info=party_info)

@app.route('/statistics/data')
def statistics_data():
    read_log()
    party_counts = {}
    for item in prayed_for:
        party = item.get('party', 'Other')
        short_name = party_info.get(party, party_info['Other'])['short_name']
        party_counts[short_name] = party_counts.get(short_name, 0) + 1
    return jsonify(party_counts)

@app.route('/statistics/timedata')
def statistics_timedata():
    read_log()
    timestamps = []
    values = []
    for item in prayed_for:
        timestamps.append(item.get('timestamp'))
        values.append({
            'place': item.get('post_label'),
            'person': item.get('person_name'),
            'party': item.get('party')  # Use full party name for matching colors
        })
    return jsonify({'timestamps': timestamps, 'values': values})

@app.route('/prayed')
def prayed_list():
    read_log()
    for item in prayed_for:
        item['formatted_timestamp'] = format_pretty_timestamp(item.get('timestamp'))
        party = item.get('party', 'Other')
        party_info_item = party_info.get(party, party_info['Other'])
        item['party_class'] = party_info_item['short_name'].lower().replace(' ', '-').replace('&', 'and')
        item['party_color'] = party_info_item['color']

    return render_template('prayed.html', prayed_for=prayed_for, party_info=party_info)

@app.route('/purge')
def purge_queue():
    global data_queue, prayed_for, queued_entries
    with data_queue.mutex:
        data_queue.queue.clear()
    prayed_for = []
    queued_entries.clear()
    write_log()
    plot_hex_map_with_hearts(hex_map, post_label_mapping, [], [])  # Update hex map
    return redirect(url_for('home'))

@app.route('/refresh')
def refresh_data():
    threading.Thread(target=update_queue).start()
    write_log()
    return redirect(url_for('home'))

@app.route('/put_back', methods=['POST'])
def put_back_in_queue():
    global prayed_for
    read_log()
    person_name = request.form.get('person_name')
    post_label = request.form.get('post_label')
    constituency = next((item for item in prayed_for if item['post_label'] == post_label and item['person_name'] == person_name), None)

    if constituency:
        data_queue.put(constituency)
        prayed_for = [p for p in prayed_for if p['post_label'] != post_label or p['person_name'] != person_name]
        queued_entries.add((person_name, post_label))
        write_log()
        queue_list = list(data_queue.queue)
        plot_hex_map_with_hearts(hex_map, post_label_mapping, [item['post_label'] for item in prayed_for], [item['post_label'] for item in queue_list])  # Update hex map

    return redirect(url_for('prayed_list'))

if __name__ == '__main__':
    # Read initial log
    read_log()

    # Start the queue updating thread
    threading.Thread(target=update_queue, daemon=True).start()

    try:
        # Run the Flask app with debug mode enabled
        app.run(debug=True)
    except KeyboardInterrupt:
        print('You pressed Ctrl+C! Exiting gracefully...')
        sys.exit(0)
