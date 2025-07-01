import os
import pandas as pd
from flask import current_app # Can be used if app_instance is not passed to helpers

# Import functions and data stores from the 'app.py' module (now acting as a utility library)
# 'app.py' is in the parent directory of 'project'.
from ..app import (
    init_db,
    load_prayed_for_data_from_db,
    update_queue,
    fetch_csv,
    process_deputies, # This populates global deputies_data in app.py
    COUNTRIES_CONFIG,
    HEX_MAP_DATA_STORE, # Global store in app.py that _populate_static_stores will update
    POST_LABEL_MAPPINGS_STORE, # Global store in app.py
    deputies_data # Global store in app.py, process_deputies writes to it
)
from hex_map import load_hex_map, load_post_label_mapping # These are from root level

def _populate_static_stores(app_instance):
    """Populates global data stores in app.py (HEX_MAP_DATA_STORE, deputies_data, etc.).
    These are used by functions in app.py like update_queue and by blueprints.
    """
    app_instance.logger.info("Populating static data stores (HEX_MAP_DATA_STORE, deputies_data, etc.)...")
    for country_code in COUNTRIES_CONFIG.keys():
        app_instance.logger.debug(f"Populating static stores for country: {country_code}")

        # Deputies Data (process_deputies updates global deputies_data in app.py)
        df_country = fetch_csv(country_code) # from ..app
        if not df_country.empty:
            process_deputies(df_country, country_code) # from ..app
            app_instance.logger.debug(f"Processed deputies for {country_code} into global store.")
        else:
            app_instance.logger.warning(f"CSV data for {country_code} was empty for deputies processing.")
            # Ensure structure exists even if empty for global deputies_data in app.py
            if country_code not in deputies_data:
                 deputies_data[country_code] = {'with_images': [], 'without_images': []}
            elif 'with_images' not in deputies_data[country_code]: # Check specific keys
                 deputies_data[country_code]['with_images'] = []
            elif 'without_images' not in deputies_data[country_code]: # Check specific keys
                 deputies_data[country_code]['without_images'] = []


        # HEX_MAP_DATA_STORE (updates global HEX_MAP_DATA_STORE in app.py)
        map_path = COUNTRIES_CONFIG[country_code]['map_shape_path']
        if os.path.exists(map_path):
            HEX_MAP_DATA_STORE[country_code] = load_hex_map(map_path) # load_hex_map from hex_map.py
            app_instance.logger.debug(f"Loaded hex map for {country_code} into global store.")
        else:
            app_instance.logger.error(f"Map file not found: {map_path} for {country_code}")
            HEX_MAP_DATA_STORE[country_code] = None # Ensure it's set to None if file not found

        # POST_LABEL_MAPPINGS_STORE (updates global POST_LABEL_MAPPINGS_STORE in app.py)
        post_label_path = COUNTRIES_CONFIG[country_code].get('post_label_mapping_path')
        if post_label_path and os.path.exists(post_label_path):
            POST_LABEL_MAPPINGS_STORE[country_code] = load_post_label_mapping(post_label_path) # from hex_map.py
            app_instance.logger.debug(f"Loaded post label mapping for {country_code} into global store.")
        else:
            POST_LABEL_MAPPINGS_STORE[country_code] = pd.DataFrame() # Empty DataFrame
            if post_label_path: # Log if path was given but not found
                 app_instance.logger.warning(f"Post label mapping file not found: {post_label_path} for {country_code}.")
            # else: # No need to log if no path was specified, it's normal for some. Debug log in app.py handles this.


def initialize_application(app_instance): # app_instance is the Flask app from create_app
    app_instance.logger.info("Data Initializer: Starting application data initialization...")

    # DATABASE_URL is read from os.environ in app.py and used by init_db, load_prayed_for_data_from_db, update_queue
    # Check if it's available to decide if DB operations can proceed.
    # app_instance.config.get('DATABASE_URL') would be from project/config.py which also reads from os.environ.
    effective_db_url = os.environ.get('DATABASE_URL')
    if not effective_db_url: # Check the one app.py's functions will use
        app_instance.logger.error("Data Initializer: DATABASE_URL environment variable is not set. Critical.")
        # Populate static stores that don't depend on the DB itself, but update_queue (DB dependent) needs them.
        _populate_static_stores(app_instance)
        app_instance.logger.info("Data Initializer: Static data stores populated. DB-dependent initializations will likely fail or be skipped.")
        # Allow to proceed so errors in DB functions are caught and logged there if DATABASE_URL is missing.

    # 1. Initialize Database Schema (init_db from ..app uses global DATABASE_URL from os.environ)
    init_db() # This will log its own error if DATABASE_URL is missing.
    app_instance.logger.info("Data Initializer: Database schema initialization attempted.")

    # 2. Populate static data stores (these are globals in app.py, needed by update_queue and routes)
    # These globals are used by functions in app.py and by blueprints.
    _populate_static_stores(app_instance)
    app_instance.logger.info("Data Initializer: Static data stores (globals in app.py) populated.")

    # 3. Load 'prayed' data from DB into the global `prayed_for_data` store (in app.py)
    load_prayed_for_data_from_db() # from ..app
    app_instance.logger.info("Data Initializer: Prayed-for data loading from DB attempted.")

    # 4. Seed/Update the prayer queue
    # update_queue (from ..app) uses the global stores populated by _populate_static_stores
    # and the global prayed_for_data populated by load_prayed_for_data_from_db.
    update_queue()
    app_instance.logger.info("Data Initializer: Prayer queue update/seed attempted.")

    app_instance.logger.info("Data Initializer: Application data initialization process complete.")
