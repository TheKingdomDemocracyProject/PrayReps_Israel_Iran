from flask import current_app
from datetime import datetime
import pandas as pd
import numpy as np
import random
import psycopg2  # For PostgreSQL
from psycopg2.extras import DictCursor  # To fetch rows as dictionaries

# Import from new utility modules within the 'project' package
from ..db_utils import get_db_conn, DATABASE_URL

# --- Data Fetching and Processing (from original app.py, to be adapted) ---


def fetch_csv_data(country_code):
    """Fetches CSV data for a given country."""
    csv_path = current_app.config["COUNTRIES_CONFIG"][country_code]["csv_path"]
    try:
        df = pd.read_csv(csv_path)
        df = df.replace({np.nan: None})  # Replace NaN with None for DB compatibility
        current_app.logger.debug(
            f"Successfully fetched {len(df)} rows from {csv_path} for {country_code}."
        )
        return df
    except FileNotFoundError:
        current_app.logger.error(f"CSV file not found for {country_code} at {csv_path}")
        return pd.DataFrame()
    except Exception as e:
        current_app.logger.error(
            f"Error reading CSV for {country_code} at {csv_path}: {e}"
        )
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
        current_app.logger.warning(
            f"No deputies to process for {country_code} as DataFrame is empty."
        )
        return {"with_images": [], "without_images": []}

    for _index, row in df_country.iterrows():
        image_url = row.get("image_url")
        processed_row = row.to_dict()
        if not image_url:
            deputies_without_images.append(processed_row)
        else:
            # In original app.py, 'Image' was added to row. Not strictly needed if 'image_url' is used.
            # processed_row['Image'] = image_url
            deputies_with_images.append(processed_row)

    current_app.logger.debug(
        f"Processed deputies for {country_code}: {len(deputies_with_images)} with, "
        f"{len(deputies_without_images)} without images."
    )
    return {
        "with_images": deputies_with_images,
        "without_images": deputies_without_images,
    }


# --- Queue Management (interacting with prayer_candidates table) ---


def get_queued_representatives(limit=None):
    """Gets representatives from the prayer_candidates table with status 'queued' (PostgreSQL)."""
    items = []
    conn = None
    if not DATABASE_URL:
        current_app.logger.error(
            "DATABASE_URL not set, cannot fetch queued representatives."
        )
        return items
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            query = """
                SELECT id, person_name, post_label, country_code, party, thumbnail,
                       initial_add_timestamp AS added_timestamp, hex_id, status_timestamp
                FROM prayer_candidates
                WHERE status = 'queued'
                ORDER BY id ASC
            """
            params = []
            if limit:
                query += " LIMIT %s"
                params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            items = [dict(row) for row in rows]
            current_app.logger.debug(
                f"Fetched {len(items)} 'queued' representatives (PostgreSQL)."
            )
    except psycopg2.Error as e:
        current_app.logger.error(f"PostgreSQL error in get_queued_representatives: {e}")
    except Exception as e_gen:
        current_app.logger.error(
            f"Unexpected error in get_queued_representatives: {e_gen}", exc_info=True
        )
    finally:
        if conn:
            conn.close()
    return items


def get_next_queued_representative():
    """Gets the next representative from the queue (oldest by ID) (PostgreSQL)."""
    items = get_queued_representatives(limit=1)
    return items[0] if items else None


def get_prayed_representatives(country_code=None):
    """Gets representatives from prayer_candidates with status 'prayed' (PostgreSQL)."""
    items = []
    conn = None
    if not DATABASE_URL:
        current_app.logger.error(
            "DATABASE_URL not set, cannot fetch prayed representatives."
        )
        return items
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            query = """
                SELECT id, person_name, post_label, country_code, party, thumbnail,
                       status_timestamp AS timestamp, hex_id
                FROM prayer_candidates
                WHERE status = 'prayed'
            """
            params = []
            if country_code:
                query += " AND country_code = %s"
                params.append(country_code)
            query += " ORDER BY status_timestamp DESC"  # Show most recent first

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            items = [dict(row) for row in rows]
            current_app.logger.debug(
                f"Fetched {len(items)} 'prayed' representatives (country: {country_code or 'all'}) (PostgreSQL)."
            )
    except psycopg2.Error as e:
        current_app.logger.error(f"PostgreSQL error in get_prayed_representatives: {e}")
    except Exception as e_gen:
        current_app.logger.error(
            f"Unexpected error in get_prayed_representatives: {e_gen}", exc_info=True
        )
    finally:
        if conn:
            conn.close()
    return items


def mark_representative_as_prayed(candidate_id):
    """Updates a representative's status to 'prayed' (PostgreSQL)."""
    conn = None
    if not DATABASE_URL:
        current_app.logger.error(
            "DATABASE_URL not set, cannot mark representative as prayed."
        )
        return None, 0

    now_timestamp = datetime.now()  # Use datetime object for psycopg2

    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            # First, fetch the item to ensure it exists and is queued
            cursor.execute(
                "SELECT * FROM prayer_candidates WHERE id = %s AND status = 'queued'",
                (candidate_id,),
            )
            item_to_update_row = cursor.fetchone()

            if not item_to_update_row:
                current_app.logger.warning(
                    f"Attempted to mark item ID {candidate_id} as prayed, but it was not "
                    f"found or not in 'queued' state (PostgreSQL)."
                )
                return None, 0

            item_to_update = dict(item_to_update_row)

            cursor.execute(
                """
                UPDATE prayer_candidates
                SET status = 'prayed', status_timestamp = %s
                WHERE id = %s AND status = 'queued'
            """,
                (now_timestamp, candidate_id),
            )

            rows_affected = cursor.rowcount
            if rows_affected > 0:
                conn.commit()
                current_app.logger.info(
                    f"Marked representative ID {candidate_id} as 'prayed' (PostgreSQL)."
                )
                processed_item_details = item_to_update
                processed_item_details["status"] = "prayed"
                # Ensure timestamp is in a consistent string format if needed by frontend, though DB stores it as TIMESTAMP
                processed_item_details["timestamp"] = now_timestamp.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                return processed_item_details, rows_affected
            else:
                conn.rollback()  # Should not happen if initial check passed
                current_app.logger.warning(
                    f"Mark as prayed for ID {candidate_id} (PostgreSQL) affected 0 rows, "
                    f"despite initial check."
                )
                return None, 0
    except psycopg2.Error as e:
        current_app.logger.error(
            f"PostgreSQL error marking representative ID {candidate_id} as prayed: {e}"
        )
        if conn:
            conn.rollback()
        return None, 0
    except Exception as e_gen:
        current_app.logger.error(
            f"Unexpected error in mark_representative_as_prayed (PG): {e_gen}",
            exc_info=True,
        )
        if conn:
            conn.rollback()
        return None, 0
    finally:
        if conn:
            conn.close()


def put_representative_back_in_queue(candidate_id, new_hex_id=None):
    """
    Updates a representative's status to 'queued' (PostgreSQL).
    If new_hex_id is provided, it also updates the hex_id.
    """
    conn = None
    if not DATABASE_URL:
        current_app.logger.error(
            "DATABASE_URL not set, cannot put representative back in queue."
        )
        return 0

    now_timestamp = datetime.now()  # Use datetime object

    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM prayer_candidates WHERE id = %s AND status = 'prayed'",
                (candidate_id,),
            )
            item_to_update_row = cursor.fetchone()

            if not item_to_update_row:
                current_app.logger.warning(
                    f"Attempted to put item ID {candidate_id} back in queue (PG), but it "
                    f"was not found or not in 'prayed' state."
                )
                return 0

            item_to_update = dict(item_to_update_row)
            final_hex_id = (
                new_hex_id if new_hex_id is not None else item_to_update["hex_id"]
            )

            cursor.execute(
                """
                UPDATE prayer_candidates
                SET status = 'queued', status_timestamp = %s, hex_id = %s
                WHERE id = %s AND status = 'prayed'
            """,
                (now_timestamp, final_hex_id, candidate_id),
            )

            rows_affected = cursor.rowcount
            if rows_affected > 0:
                conn.commit()
                current_app.logger.info(
                    f"Put representative ID {candidate_id} back to 'queued' (PG), hex_id set to {final_hex_id}."
                )
            else:
                conn.rollback()  # Should not happen
                current_app.logger.warning(
                    f"Put back for ID {candidate_id} (PG) affected 0 rows."
                )
            return rows_affected
    except psycopg2.Error as e:
        current_app.logger.error(
            f"PostgreSQL error putting representative ID {candidate_id} back to queue: {e}"
        )
        if conn:
            conn.rollback()
        return 0
    except Exception as e_gen:
        current_app.logger.error(
            f"Unexpected error in put_representative_back_in_queue (PG): {e_gen}",
            exc_info=True,
        )
        if conn:
            conn.rollback()
        return 0
    finally:
        if conn:
            conn.close()


def get_available_hex_id_for_country(country_code, exclude_candidate_id=None):
    """
    Finds an available hex_id for a given country from its map (PostgreSQL version).
    """
    conn = None
    if not DATABASE_URL:
        current_app.logger.error("DATABASE_URL not set, cannot get available hex_id.")
        return None

    # hex_map_gdf is expected to be on current_app, populated by data_initializer
    # from the main app.HEX_MAP_DATA_STORE
    hex_map_gdf = current_app.hex_map_data_store.get(country_code)

    if hex_map_gdf is None or hex_map_gdf.empty or "id" not in hex_map_gdf.columns:
        current_app.logger.warning(
            f"Hex map data or 'id' column not available for {country_code} via "
            f"current_app.hex_map_data_store. Cannot assign hex_id."
        )
        return None

    all_map_hex_ids = set(hex_map_gdf["id"].unique())

    used_hex_ids = set()
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            query = """
                SELECT hex_id FROM prayer_candidates
                WHERE country_code = %s AND hex_id IS NOT NULL AND (status = 'prayed' OR status = 'queued')
            """
            params = [country_code]
            if exclude_candidate_id:
                query += " AND id != %s"
                params.append(exclude_candidate_id)

            cursor.execute(query, tuple(params))
            used_hex_rows = cursor.fetchall()
            used_hex_ids = {row["hex_id"] for row in used_hex_rows}

    except psycopg2.Error as e:
        current_app.logger.error(
            f"PostgreSQL error fetching used hex_ids for {country_code}: {e}"
        )
        return None  # Cannot determine available hex_ids
    except Exception as e_gen:
        current_app.logger.error(
            f"Unexpected error in get_available_hex_id_for_country (PG db part): {e_gen}",
            exc_info=True,
        )
        return None
    finally:
        if conn:
            conn.close()

    available_hex_ids = list(all_map_hex_ids - used_hex_ids)
    if not available_hex_ids:
        current_app.logger.warning(
            f"No available hex_ids to assign in {country_code} (PG)."
        )
        return None

    random.shuffle(available_hex_ids)
    assigned_hex_id = available_hex_ids.pop()
    current_app.logger.info(
        f"Assigned available hex_id {assigned_hex_id} for {country_code} (PG)."
    )
    return assigned_hex_id


def purge_all_data():
    """Deletes all records from the prayer_candidates table (PostgreSQL)."""
    conn = None
    if not DATABASE_URL:
        current_app.logger.error("DATABASE_URL not set, cannot purge data.")
        return False
    try:
        conn = get_db_conn()
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM prayer_candidates")
            # No need to delete from prayer_queue or prayed_items as they are legacy SQLite tables
            conn.commit()
            current_app.logger.info(
                f"Purged all {cursor.rowcount} items from prayer_candidates table (PostgreSQL)."
            )
        return True
    except psycopg2.Error as e:
        current_app.logger.error(f"PostgreSQL error during purge: {e}")
        if conn:
            conn.rollback()
        return False
    except Exception as e_gen:
        current_app.logger.error(
            f"Unexpected error in purge_all_data (PG): {e_gen}", exc_info=True
        )
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()


# --- Statistics ---
def get_party_statistics(country_code):
    """Calculates prayed-for counts by party for a given country (uses PG get_prayed_representatives)."""
    prayed_items_for_country = get_prayed_representatives(
        country_code
    )  # This now uses PostgreSQL
    party_counts = {}

    # Use APP_COUNTRIES_CONFIG if direct import, else current_app.config['PARTY_INFO']
    # Assuming PARTY_INFO is correctly set on current_app.config by the factory
    country_party_info_map = current_app.config["PARTY_INFO"].get(country_code, {})
    other_party_default = {"short_name": "Other", "color": "#CCCCCC"}

    for item in prayed_items_for_country:
        party_name = item.get("party", "Other")
        party_details = country_party_info_map.get(
            party_name, country_party_info_map.get("Other", other_party_default)
        )
        short_name = party_details["short_name"]
        party_counts[short_name] = party_counts.get(short_name, 0) + 1

    sorted_party_counts = sorted(party_counts.items(), key=lambda x: x[1], reverse=True)
    current_app.logger.debug(
        f"Calculated party statistics for {country_code} (PG): {sorted_party_counts}"
    )
    return sorted_party_counts, country_party_info_map


def get_timedata_statistics(country_code):
    """Gets timestamped prayer data for a country or overall (uses PG get_prayed_representatives)."""
    items_for_timedata = []
    # Use APP_COUNTRIES_CONFIG if direct import, else current_app.config['COUNTRIES_CONFIG']
    target_countries = current_app.config["COUNTRIES_CONFIG"]

    if country_code == "overall":
        for c_code in target_countries.keys():
            items_for_timedata.extend(get_prayed_representatives(c_code))  # PG
        items_for_timedata.sort(key=lambda x: x.get("timestamp", ""))
    else:
        items_for_timedata = get_prayed_representatives(country_code)  # PG

    timestamps = []
    values = []
    for item in items_for_timedata:
        # Timestamps from DictCursor (psycopg2) might be datetime objects.
        # Ensure they are formatted as strings if the consumer expects strings.
        ts_value = item.get("timestamp")
        if isinstance(ts_value, datetime):
            ts_str = ts_value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(ts_value, str):
            ts_str = ts_value  # Already a string
        else:
            ts_str = None

        if ts_str:
            timestamps.append(ts_str)
            value_detail = {
                "place": item.get("post_label"),
                "person": item.get("person_name"),
                "party": item.get("party"),
            }
            if country_code == "overall":
                item_country_code = item.get("country_code")
                value_detail["country"] = target_countries.get(
                    item_country_code, {}
                ).get("name", "Unknown")
            values.append(value_detail)

    current_app.logger.debug(
        f"Fetched timedata for {country_code} (PG): {len(timestamps)} entries."
    )
    return {"timestamps": timestamps, "values": values}


def get_overall_prayed_count():
    """Gets the total count of prayed-for items across all countries (PostgreSQL)."""
    count = 0
    conn = None
    if not DATABASE_URL:
        current_app.logger.error(
            "DATABASE_URL not set, cannot get overall prayed count."
        )
        return count
    try:
        conn = get_db_conn()
        with conn.cursor() as cursor:  # No DictCursor needed for simple count
            cursor.execute(
                "SELECT COUNT(id) FROM prayer_candidates WHERE status = 'prayed'"
            )
            row = cursor.fetchone()
            count = row[0] if row else 0
            current_app.logger.debug(f"Overall prayed count from DB (PG): {count}")
    except psycopg2.Error as e:
        current_app.logger.error(f"PostgreSQL error in get_overall_prayed_count: {e}")
    except Exception as e_gen:
        current_app.logger.error(
            f"Unexpected error in get_overall_prayed_count (PG): {e_gen}", exc_info=True
        )
    finally:
        if conn:
            conn.close()
    return count


# The `update_queue` function from app.py is complex and involves initial data seeding.
# It will be part of the `data_initializer.py` module or a dedicated seeding service,
# as it's more about initial population than ongoing prayer request processing.
# This service focuses on operations related to existing prayer candidates.
