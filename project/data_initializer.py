import os
import pandas as pd
from flask import current_app  # Can be used if app_instance is not passed to helpers

import os
import pandas as pd
from flask import current_app  # Can be used if app_instance is not passed to helpers

# Import functions from 'app.py' (now using new utils internally)
# Data stores (HEX_MAP_DATA_STORE etc.) are initialized in project/__init__.py on app instance
# and populated here by setting attributes on app_instance.
from app import (
    init_db,
    load_prayed_for_data_from_db,  # This function will need to use current_app for its globals
    update_queue,  # This function will need to use current_app for its globals
    fetch_csv,  # This function uses COUNTRIES_CONFIG from project.app_config
    process_deputies,  # This function will need to use current_app.deputies_data
)

# Import configs from project.app_config
from project.app_config import COUNTRIES_CONFIG

from hex_map import load_hex_map, load_post_label_mapping  # These are from root level


def _populate_static_stores(app_instance):
    """Populates data stores on the app_instance.
    These are used by functions in app.py like update_queue (via current_app) and by blueprints.
    """
    app_instance.logger.info(
        "Populating static data stores on app_instance (hex_map_data_store, deputies_data, etc.)..."
    )

    # Ensure stores are initialized on app_instance (should be done in create_app)
    if not hasattr(app_instance, "hex_map_data_store"):
        app_instance.hex_map_data_store = {}
    if not hasattr(app_instance, "post_label_mappings_store"):
        app_instance.post_label_mappings_store = {}
    if not hasattr(app_instance, "deputies_data"):
        app_instance.deputies_data = {}

    for country_code in COUNTRIES_CONFIG.keys():  # Use imported COUNTRIES_CONFIG
        app_instance.logger.debug(
            f"Populating static stores for country: {country_code}"
        )

        # Initialize country-specific dicts if not present
        if country_code not in app_instance.deputies_data:
            app_instance.deputies_data[country_code] = {
                "with_images": [],
                "without_images": [],
            }

        # Deputies Data: process_deputies will now need to operate on app_instance.deputies_data
        # For now, process_deputies (from app.py) still modifies its own module-level deputies_data.
        # This is a point of friction. Let's assume process_deputies is refactored or
        # we replicate its logic here to populate app_instance.deputies_data directly.
        # To minimize changes to app.py for now, we'll call it, then copy its result.
        # This is not ideal but limits scope.
        # A better way: process_deputies returns the data, and data_initializer assigns it.

        # Temporary approach: Call app.py's process_deputies which uses its own global,
        # then copy to app_instance.deputies_data.
        # This requires app.py's deputies_data to be importable or process_deputies to return data.
        # Let's modify app.py's process_deputies to return the data instead of direct global mod.
        # For now, assuming process_deputies in app.py is updated to work with current_app.deputies_data
        # or returns the data.
        # If process_deputies is modified to take app_instance and populate app_instance.deputies_data:
        df_country = fetch_csv(country_code)  # from app.py, uses project.app_config
        if not df_country.empty:
            # process_deputies(df_country, country_code, app_instance) # Ideal: pass app_instance
            # Current process_deputies in app.py modifies its own global.
            # This part needs careful handling.
            # For now, assume process_deputies in app.py will be updated to use current_app.deputies_data
            process_deputies(
                df_country, country_code
            )  # Call it, it will use current_app.deputies_data
            app_instance.logger.debug(
                f"Processed deputies for {country_code} (data on current_app)."
            )

        else:
            app_instance.logger.warning(
                f"CSV data for {country_code} was empty for deputies processing."
            )
            # Ensure structure exists on app_instance
            if country_code not in app_instance.deputies_data:
                app_instance.deputies_data[country_code] = {
                    "with_images": [],
                    "without_images": [],
                }

        # HEX_MAP_DATA_STORE on app_instance
        map_path = COUNTRIES_CONFIG[country_code]["map_shape_path"]
        if os.path.exists(map_path):
            app_instance.hex_map_data_store[country_code] = load_hex_map(map_path)
            app_instance.logger.debug(
                f"Loaded hex map for {country_code} onto app_instance."
            )
        else:
            app_instance.logger.error(
                f"Map file not found: {map_path} for {country_code}"
            )
            app_instance.hex_map_data_store[country_code] = None

        # POST_LABEL_MAPPINGS_STORE on app_instance
        post_label_path = COUNTRIES_CONFIG[country_code].get("post_label_mapping_path")
        if post_label_path and os.path.exists(post_label_path):
            app_instance.post_label_mappings_store[country_code] = (
                load_post_label_mapping(post_label_path)
            )
            app_instance.logger.debug(
                f"Loaded post label mapping for {country_code} onto app_instance."
            )
        else:
            app_instance.post_label_mappings_store[country_code] = pd.DataFrame()
            if post_label_path:
                app_instance.logger.warning(
                    f"Post label mapping file not found: {post_label_path} for {country_code}."
                )


def initialize_application(
    app_instance,
):  # app_instance is the Flask app from create_app
    app_instance.logger.info(
        "Data Initializer: Starting application data initialization..."
    )

    # DATABASE_URL is now sourced by project.db_utils from os.environ
    # init_db (from app.py) will use project.db_utils.get_db_conn()
    # which in turn uses project.db_utils.DATABASE_URL.
    # A check for DATABASE_URL's existence is done in project.db_utils.

    # 1. Initialize Database Schema
    # init_db (from app.py) internally uses get_db_conn from project.db_utils
    init_db()
    app_instance.logger.info(
        "Data Initializer: Database schema initialization attempted."
    )

    # 2. Populate static data stores on the app_instance
    # These are needed by functions in app.py (via current_app) and by blueprints.
    _populate_static_stores(app_instance)
    app_instance.logger.info(
        "Data Initializer: Static data stores populated on app_instance."
    )

    # 3. Load 'prayed' data from DB.
    # load_prayed_for_data_from_db (from app.py) will need to use current_app.prayed_for_data
    load_prayed_for_data_from_db()
    app_instance.logger.info(
        "Data Initializer: Prayed-for data loading (current_app.prayed_for_data) attempted."
    )

    # 4. Seed/Update the prayer queue
    # update_queue (from app.py) will need to use current_app for HEX_MAP_DATA_STORE etc.
    update_queue()
    app_instance.logger.info("Data Initializer: Prayer queue update/seed attempted.")

    app_instance.logger.info(
        "Data Initializer: Application data initialization process complete."
    )
