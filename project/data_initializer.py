"""
Handles the initial setup of application data:
1. Database schema initialization.
2. Migration of old data (JSON logs to DB, old DB schema to new DB schema).
3. Loading static data (CSVs for deputies, map GeoJSONs, etc.) into app memory/context.
4. Initial population of the prayer queue from CSVs if the queue is empty.
"""
import os
import sqlite3
import json
import pandas as pd
import numpy as np
import random
from datetime import datetime
from flask import current_app

# Assuming services are available for DB interaction and some data processing
from .database import init_db_schema, get_db # For direct DB access during migration/seeding
# Corrected: services is a package, import specific modules from it
from .services import prayer_service
from .services import map_service # Explicitly import map_service

def initialize_application(app): # Pass the app instance directly
    """Main function to coordinate all initialization steps."""
    with app.app_context(): # Use the passed app instance to get context
        current_app.logger.info("Starting application data initialization sequence...")

        # 1. Initialize Database Schema (idempotent)
        current_app.logger.info("Step 1: Initializing database schema...")
        init_db_schema() # From database.py, ensures tables exist
        current_app.logger.info("Database schema initialization complete.")

        # 2. Run Data Migrations
        current_app.logger.info("Step 2: Running data migrations...")
        _migrate_json_logs_to_db_if_needed()
        _migrate_old_schema_to_prayer_candidates_if_needed()
        current_app.logger.info("Data migrations complete.")

        # 3. Load static application data (maps, CSV info into memory stores)
        current_app.logger.info("Step 3: Loading static application data (maps, CSVs)...")
        map_service.load_all_map_data(app.app_context()) # Pass app_context
        _load_deputies_data_from_csvs(app.app_context()) # Pass app_context
        current_app.logger.info("Static application data loading complete.")

        # 4. Seed initial prayer queue if prayer_candidates is empty or only has 'prayed' items
        current_app.logger.info("Step 4: Seeding initial prayer queue...")
        _seed_initial_prayer_queue()
        current_app.logger.info("Initial prayer queue seeding complete.")

        current_app.logger.info("Application data initialization sequence finished.")


def _load_deputies_data_from_csvs(app_context): # app_context is correct here
    """Loads representative data from CSVs into current_app.deputies_data."""
    # with app_context: # Already within app_context from the caller
    current_app.logger.info("Loading deputies data from CSVs into app context...")
    countries_config = current_app.config['COUNTRIES_CONFIG']
    for country_code in countries_config.keys():
        df_country = prayer_service.fetch_csv_data(country_code) # prayer_service uses current_app
        if not df_country.empty:
            processed_data = prayer_service.process_deputies_from_df(df_country, country_code)
            current_app.deputies_data[country_code]['with_images'] = processed_data['with_images']
            current_app.deputies_data[country_code]['without_images'] = processed_data['without_images']
            current_app.logger.debug(f"Loaded deputies for {country_code}: {len(processed_data['with_images'])} with, {len(processed_data['without_images'])} without images.")
        else:
            current_app.logger.warning(f"CSV data for {country_code} was empty. No deputies loaded into app.deputies_data.")
    current_app.logger.info("Finished loading deputies data into app context.")


def _migrate_json_logs_to_db_if_needed():
    """
    Migrates data from old JSON log files (e.g., prayed_for_israel.json)
    to the legacy 'prayed_items' SQLite table if that table is empty.
    This is part of the original app.py logic.
    """
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM prayed_items") # Check legacy table
        count = cursor.fetchone()[0]
        if count > 0:
            current_app.logger.info(f"'prayed_items' table is not empty (contains {count} items). JSON log migration skipped.")
            return

        current_app.logger.info("'prayed_items' table is empty. Starting migration from JSON logs...")
        total_migrated_count = 0
        countries_config = current_app.config['COUNTRIES_CONFIG']

        # Original app.py used 'log_file' key in COUNTRIES_CONFIG. This key was removed.
        # We need to reconstruct the expected old JSON log file paths or skip if not found.
        # For this migration, we assume a pattern or specific filenames.
        # Example: data/logs/prayed_for_{country_code}.json

        for country_code, config in countries_config.items():
            # Attempt to find the old JSON log file
            # This part needs to align with how old log files were named.
            # Let's assume a fixed naming pattern for migration:
            old_log_filename = f"prayed_for_{country_code}.json"
            # Original app.py stored these in LOG_DIR, which is now app.config['LOG_DIR']
            log_file_path = os.path.join(current_app.config['LOG_DIR'], old_log_filename)

            country_migrated_count = 0
            if os.path.exists(log_file_path):
                try:
                    with open(log_file_path, 'r') as f:
                        items_from_log = json.load(f)

                    for item in items_from_log:
                        person_name = item.get('person_name')
                        post_label = item.get('post_label')
                        item_country_code = item.get('country_code', country_code) # Fallback
                        party = item.get('party')
                        thumbnail = item.get('thumbnail')
                        prayed_timestamp = item.get('timestamp')

                        if person_name and item_country_code and prayed_timestamp:
                            cursor.execute('''
                                INSERT OR IGNORE INTO prayed_items
                                    (person_name, post_label, country_code, party, thumbnail, prayed_timestamp)
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (person_name, post_label, item_country_code, party, thumbnail, prayed_timestamp))
                            if cursor.rowcount > 0:
                                country_migrated_count += 1
                        else:
                            current_app.logger.warning(f"Skipping item due to missing data during JSON migration: {item} from {log_file_path}")

                    db.commit() # Commit after each file
                    current_app.logger.info(f"Migrated {country_migrated_count} items from {log_file_path} to 'prayed_items' table.")
                    total_migrated_count += country_migrated_count
                except json.JSONDecodeError:
                    current_app.logger.error(f"Error decoding JSON from {log_file_path}. Skipping migration for this file.")
                except sqlite3.Error as e_sql:
                    current_app.logger.error(f"SQLite error migrating from {log_file_path}: {e_sql}")
                    db.rollback()
                except Exception as e_file:
                    current_app.logger.error(f"Error processing file {log_file_path}: {e_file}")
            else:
                current_app.logger.info(f"Old JSON log file not found: {log_file_path}. No items to migrate for {country_code}.")

        if total_migrated_count > 0:
            current_app.logger.info(f"Total items migrated from JSON logs to 'prayed_items' table: {total_migrated_count}.")
        else:
            current_app.logger.info("No items were migrated from JSON logs (files empty, not found, or items already existed).")

    except sqlite3.Error as e:
        current_app.logger.error(f"SQLite error during JSON log migration check: {e}")
        if db: db.rollback()
    except Exception as e_main:
        current_app.logger.error(f"Unexpected error during JSON log migration: {e_main}", exc_info=True)
        if db: db.rollback()


def _migrate_old_schema_to_prayer_candidates_if_needed():
    """
    Migrates data from old 'prayer_queue' and 'prayed_items' tables
    to the new 'prayer_candidates' table if 'prayer_candidates' is empty
    and the old tables have data. This is from original app.py.
    """
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM prayer_candidates")
        candidates_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM prayer_queue") # Legacy table
        queue_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM prayed_items") # Legacy table (populated by JSON migration)
        prayed_count = cursor.fetchone()[0]

        if candidates_count > 0:
            current_app.logger.info(f"'prayer_candidates' table is not empty (contains {candidates_count} items). Old schema migration skipped.")
            return

        if queue_count == 0 and prayed_count == 0:
            current_app.logger.info("Legacy 'prayer_queue' and 'prayed_items' tables are empty. No data to migrate to 'prayer_candidates'.")
            return

        current_app.logger.info(f"Conditions met for old schema migration: 'prayer_candidates' is empty, old tables have data (queue: {queue_count}, prayed: {prayed_count}). Starting migration.")

        migrated_count = 0
        # Migrate from prayer_queue (legacy)
        if queue_count > 0:
            cursor.execute("SELECT person_name, post_label, country_code, party, thumbnail, added_timestamp FROM prayer_queue")
            for item in cursor.fetchall():
                try:
                    # initial_add_timestamp is the same as status_timestamp for newly queued items
                    res = db.execute('''
                        INSERT OR IGNORE INTO prayer_candidates
                            (person_name, post_label, country_code, party, thumbnail, status, status_timestamp, initial_add_timestamp, hex_id)
                        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, NULL)
                    ''', (item['person_name'], item['post_label'], item['country_code'], item['party'], item['thumbnail'], item['added_timestamp'], item['added_timestamp']))
                    if res.rowcount > 0: migrated_count +=1
                except sqlite3.Error as e_insert:
                    current_app.logger.error(f"Error migrating item {item['person_name']} from prayer_queue: {e_insert}")
            current_app.logger.info(f"Migrated {migrated_count} records from prayer_queue to prayer_candidates.")

        # Migrate from prayed_items (legacy)
        migrated_from_prayed_count = 0
        if prayed_count > 0:
            cursor.execute("SELECT person_name, post_label, country_code, party, thumbnail, prayed_timestamp FROM prayed_items")
            for item in cursor.fetchall():
                try:
                     # initial_add_timestamp is the same as status_timestamp for items that were only ever 'prayed'
                    res = db.execute('''
                        INSERT OR IGNORE INTO prayer_candidates
                            (person_name, post_label, country_code, party, thumbnail, status, status_timestamp, initial_add_timestamp, hex_id)
                        VALUES (?, ?, ?, ?, ?, 'prayed', ?, ?, NULL)
                    ''', (item['person_name'], item['post_label'], item['country_code'], item['party'], item['thumbnail'], item['prayed_timestamp'], item['prayed_timestamp']))
                    if res.rowcount > 0: migrated_from_prayed_count +=1
                except sqlite3.Error as e_insert:
                    current_app.logger.error(f"Error migrating item {item['person_name']} from prayed_items: {e_insert}")
            current_app.logger.info(f"Migrated {migrated_from_prayed_count} records from prayed_items to prayer_candidates.")
            migrated_count += migrated_from_prayed_count

        if migrated_count > 0:
            db.commit()
            current_app.logger.info(f"Total {migrated_count} records migrated to 'prayer_candidates' successfully.")
        else:
            db.rollback() # Should not happen if counts > 0, but good practice
            current_app.logger.info("No records were migrated in this pass, though old tables had data. Check for IGNORE conflicts.")

    except sqlite3.Error as e:
        current_app.logger.error(f"SQLite error during old schema migration: {e}")
        if db: db.rollback()
    except Exception as e_main:
        current_app.logger.error(f"Unexpected error during old schema migration: {e_main}", exc_info=True)
        if db: db.rollback()


def _seed_initial_prayer_queue():
    """
    Populates the 'prayer_candidates' table with 'queued' items from CSVs
    if the table is currently empty of 'queued' items or entirely empty.
    This is adapted from the original `update_queue` function in `app.py`.
    """
    db = get_db()
    cursor = db.cursor()

    # Check if there are any 'queued' items. If so, skip seeding.
    cursor.execute("SELECT COUNT(id) FROM prayer_candidates WHERE status = 'queued'")
    queued_count = cursor.fetchone()[0]
    if queued_count > 0:
        current_app.logger.info(f"Found {queued_count} 'queued' items in prayer_candidates. Initial seeding skipped.")
        return

    current_app.logger.info("No 'queued' items found. Proceeding with initial data population from CSVs.")

    # Fetch identifiers of already prayed individuals to avoid re-adding them as queued
    cursor.execute("SELECT person_name, post_label, country_code FROM prayer_candidates WHERE status = 'prayed'")
    already_prayed_tuples = set()
    for record in cursor.fetchall():
        # Normalize post_label for consistent set storage and lookup
        pn = record['person_name']
        pl = record['post_label'] if record['post_label'] is not None else ""
        cc = record['country_code']
        already_prayed_tuples.add((pn, pl, cc))
    current_app.logger.debug(f"Found {len(already_prayed_tuples)} individuals already marked as 'prayed'.")

    all_potential_candidates_to_queue = []
    countries_config = current_app.config['COUNTRIES_CONFIG']

    for country_code, config_val in countries_config.items():
        df_country = prayer_service.fetch_csv_data(country_code)
        if df_country.empty:
            current_app.logger.warning(f"CSV data for {country_code} is empty. Skipping for initial seeding.")
            continue

        num_to_select = config_val.get('total_representatives')
        # Sample or shuffle logic (as in original app.py update_queue)
        if num_to_select is None or len(df_country) <= num_to_select :
            df_sampled = df_country.sample(frac=1).reset_index(drop=True)
        else:
            df_sampled = df_country.sample(n=num_to_select).reset_index(drop=True)
        current_app.logger.debug(f"Sampled {len(df_sampled)} individuals from {country_code} CSV.")

        for _idx, row in df_sampled.iterrows():
            item = row.to_dict()
            item['country_code'] = country_code
            item['party'] = item.get('party', 'Other') # Standardize party

            # Normalize post_label for comparison
            current_post_label_raw = item.get('post_label')
            post_label_for_check = ""
            if isinstance(current_post_label_raw, str) and current_post_label_raw.strip():
                post_label_for_check = current_post_label_raw
            elif current_post_label_raw is None: # Explicit None check
                 post_label_for_check = ""
            # else: post_label_for_check remains "" for empty strings after strip or other types

            candidate_id_tuple = (item['person_name'], post_label_for_check, item['country_code'])

            if item.get('person_name') and candidate_id_tuple not in already_prayed_tuples:
                # Standardize item['post_label'] for DB storage (None for empty/whitespace)
                if isinstance(current_post_label_raw, str) and not current_post_label_raw.strip():
                    item['post_label'] = None
                elif current_post_label_raw is None:
                    item['post_label'] = None

                # Thumbnail: use image_url or default (HEART_IMG_PATH_RELATIVE is just the name, not full path)
                # The actual default image handling might be better in templates or when displaying
                item['thumbnail'] = item.get('image_url') # Store URL, let frontend handle missing
                all_potential_candidates_to_queue.append(item)
            else:
                if not item.get('person_name'):
                    current_app.logger.debug(f"Skipped entry due to missing person_name for {country_code}: {row.to_dict()}")
                else:
                    current_app.logger.debug(f"Skipped {candidate_id_tuple} from CSV for {country_code}; already prayed for or duplicate.")

    random.shuffle(all_potential_candidates_to_queue)
    current_app.logger.info(f"Collected {len(all_potential_candidates_to_queue)} new potential candidates to queue after filtering.")

    items_added_to_db = 0
    # Hex ID assignment logic (as in original app.py update_queue)
    available_hex_ids_by_country = {}
    random_allocation_countries = ['israel', 'iran']

    for country_code_hex_prep in random_allocation_countries:
        hex_map_gdf = current_app.hex_map_data_store.get(country_code_hex_prep)
        if hex_map_gdf is not None and not hex_map_gdf.empty and 'id' in hex_map_gdf.columns:
            all_map_hex_ids = set(hex_map_gdf['id'].unique())
            # Fetch used hex_ids (prayed or queued) for this country
            # Note: This query is slightly different from prayer_service.get_available_hex_id_for_country
            # as it runs during seeding.
            cursor.execute("""
                SELECT hex_id FROM prayer_candidates
                WHERE country_code = ? AND hex_id IS NOT NULL AND (status = 'prayed' OR status = 'queued')
            """, (country_code_hex_prep,))
            used_hex_ids = {r['hex_id'] for r in cursor.fetchall()}

            current_available_hex_ids = list(all_map_hex_ids - used_hex_ids)
            random.shuffle(current_available_hex_ids)
            available_hex_ids_by_country[country_code_hex_prep] = current_available_hex_ids
            current_app.logger.debug(f"For {country_code_hex_prep} (seeding): {len(all_map_hex_ids)} total, {len(used_hex_ids)} used, {len(current_available_hex_ids)} available hexes.")
        else:
            available_hex_ids_by_country[country_code_hex_prep] = []

    # Assign hex_id and insert
    for item_to_add in all_potential_candidates_to_queue:
        hex_id_to_insert = None
        item_country_code = item_to_add['country_code']
        if item_country_code in random_allocation_countries:
            if available_hex_ids_by_country.get(item_country_code):
                hex_id_to_insert = available_hex_ids_by_country[item_country_code].pop()
            else:
                current_app.logger.warning(f"No available hex_ids to assign for {item_to_add['person_name']} in {item_country_code} during seeding.")

        now_ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            res = db.execute('''
                INSERT OR IGNORE INTO prayer_candidates
                    (person_name, post_label, country_code, party, thumbnail, status, status_timestamp, initial_add_timestamp, hex_id)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)
            ''', (item_to_add['person_name'], item_to_add['post_label'], item_country_code,
                  item_to_add['party'], item_to_add['thumbnail'], now_ts_str, now_ts_str, hex_id_to_insert))
            if res.rowcount > 0:
                items_added_to_db += 1
        except sqlite3.Error as e_insert:
            current_app.logger.error(f"SQLite error during initial seeding for {item_to_add['person_name']}: {e_insert}")

    if items_added_to_db > 0:
        db.commit()
        current_app.logger.info(f"Successfully inserted {items_added_to_db} new items into prayer_candidates as 'queued'.")
    else:
        db.rollback() # No changes to commit
        current_app.logger.info("No new items were added to the queue during this seeding pass (perhaps all were duplicates or already prayed for).")

    cursor.execute("SELECT COUNT(id) FROM prayer_candidates WHERE status = 'queued'")
    final_queued_count = cursor.fetchone()[0]
    current_app.logger.info(f"Initial seeding process complete. Current 'queued' items in prayer_candidates: {final_queued_count}")
