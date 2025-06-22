from flask import current_app
from datetime import datetime
import pandas as pd
import numpy as np
import random
import sqlite3 # For specific error types if needed

from ..database import get_db # Use the new DB module

# --- Data Fetching and Processing (from original app.py, to be adapted) ---

def fetch_csv_data(country_code):
    """Fetches CSV data for a given country."""
    csv_path = current_app.config['COUNTRIES_CONFIG'][country_code]['csv_path']
    try:
        df = pd.read_csv(csv_path)
        df = df.replace({np.nan: None}) # Replace NaN with None for DB compatibility
        current_app.logger.debug(f"Successfully fetched {len(df)} rows from {csv_path} for {country_code}.")
        return df
    except FileNotFoundError:
        current_app.logger.error(f"CSV file not found for {country_code} at {csv_path}")
        return pd.DataFrame()
    except Exception as e:
        current_app.logger.error(f"Error reading CSV for {country_code} at {csv_path}: {e}")
        return pd.DataFrame()


def process_deputies_from_df(df_country, country_code):
    """Processes deputies from a DataFrame, separating those with and without images."""
    # This function was used to populate app.deputies_data
    # It can be adapted if that global structure is still needed for some views,
    # or if the data is directly inserted into a more permanent store.
    # For now, let's assume it populates the app-level store as before.

    deputies_with_images = []
    deputies_without_images = []

    if df_country.empty:
        current_app.logger.warning(f"No deputies to process for {country_code} as DataFrame is empty.")
        return {'with_images': [], 'without_images': []}

    for _index, row in df_country.iterrows():
        image_url = row.get('image_url')
        processed_row = row.to_dict()
        if not image_url:
            deputies_without_images.append(processed_row)
        else:
            # In original app.py, 'Image' was added to row. Not strictly needed if 'image_url' is used.
            # processed_row['Image'] = image_url
            deputies_with_images.append(processed_row)

    current_app.logger.debug(f"Processed deputies for {country_code}: {len(deputies_with_images)} with, {len(deputies_without_images)} without images.")
    return {'with_images': deputies_with_images, 'without_images': deputies_without_images}


# --- Queue Management (interacting with prayer_candidates table) ---

def get_queued_representatives(limit=None):
    """Gets representatives from the prayer_candidates table with status 'queued'."""
    db = get_db()
    query = """
        SELECT id, person_name, post_label, country_code, party, thumbnail,
               initial_add_timestamp AS added_timestamp, hex_id, status_timestamp
        FROM prayer_candidates
        WHERE status = 'queued'
        ORDER BY id ASC
    """
    params = []
    if limit:
        query += " LIMIT ?"
        params.append(limit)

    rows = db.execute(query, params).fetchall()
    items = [dict(row) for row in rows]
    current_app.logger.debug(f"Fetched {len(items)} 'queued' representatives.")
    return items

def get_next_queued_representative():
    """Gets the next representative from the queue (oldest by ID)."""
    items = get_queued_representatives(limit=1)
    return items[0] if items else None

def get_prayed_representatives(country_code=None):
    """Gets representatives from prayer_candidates with status 'prayed'."""
    db = get_db()
    query = """
        SELECT id, person_name, post_label, country_code, party, thumbnail,
               status_timestamp AS timestamp, hex_id
        FROM prayer_candidates
        WHERE status = 'prayed'
    """
    params = []
    if country_code:
        query += " AND country_code = ?"
        params.append(country_code)
    query += " ORDER BY status_timestamp DESC" # Show most recent first

    rows = db.execute(query, params).fetchall()
    items = [dict(row) for row in rows]
    current_app.logger.debug(f"Fetched {len(items)} 'prayed' representatives (country: {country_code or 'all'}).")
    return items

def mark_representative_as_prayed(candidate_id):
    """Updates a representative's status to 'prayed'."""
    db = get_db()
    now_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # First, fetch the item to ensure it exists and is queued
    item_to_update = db.execute("SELECT * FROM prayer_candidates WHERE id = ? AND status = 'queued'", (candidate_id,)).fetchone()

    if not item_to_update:
        current_app.logger.warning(f"Attempted to mark item ID {candidate_id} as prayed, but it was not found or not in 'queued' state.")
        return None, 0 # Return None and 0 rows affected

    try:
        cursor = db.execute("""
            UPDATE prayer_candidates
            SET status = 'prayed', status_timestamp = ?
            WHERE id = ? AND status = 'queued'
        """, (now_timestamp, candidate_id))
        db.commit()
        rows_affected = cursor.rowcount
        if rows_affected > 0:
            current_app.logger.info(f"Marked representative ID {candidate_id} as 'prayed'.")
            # Return the details of the processed item, including the new timestamp
            processed_item_details = dict(item_to_update) # Original details
            processed_item_details['status'] = 'prayed'
            processed_item_details['timestamp'] = now_timestamp # Use the actual update timestamp
            return processed_item_details, rows_affected
        else:
            # This case should be rare if the initial check passed, but good for safety
            current_app.logger.warning(f"Mark as prayed for ID {candidate_id} affected 0 rows, despite initial check. Possible race condition or stale data.")
            return None, 0
    except sqlite3.Error as e:
        current_app.logger.error(f"SQLite error marking representative ID {candidate_id} as prayed: {e}")
        db.rollback()
        return None, 0


def put_representative_back_in_queue(candidate_id, new_hex_id=None):
    """
    Updates a representative's status to 'queued'.
    If new_hex_id is provided, it also updates the hex_id.
    """
    db = get_db()
    now_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Fetch the item to ensure it exists and is 'prayed'
    # Also get its current hex_id if new_hex_id is not provided
    item_to_update = db.execute("SELECT * FROM prayer_candidates WHERE id = ? AND status = 'prayed'", (candidate_id,)).fetchone()

    if not item_to_update:
        current_app.logger.warning(f"Attempted to put item ID {candidate_id} back in queue, but it was not found or not in 'prayed' state.")
        return 0

    final_hex_id = new_hex_id if new_hex_id is not None else item_to_update['hex_id']

    try:
        cursor = db.execute("""
            UPDATE prayer_candidates
            SET status = 'queued', status_timestamp = ?, hex_id = ?
            WHERE id = ? AND status = 'prayed'
        """, (now_timestamp, final_hex_id, candidate_id))
        db.commit()
        rows_affected = cursor.rowcount
        if rows_affected > 0:
            current_app.logger.info(f"Put representative ID {candidate_id} back to 'queued', hex_id set to {final_hex_id}.")
        else:
            current_app.logger.warning(f"Put back for ID {candidate_id} affected 0 rows. Possible race condition or stale data.")
        return rows_affected
    except sqlite3.Error as e:
        current_app.logger.error(f"SQLite error putting representative ID {candidate_id} back to queue: {e}")
        db.rollback()
        return 0

def get_available_hex_id_for_country(country_code, exclude_candidate_id=None):
    """
    Finds an available hex_id for a given country from its map,
    excluding hex_ids already used by 'queued' or 'prayed' candidates.
    Optionally excludes a specific candidate_id (e.g., the one being put back).
    """
    db = get_db()
    hex_map_gdf = current_app.hex_map_data_store.get(country_code)

    if hex_map_gdf is None or hex_map_gdf.empty or 'id' not in hex_map_gdf.columns:
        current_app.logger.warning(f"Hex map data or 'id' column not available for {country_code}. Cannot assign hex_id.")
        return None

    all_map_hex_ids = set(hex_map_gdf['id'].unique())

    # Fetch used hex_ids from DB for this country
    query = """
        SELECT hex_id FROM prayer_candidates
        WHERE country_code = ? AND hex_id IS NOT NULL AND (status = 'prayed' OR status = 'queued')
    """
    params = [country_code]
    if exclude_candidate_id:
        query += " AND id != ?"
        params.append(exclude_candidate_id)

    used_hex_rows = db.execute(query, params).fetchall()
    used_hex_ids = {row['hex_id'] for row in used_hex_rows}

    available_hex_ids = list(all_map_hex_ids - used_hex_ids)
    if not available_hex_ids:
        current_app.logger.warning(f"No available hex_ids to assign in {country_code}.")
        return None

    random.shuffle(available_hex_ids)
    assigned_hex_id = available_hex_ids.pop()
    current_app.logger.info(f"Assigned available hex_id {assigned_hex_id} for {country_code}.")
    return assigned_hex_id


def purge_all_data():
    """Deletes all records from the prayer_candidates table."""
    db = get_db()
    try:
        cursor = db.execute("DELETE FROM prayer_candidates")
        db.commit()
        current_app.logger.info(f"Purged all {cursor.rowcount} items from prayer_candidates table.")

        # Also clear old tables if they were part of the purge in original app
        # cursor = db.execute("DELETE FROM prayer_queue") # Legacy
        # db.commit()
        # current_app.logger.info(f"Purged legacy prayer_queue table: {cursor.rowcount} items.")
        # cursor = db.execute("DELETE FROM prayed_items") # Legacy
        # db.commit()
        # current_app.logger.info(f"Purged legacy prayed_items table: {cursor.rowcount} items.")

        return True
    except sqlite3.Error as e:
        current_app.logger.error(f"SQLite error during purge: {e}")
        db.rollback()
        return False

# --- Statistics ---
def get_party_statistics(country_code):
    """Calculates prayed-for counts by party for a given country."""
    prayed_items_for_country = get_prayed_representatives(country_code)
    party_counts = {}

    country_party_info_map = current_app.config['PARTY_INFO'].get(country_code, {})
    other_party_default = {'short_name': 'Other', 'color': '#CCCCCC'} # Default for 'Other'

    for item in prayed_items_for_country:
        party_name = item.get('party', 'Other')
        party_details = country_party_info_map.get(party_name,
                                                 country_party_info_map.get('Other', other_party_default))
        short_name = party_details['short_name']
        party_counts[short_name] = party_counts.get(short_name, 0) + 1

    sorted_party_counts = sorted(party_counts.items(), key=lambda x: x[1], reverse=True)
    current_app.logger.debug(f"Calculated party statistics for {country_code}: {sorted_party_counts}")
    return sorted_party_counts, country_party_info_map

def get_timedata_statistics(country_code):
    """Gets timestamped prayer data for a country or overall."""
    items_for_timedata = []
    if country_code == 'overall':
        for c_code in current_app.config['COUNTRIES_CONFIG'].keys():
            items_for_timedata.extend(get_prayed_representatives(c_code))
        # Sort all items by timestamp if combining
        items_for_timedata.sort(key=lambda x: x.get('timestamp', ''))
    else:
        items_for_timedata = get_prayed_representatives(country_code)
        # Already sorted by timestamp DESC by get_prayed_representatives

    timestamps = []
    values = []
    for item in items_for_timedata:
        if item.get('timestamp'):
            timestamps.append(item.get('timestamp'))
            value_detail = {
                'place': item.get('post_label'),
                'person': item.get('person_name'),
                'party': item.get('party')
            }
            if country_code == 'overall':
                item_country_code = item.get('country_code')
                value_detail['country'] = current_app.config['COUNTRIES_CONFIG'].get(item_country_code, {}).get('name', 'Unknown')
            values.append(value_detail)

    current_app.logger.debug(f"Fetched timedata for {country_code}: {len(timestamps)} entries.")
    return {'timestamps': timestamps, 'values': values}

def get_overall_prayed_count():
    """Gets the total count of prayed-for items across all countries."""
    db = get_db()
    row = db.execute("SELECT COUNT(id) FROM prayer_candidates WHERE status = 'prayed'").fetchone()
    count = row[0] if row else 0
    current_app.logger.debug(f"Overall prayed count from DB: {count}")
    return count

# The `update_queue` function from app.py is complex and involves initial data seeding.
# It will be part of the `data_initializer.py` module or a dedicated seeding service,
# as it's more about initial population than ongoing prayer request processing.
# This service focuses on operations related to existing prayer candidates.
