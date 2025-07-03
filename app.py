# Standard library imports
import logging
from datetime import datetime
import os
import random

# Third-party imports
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import DictCursor
from flask import current_app

# current_app added for accessing app context data
# Local application imports
# Assuming these are in src/
# Assuming this is in src/

# Imports from project package
from project.db_utils import (
    get_db_conn,
    DATABASE_URL,
)  # DATABASE_URL is for checks here
from project.app_config import (
    APP_ROOT,
    APP_DATA_DIR,
    COUNTRIES_CONFIG,
    HEART_IMG_PATH,
)


# Configure logging (initial basic setup)
# This logging configuration might be superseded by the one in project/__init__.py (create_app)
# once the app context is available. For functions in this module called outside app context
# (e.g. if any were, though most are called by data_initializer within app context), this would apply.
# Consider if this basicConfig is needed or if all logging should rely on Flask app's logger.
# For now, keeping it for standalone module utility if ever needed, but Flask app logger is preferred.
# If APP_ROOT from app_config is used, ensure it's correctly defined for this file's location.
# The APP_ROOT in app_config is src/ if app.py is in src/.
log_file_path_app_direct = os.path.join(APP_ROOT, "logs_app", "app_direct.log")
os.makedirs(os.path.dirname(log_file_path_app_direct), exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format=("%(asctime)s - %(levelname)s - %(message)s (app.py direct)"),
    handlers=[
        logging.FileHandler(log_file_path_app_direct),
        logging.StreamHandler(),
    ],
)

logging.info(f"app.py: APP_ROOT imported as: {APP_ROOT}")
logging.info(f"app.py: APP_DATA_DIR imported as: {APP_DATA_DIR}")
# DATABASE_URL is imported from db_utils, so its check/logging is there.
# logging.info(
# f"DATABASE_URL (from project.db_utils): "
#    f"{'********' if DATABASE_URL else 'NOT SET'}"
# )


# Global data structures previously here (prayed_for_data, deputies_data,
# HEX_MAP_DATA_STORE, POST_LABEL_MAPPINGS_STORE) are now initialized on the
# Flask app instance in project/__init__.py (create_app). Functions in this
# module will access them via current_app.


def init_db():
    """Initializes the PostgreSQL database and creates tables if they don't exist."""
    # Uses get_db_conn from project.db_utils
    logging.info("app.py: Initializing PostgreSQL database schema...")
    conn = None
    try:
        conn = get_db_conn()  # From project.db_utils
        with conn.cursor() as cursor:
            cursor.execute(
                """
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
            """
            )
            logging.info("app.py: Ensured prayer_candidates table exists.")
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_unique
                ON prayer_candidates (person_name, post_label, country_code);
            """
            )
            logging.info(
                "app.py: Ensured idx_candidates_unique index exists on "
                "prayer_candidates table."
            )
            conn.commit()
            logging.info(
                "app.py: Successfully initialized PostgreSQL database tables "
                "and indexes."
            )
    except psycopg2.Error as e:
        logging.error(f"app.py: Error initializing PostgreSQL database: {e}")
        if conn:
            conn.rollback()
    except ValueError as ve:  # Catch DATABASE_URL not configured from get_db_conn
        logging.error(f"app.py: DB Init Error - {str(ve)}")
    finally:
        if conn:
            conn.close()


def get_current_queue_items_from_db():
    """Fetches all items from the prayer_candidates table with status 'queued', for PostgreSQL."""
    items = []
    conn = None
    if not DATABASE_URL:  # Check imported DATABASE_URL from project.db_utils
        logging.error("app.py: DATABASE_URL not set, cannot fetch queue items.")
        return items
    try:
        conn = get_db_conn()  # From project.db_utils
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, person_name, post_label, country_code, party, thumbnail,
                       initial_add_timestamp AS added_timestamp, hex_id
                FROM prayer_candidates
                WHERE status = 'queued'
                ORDER BY id ASC
            """
            )
            rows = cursor.fetchall()
            items = [dict(row) for row in rows]
            logging.info(
                f"app.py: Fetched {len(items)} 'queued' items from "
                f"prayer_candidates (PostgreSQL)."
            )
    except psycopg2.Error as e:
        logging.error(
            f"app.py: PostgreSQL error in " f"get_current_queue_items_from_db: {e}"
        )
    except Exception as e_gen:
        logging.error(
            f"app.py: Unexpected error in " f"get_current_queue_items_from_db: {e_gen}",
            exc_info=True,
        )
    finally:
        if conn:
            conn.close()
    return items


def fetch_csv(country_code):
    """Fetches CSV data for a given country using COUNTRIES_CONFIG from project.app_config."""
    # COUNTRIES_CONFIG is imported from project.app_config
    logging.debug(f"app.py: Fetching CSV data for {country_code}")
    csv_path = COUNTRIES_CONFIG[country_code]["csv_path"]
    try:
        df = pd.read_csv(csv_path)
        logging.debug(f"app.py: Successfully fetched {len(df)} rows from {csv_path}")
        df = df.replace({np.nan: None})
        logging.debug(f"app.py: Fetched data for {country_code}: {df.head()}")
        return df
    except FileNotFoundError:
        logging.error(f"app.py: CSV file not found for {country_code} at {csv_path}")
        return pd.DataFrame()


def process_deputies(csv_data, country_code):
    """Processes deputies from CSV, populates global deputies_data in this module."""
    # deputies_data is a global in this module.
    # COUNTRIES_CONFIG is used via import.
    country_deputies_with_images = []
    country_deputies_without_images = []
    for _index, row in csv_data.iterrows():  # _index unused
        image_url = row.get("image_url")
        processed_row = row.to_dict()
        if not image_url:
            country_deputies_without_images.append(processed_row)
            continue
        # Retaining 'Image' key as per original logic
        processed_row["Image"] = image_url
        country_deputies_with_images.append(processed_row)
        logging.debug(
            f"app.py: Image URL assigned for {row.get('person_name')} "
            f"({country_code}): {image_url}"
        )

    # Access deputies_data via current_app
    app_deputies_data = current_app.deputies_data

    # Ensure the country key exists in current_app.deputies_data
    if (
        country_code not in app_deputies_data
    ):  # Should have been initialized by create_app
        app_deputies_data[country_code] = {"with_images": [], "without_images": []}

    app_deputies_data[country_code]["with_images"] = country_deputies_with_images
    app_deputies_data[country_code]["without_images"] = country_deputies_without_images

    if country_deputies_without_images:
        names_without_images = ", ".join(
            [dep.get("person_name", "N/A") for dep in country_deputies_without_images]
        )
        logging.info(
            f"app.py: No images found for the following names in "
            f"{country_code}: {names_without_images}"
        )


def update_queue():
    """
    Seeds or updates the prayer queue in the PostgreSQL database.
    Uses globals from this module (HEX_MAP_DATA_STORE) and imported configs.
    Relies on current_app for Flask app context specific data if that pattern were fully adopted,
    but current HEX_MAP_DATA_STORE is a module global populated by data_initializer.
    """
    logging.info("app.py: Update_queue function execution started.")
    conn = None
    if not DATABASE_URL:  # Check imported DATABASE_URL
        logging.error(
            "app.py: [update_queue] DATABASE_URL not set. Aborting queue update."
        )
        return

    # Access HEX_MAP_DATA_STORE via current_app
    # This is populated by data_initializer.py onto the app instance.
    current_hex_map_store = current_app.hex_map_data_store

    try:
        logging.info("app.py: [update_queue] Attempting to connect to PostgreSQL DB.")
        conn = get_db_conn()  # From project.db_utils
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            logging.info(
                "app.py: [update_queue] Deleting existing 'queued' items from "
                "prayer_candidates table."
            )
            cursor.execute("DELETE FROM prayer_candidates WHERE status = 'queued'")
            logging.info(
                f"app.py: [update_queue] Deleted {cursor.rowcount} existing "
                f"'queued' items."
            )

            cursor.execute(
                "SELECT person_name, post_label, country_code "
                "FROM prayer_candidates WHERE status = 'prayed'"
            )
            already_prayed_records = cursor.fetchall()
            already_prayed_ids = set()
            for record in already_prayed_records:
                pn = record["person_name"]
                pl = record["post_label"] if record["post_label"] is not None else ""
                cc = record["country_code"]
                already_prayed_ids.add((pn, pl, cc))
            logging.info(
                f"app.py: [update_queue] Found {len(already_prayed_ids)} "
                f"individuals already marked as 'prayed'."
            )

            all_potential_candidates = []
            for country_code_collect in COUNTRIES_CONFIG.keys():  # Imported config
                df_raw = fetch_csv(
                    country_code_collect
                )  # Uses imported COUNTRIES_CONFIG
                if df_raw.empty:
                    logging.warning(
                        f"app.py: CSV data for {country_code_collect} is empty. Skipping for seeding."
                    )
                    continue

                num_to_select = COUNTRIES_CONFIG[country_code_collect].get(
                    "total_representatives"
                )
                df_sampled = df_raw.sample(
                    n=(
                        min(num_to_select, len(df_raw))
                        if num_to_select is not None
                        else len(df_raw)
                    )
                ).reset_index(drop=True)
                logging.info(
                    f"app.py: Selected {len(df_sampled)} individuals from "
                    f"{country_code_collect} CSV (before filtering prayed)."
                )

                for _index, row in df_sampled.iterrows():  # _index for unused variable
                    if row.get("person_name"):
                        item = row.to_dict()
                        item["country_code"] = country_code_collect
                        item["party"] = item.get("party") or "Other"

                        current_person_name = item["person_name"]
                        current_post_label_raw = item.get("post_label")
                        post_label_for_check = (
                            current_post_label_raw
                            if isinstance(current_post_label_raw, str)
                            and current_post_label_raw.strip()
                            else ""
                        )

                        candidate_id_tuple = (
                            current_person_name,
                            post_label_for_check,
                            item["country_code"],
                        )

                        if candidate_id_tuple not in already_prayed_ids:
                            item["post_label"] = (
                                None
                                if not post_label_for_check
                                else post_label_for_check
                            )

                            raw_image_url = item.get(
                                "image_url"
                            )  # Get raw value from CSV

                            final_thumbnail_path = None
                            # Ensure raw_image_url is a string before calling startswith
                            if raw_image_url and isinstance(raw_image_url, str):
                                if raw_image_url.startswith("static/"):
                                    final_thumbnail_path = raw_image_url[
                                        len("static/") :
                                    ]
                                elif (
                                    raw_image_url.strip()
                                ):  # Non-empty and not starting with static/
                                    final_thumbnail_path = raw_image_url.strip()

                            if (
                                not final_thumbnail_path
                            ):  # Fallback if no valid image_url from CSV
                                # HEART_IMG_PATH is "static/heart_icons/heart_red.png" from app_config
                                # We need the path relative to 'static/' for the DB.
                                if HEART_IMG_PATH.startswith("static/"):
                                    final_thumbnail_path = HEART_IMG_PATH[
                                        len("static/") :
                                    ]
                                else:
                                    # This case implies HEART_IMG_PATH is already relative or a full URL
                                    final_thumbnail_path = HEART_IMG_PATH

                            item["thumbnail"] = final_thumbnail_path
                            all_potential_candidates.append(item)
                        # else: logging.debug(...)  # Original log removed
                    # else: logging.debug(...)  # Original log removed

            logging.info(
                f"app.py: [update_queue] Collected "
                f"{len(all_potential_candidates)} new potential candidates."
            )
            random.shuffle(all_potential_candidates)

            items_added_to_db_this_cycle = 0
            available_hex_ids_by_country = {}
            random_allocation_countries = [
                "israel",
                "iran",
            ]  # Hardcoded, could be in config

            for country_code_hex_prep in random_allocation_countries:
                if country_code_hex_prep not in COUNTRIES_CONFIG:
                    continue
                hex_map_gdf_prep = current_hex_map_store.get(
                    country_code_hex_prep
                )  # Using local copy of module global
                if (
                    hex_map_gdf_prep is not None
                    and not hex_map_gdf_prep.empty
                    and "id" in hex_map_gdf_prep.columns
                ):
                    all_map_hex_ids = set(hex_map_gdf_prep["id"].unique())
                    cursor.execute(
                        "SELECT hex_id FROM prayer_candidates WHERE "
                        "country_code = %s AND hex_id IS NOT NULL AND "
                        "(status = 'prayed' OR status = 'queued')",
                        (country_code_hex_prep,),
                    )
                    used_hex_ids = {r["hex_id"] for r in cursor.fetchall()}
                    current_available_hex_ids = list(all_map_hex_ids - used_hex_ids)
                    random.shuffle(current_available_hex_ids)
                    available_hex_ids_by_country[country_code_hex_prep] = (
                        current_available_hex_ids
                    )
                    # logging.info(
                    #    f"app.py: [update_queue] For {country_code_hex_prep}: "
                    #    f"{len(all_map_hex_ids)} total, {len(used_hex_ids)} "
                    #    f"used, {len(current_available_hex_ids)} available hexes."
                    # )
                else:
                    # logging.warning(
                    #    f"app.py: [update_queue] Hex map data or 'id' "
                    #    f"column not available for {country_code_hex_prep}."
                    # )
                    available_hex_ids_by_country[country_code_hex_prep] = []

            for item_to_process_for_hex in all_potential_candidates:
                item_country_code = item_to_process_for_hex["country_code"]
                item_to_process_for_hex["hex_id"] = None
                if (
                    item_country_code in random_allocation_countries
                    and available_hex_ids_by_country.get(item_country_code)
                ):
                    item_to_process_for_hex["hex_id"] = available_hex_ids_by_country[
                        item_country_code
                    ].pop()

            for item_to_add in all_potential_candidates:
                # ... (extraction of item_to_add fields) ...
                person_name = item_to_add["person_name"]
                post_label = item_to_add.get("post_label")
                country_code_add = item_to_add["country_code"]
                party_add = item_to_add["party"]
                thumbnail_add = item_to_add["thumbnail"]
                hex_id_to_insert = item_to_add.get("hex_id")
                current_ts_for_status = (
                    datetime.now()
                )  # Use datetime object for psycopg2

                try:
                    cursor.execute(
                        """
                        INSERT INTO prayer_candidates
                            (person_name, post_label, country_code, party,
                             thumbnail, status, status_timestamp, hex_id)
                        VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s)
                        ON CONFLICT (person_name, post_label, country_code)
                        DO NOTHING
                        """,
                        (
                            person_name,
                            post_label,
                            country_code_add,
                            party_add,
                            thumbnail_add,
                            current_ts_for_status,
                            hex_id_to_insert,
                        ),
                    )
                    if cursor.rowcount > 0:
                        items_added_to_db_this_cycle += 1
                except psycopg2.Error as e_insert:
                    logging.error(
                        f"app.py: PostgreSQL error during initial seeding for "
                        f"{person_name} ({post_label}): {e_insert}"
                    )

            logging.info(
                f"app.py: [update_queue] Added {items_added_to_db_this_cycle} "
                f"new items to prayer_candidates."
            )
            cursor.execute(
                "SELECT COUNT(id) FROM prayer_candidates WHERE status = 'queued'"
            )
            current_db_candidates_size = (cursor.fetchone() or [0])[0]
            logging.info(
                f"app.py: Initial seeding complete. Current 'queued' items: "
                f"{current_db_candidates_size}"
            )
            conn.commit()
            logging.info("app.py: [update_queue] Database commit successful.")

    except psycopg2.Error as e:
        logging.error(f"app.py: [update_queue] PostgreSQL error: {e}", exc_info=True)
        if conn:
            conn.rollback()
    except Exception as e_gen:
        logging.error(f"app.py: [update_queue] Critical error: {e_gen}", exc_info=True)
        if conn:
            conn.rollback()
    finally:
        logging.info("app.py: [update_queue] Reached finally block.")
        if conn:
            conn.close()


def load_prayed_for_data_from_db():
    """Loads all prayed-for items from PostgreSQL into the global prayed_for_data in this module."""
    # Access prayed_for_data via current_app
    # COUNTRIES_CONFIG is imported.
    app_prayed_for_data = current_app.prayed_for_data  # Access from current_app

    for country in COUNTRIES_CONFIG.keys():
        app_prayed_for_data[country] = []  # Initialize/clear country's list

    conn = None
    if not DATABASE_URL:  # Imported from project.db_utils
        logging.error("app.py: DATABASE_URL not set, cannot load prayed for data.")
        return
    try:
        conn = get_db_conn()  # From project.db_utils
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(
                "SELECT person_name, post_label, country_code, party, "
                "thumbnail, status_timestamp AS timestamp, hex_id "
                "FROM prayer_candidates WHERE status = 'prayed'"
            )
            rows = cursor.fetchall()
            loaded_count = 0
            for row_data in rows:
                item = dict(row_data)
                country_code_load = item.get("country_code")
                if country_code_load in app_prayed_for_data:
                    app_prayed_for_data[country_code_load].append(item)
                    loaded_count += 1
                # else: logging.warning(...) # Original warning log
            logging.info(
                f"app.py: Loaded {loaded_count} 'prayed' items from PostgreSQL "
                f"into current_app.prayed_for_data."
            )
    except psycopg2.Error as e:
        logging.error(f"app.py: PostgreSQL error in load_prayed_for_data_from_db: {e}")
    except Exception as e_gen:
        logging.error(
            f"app.py: Unexpected error in " f"load_prayed_for_data_from_db: {e_gen}",
            exc_info=True,
        )
    finally:
        if conn:
            conn.close()


def reload_single_country_prayed_data_from_db(country_code_to_reload):
    """Reloads prayed-for items for a single country into the global prayed_for_data."""
    # Access prayed_for_data via current_app
    # COUNTRIES_CONFIG is imported.
    app_prayed_for_data = current_app.prayed_for_data  # Access from current_app

    if country_code_to_reload not in COUNTRIES_CONFIG:  # Check against imported config
        logging.warning(
            f"app.py: [reload_single_country_prayed_data_from_db] "
            f"Invalid country_code: {country_code_to_reload}"
        )
        return

    logging.info(
        f"app.py: Reloading current_app.prayed_for_data for "
        f"{country_code_to_reload} (PostgreSQL)"
    )
    app_prayed_for_data[country_code_to_reload] = []  # Modify list on current_app store

    conn = None
    if not DATABASE_URL:  # Imported
        logging.error(
            f"app.py: DATABASE_URL not set, cannot reload for "
            f"{country_code_to_reload}."
        )
        return
    try:
        conn = get_db_conn()  # From project.db_utils
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(
                "SELECT person_name, post_label, country_code, party, "
                "thumbnail, status_timestamp AS timestamp, hex_id "
                "FROM prayer_candidates "
                "WHERE status = 'prayed' AND country_code = %s",
                (country_code_to_reload,),
            )
            rows = cursor.fetchall()
            loaded_count = 0
            for row_data in rows:
                item = dict(row_data)
                app_prayed_for_data[country_code_to_reload].append(
                    item
                )  # Modify list on current_app store
                loaded_count += 1
            logging.info(
                f"app.py: Reloaded {loaded_count} 'prayed' items for "
                f"{country_code_to_reload} into current_app.prayed_for_data."
            )
    except psycopg2.Error as e:
        logging.error(
            f"app.py: PostgreSQL error reloading for " f"{country_code_to_reload}: {e}"
        )
    except Exception as e_gen:
        logging.error(
            f"app.py: Unexpected error reloading for "
            f"{country_code_to_reload}: {e_gen}",
            exc_info=True,
        )
    finally:
        if conn:
            conn.close()


# Note: The original app.py had Flask routes. These are assumed to be in blueprints.
# The __main__ block is also removed as app is run via run.py or WSGI.
