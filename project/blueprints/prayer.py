from flask import (
    Blueprint,
    render_template,
    current_app,
    redirect,
    url_for,
    jsonify,
    request,
)
from datetime import datetime

# Updated: 2024-07-30 10:00:00 UTC to try and force recompile
import os
import sys
import json

# --- Import Helper ---
# try:
from ..services import prayer_service, map_service
from ..utils import format_pretty_timestamp

# except (ImportError, ValueError):
#     PROJECT_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#     if PROJECT_ROOT_PATH not in sys.path:
#         sys.path.append(PROJECT_ROOT_PATH)
#     from project.services import prayer_service, map_service
#     try:
#         from utils import format_pretty_timestamp # Assuming utils.py is in root for now
#     except ImportError:
#         def format_pretty_timestamp(ts_str): return ts_str
#         if current_app:
#              current_app.logger.error("Critical: format_pretty_timestamp could not be imported for prayer blueprint.")
# --- End Import Helper ---

bp = Blueprint("prayer", __name__, url_prefix="/prayer")


@bp.route("/process_item_htmx", methods=["POST"])
def process_item_htmx():
    item_id_str = request.form.get("item_id")
    current_app.logger.info(f"HTMX request to process item ID: {item_id_str}")

    if not item_id_str:
        current_app.logger.error("Missing item_id in HTMX request to process_item.")
        return "Error: Missing item_id", 400

    try:
        item_id_to_process = int(item_id_str)
    except ValueError:
        current_app.logger.error(f"Invalid item_id format: {item_id_str}")
        return "Error: Invalid item_id format", 400

    processed_item_details, rows_affected = (
        prayer_service.mark_representative_as_prayed(item_id_to_process)
    )

    if processed_item_details and rows_affected > 0:
        current_app.logger.info(
            f"Successfully processed item ID {item_id_to_process} as prayed."
        )

        country_code = processed_item_details["country_code"]
        prayed_for_map_country = prayer_service.get_prayed_representatives(
            country_code=country_code
        )
        current_queue_items_for_map = prayer_service.get_queued_representatives()
        map_service.generate_country_map_image(
            country_code, prayed_for_map_country, current_queue_items_for_map
        )
        map_image_path_updated = (
            url_for("static", filename="hex_map.png")
            + f"?v={datetime.now().timestamp()}"
        )

        next_item_to_display = prayer_service.get_next_queued_representative()

        total_possible_in_csvs = 0
        for cc_config_iter in current_app.config[
            "COUNTRIES_CONFIG"
        ]:  # Renamed loop variable
            df = prayer_service.fetch_csv_data(cc_config_iter)
            num_to_select = current_app.config["COUNTRIES_CONFIG"][cc_config_iter].get(
                "total_representatives", len(df)
            )
            total_possible_in_csvs += min(
                len(df), num_to_select if num_to_select is not None else float("inf")
            )
        prayed_count_overall = prayer_service.get_overall_prayed_count()
        current_remaining = total_possible_in_csvs - prayed_count_overall
        queue_size = len(current_queue_items_for_map)

        current_item_html = render_template(
            "partials/_current_item_display.html", current=next_item_to_display
        )
        map_html = render_template(
            "partials/_map_image_display.html", map_image_path=map_image_path_updated
        )
        stats_summary_html = render_template(
            "partials/_stats_summary.html",
            remaining=current_remaining,
            queue_size=queue_size,
            total_prayed_overall=prayed_count_overall,
        )

        # For HTMX out-of-band swaps, ensure partials are designed to be swapped with an ID
        # and the main response targets one container, while others are marked with hx-swap-oob.
        # The _current_item_display.html should be the main content of the response.
        # The map_html and stats_summary_html should be wrapped in divs with hx-swap-oob="true"
        # e.g. <div id="map-image-container" hx-swap-oob="true">{{ map_html_content }}</div>

        # Constructing the full response for OOB swaps:
        # The main target of the Amen button is #main-interaction-content.
        # The response should be the new content for #main-interaction-content,
        # which is essentially the re-rendered _current_item_display.html (including its own button).
        # The other partials are for OOB swaps.

        # _current_item_display.html (which includes the button)
        response_html = render_template(
            "partials/_current_item_display.html", current=next_item_to_display
        )

        # Add OOB swap elements for map and stats
        response_html += render_template(
            "partials/_map_image_display.html",
            map_image_path=map_image_path_updated,
            _oob_swap_id="map-image-container",
        )
        response_html += render_template(
            "partials/_stats_summary.html",
            remaining=current_remaining,
            queue_size=queue_size,
            total_prayed_overall=prayed_count_overall,
            _oob_swap_id="stats-summary-container",
        )

        return response_html, 200

    current_app.logger.warning(
        f"Failed to process item ID {item_id_str} or item not found/already processed."
    )
    return "", 204  # No Content, client-side can decide if any message is needed


@bp.route("/put_back_htmx", methods=["POST"])
def put_back_htmx():
    candidate_id_str = request.form.get("candidate_id")
    country_code_form = request.form.get("country_code")

    current_app.logger.info(
        f"HTMX request to put back item ID: {candidate_id_str} (Country: {country_code_form})"
    )

    if not candidate_id_str:
        current_app.logger.error("Missing candidate_id for put_back_htmx.")
        return "Error: Missing candidate_id", 400
    try:
        candidate_id = int(candidate_id_str)
    except ValueError:
        current_app.logger.error(f"Invalid candidate_id format: {candidate_id_str}")
        return "Error: Invalid candidate_id format", 400

    if (
        not country_code_form
        or country_code_form not in current_app.config["COUNTRIES_CONFIG"]
    ):
        current_app.logger.error(
            f"Invalid or missing country_code '{country_code_form}' in put_back_htmx request."
        )
        return "Error: Invalid country_code", 400

    new_hex_id_to_assign = None
    if country_code_form in ["israel", "iran"]:
        with current_app.app_context():
            new_hex_id_to_assign = prayer_service.get_available_hex_id_for_country(
                country_code_form, exclude_candidate_id=candidate_id
            )

    rows_affected = prayer_service.put_representative_back_in_queue(
        candidate_id, new_hex_id=new_hex_id_to_assign
    )

    if rows_affected > 0:
        current_app.logger.info(
            f"Successfully put item ID {candidate_id} back in queue. New hex_id (if any): {new_hex_id_to_assign}"
        )

        prayed_list_for_country_updated = prayer_service.get_prayed_representatives(
            country_code=country_code_form
        )

        current_queue_items_for_map = prayer_service.get_queued_representatives()
        map_service.generate_country_map_image(
            country_code_form,
            prayed_list_for_country_updated,
            current_queue_items_for_map,
        )

        prayed_items_display = []
        country_party_info = current_app.config["PARTY_INFO"].get(country_code_form, {})
        other_party_default = {"short_name": "Other", "color": "#CCCCCC"}
        for item_iter in prayed_list_for_country_updated:  # Renamed loop variable
            item_copy = item_iter.copy()
            item_copy["formatted_timestamp"] = format_pretty_timestamp(
                item_copy.get("timestamp")
            )
            party_name_from_log = item_copy.get("party", "Other")
            party_data = country_party_info.get(
                party_name_from_log,
                country_party_info.get("Other", other_party_default),
            )
            item_copy["party_class"] = (
                party_data["short_name"].lower().replace(" ", "-").replace("&", "and")
            )
            item_copy["party_color"] = party_data["color"]
            prayed_items_display.append(item_copy)

        updated_list_html = render_template(
            "partials/_prayed_list_table.html",
            prayed_for_list=prayed_items_display,
            country_code=country_code_form,
        )
        # This response should also trigger updates on the main page map and stats if needed.
        # For now, it updates the list on the prayed.html page.
        # Consider HX-Trigger for broader updates.
        return updated_list_html, 200

    current_app.logger.warning(
        f"Failed to put item ID {candidate_id_str} back in queue or item not found/already queued."
    )
    return "Error putting item back or item not found", 404


@bp.route("/queue_json")
def get_queue_json():
    items = prayer_service.get_queued_representatives()
    for item_iter in items:  # Renamed loop variable
        if (
            "country_code" in item_iter
            and item_iter["country_code"] in current_app.config["COUNTRIES_CONFIG"]
        ):
            item_iter["country_name"] = current_app.config["COUNTRIES_CONFIG"][
                item_iter["country_code"]
            ]["name"]
        else:
            item_iter["country_name"] = "Unknown Country"
    return jsonify(items)


@bp.route("/queue_page")
def queue_page_html():
    items = prayer_service.get_queued_representatives()
    now = datetime.now()
    return render_template("queue.html", queue=items, now=now)


# Non-HTMX version of process_item, similar to original app.py version
@bp.route("/process_item_form", methods=["POST"])
def process_item_form():
    item_id_str = request.form.get("item_id")
    current_app.logger.info(f"Form request to process item ID: {item_id_str}")

    if not item_id_str:
        current_app.logger.error("Missing item_id in form request to process_item.")
        # Handle error appropriately, e.g., flash message and redirect
        return redirect(url_for("main.home"))
    try:
        item_id_to_process = int(item_id_str)
    except ValueError:
        current_app.logger.error(f"Invalid item_id format in form: {item_id_str}")
        return redirect(url_for("main.home"))

    processed_item_details, rows_affected = (
        prayer_service.mark_representative_as_prayed(item_id_to_process)
    )

    if processed_item_details and rows_affected > 0:
        current_app.logger.info(
            f"Successfully processed item ID {item_id_to_process} via form."
        )
        country_code = processed_item_details["country_code"]
        # Regenerate map for the affected country
        prayed_for_map_country = prayer_service.get_prayed_representatives(
            country_code=country_code
        )
        current_queue_items_for_map = prayer_service.get_queued_representatives()
        map_service.generate_country_map_image(
            country_code, prayed_for_map_country, current_queue_items_for_map
        )
    else:
        current_app.logger.warning(
            f"Failed to process item ID {item_id_str} via form or item not found/already processed."
        )

    return redirect(url_for("main.home"))  # Redirect to home or queue page


# Non-HTMX version of put_back_in_queue
@bp.route("/put_back_form", methods=["POST"])
def put_back_form():
    person_name = request.form.get("person_name")
    post_label_form = request.form.get("post_label")  # This is how it was in app.py
    country_code_form = request.form.get("country_code")

    current_app.logger.info(
        f"Form request to put back item: Name='{person_name}', PostLabel='{post_label_form}', Country='{country_code_form}'"
    )

    if not all([person_name, country_code_form]):  # post_label can be None/empty
        current_app.logger.error(
            "Missing required fields (person_name, country_code) for put_back_form."
        )
        return redirect(
            url_for("prayer.prayed_list_default_redirect")
        )  # Or appropriate error page/flash

    # Logic to find candidate_id based on name, post_label, country_code
    # This requires querying the DB. prayer_service could have a helper for this.
    # For now, let's assume prayer_service.find_prayed_candidate_id_for_put_back exists or add it.
    # Simplified: direct DB access here or extend prayer_service
    from ..database import get_db  # Temporary direct DB access if service not ready

    db = get_db()
    query_post_label_value_for_db = post_label_form
    is_post_label_null_in_db_query = False
    if post_label_form is None or not post_label_form.strip():
        is_post_label_null_in_db_query = True

    sql_find = "SELECT id FROM prayer_candidates WHERE person_name = %s AND country_code = %s AND status = 'prayed'"
    params_find = [person_name, country_code_form]
    if is_post_label_null_in_db_query:
        sql_find += " AND post_label IS NULL"
    else:
        sql_find += " AND post_label = %s"
        params_find.append(query_post_label_value_for_db)

    found_item = db.execute(sql_find, tuple(params_find)).fetchone()

    if not found_item:
        current_app.logger.warning(
            f"Item not found for put_back_form: Name='{person_name}', PostLabel='{post_label_form}', Country='{country_code_form}'"
        )
        return redirect(
            url_for("prayer.prayed_list_page_html", country_code=country_code_form)
        )

    candidate_id = found_item["id"]
    new_hex_id_to_assign = None
    if country_code_form in ["israel", "iran"]:  # Hex ID logic
        with current_app.app_context():  # Ensure context for service call if it uses current_app
            new_hex_id_to_assign = prayer_service.get_available_hex_id_for_country(
                country_code_form, exclude_candidate_id=candidate_id
            )

    rows_affected = prayer_service.put_representative_back_in_queue(
        candidate_id, new_hex_id=new_hex_id_to_assign
    )

    if rows_affected > 0:
        current_app.logger.info(
            f"Successfully put item ID {candidate_id} back in queue via form."
        )
        # Regenerate map
        prayed_list_updated = prayer_service.get_prayed_representatives(
            country_code=country_code_form
        )
        current_queue_items = prayer_service.get_queued_representatives()
        map_service.generate_country_map_image(
            country_code_form, prayed_list_updated, current_queue_items
        )
    else:
        current_app.logger.warning(
            f"Failed to put item ID {candidate_id} back in queue via form."
        )

    return redirect(
        url_for("prayer.prayed_list_page_html", country_code=country_code_form)
    )


@bp.route("/prayed_list_page/<country_code>")
def prayed_list_page_html(country_code):
    if country_code == "overall":
        overall_prayed_list_display = []
        prayed_items_all = prayer_service.get_prayed_representatives(country_code=None)
        prayed_items_all.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        for item_iter in prayed_items_all:  # Renamed loop variable
            display_item = item_iter.copy()
            item_country_code = display_item.get("country_code")
            if (
                item_country_code
                and item_country_code in current_app.config["COUNTRIES_CONFIG"]
            ):
                display_item["country_name_display"] = current_app.config[
                    "COUNTRIES_CONFIG"
                ][item_country_code]["name"]
            else:
                display_item["country_name_display"] = "Unknown Country"
            display_item["formatted_timestamp"] = format_pretty_timestamp(
                item_iter.get("timestamp")
            )  # Use original item for timestamp
            overall_prayed_list_display.append(display_item)
        prayed_for_list_to_render = overall_prayed_list_display
        current_country_name = "Overall"
    elif country_code not in current_app.config["COUNTRIES_CONFIG"]:
        current_app.logger.warning(
            f"Invalid country code '{country_code}' for prayed list page. Redirecting to default."
        )
        default_country = list(current_app.config["COUNTRIES_CONFIG"].keys())[0]
        return redirect(
            url_for("prayer.prayed_list_page_html", country_code=default_country)
        )
    else:
        prayed_items_for_country = prayer_service.get_prayed_representatives(
            country_code=country_code
        )
        current_country_party_info = current_app.config["PARTY_INFO"].get(
            country_code, {}
        )
        other_party_default = {"short_name": "Other", "color": "#CCCCCC"}
        prayed_list_display_specific = []
        for item_original_iter in prayed_items_for_country:  # Renamed loop variable
            item = item_original_iter.copy()
            item["formatted_timestamp"] = format_pretty_timestamp(
                item_original_iter.get("timestamp")
            )  # Use original item for timestamp
            party_name_from_log = item.get("party", "Other")
            party_data = current_country_party_info.get(
                party_name_from_log,
                current_country_party_info.get("Other", other_party_default),
            )
            item["party_class"] = (
                party_data["short_name"].lower().replace(" ", "-").replace("&", "and")
            )
            item["party_color"] = party_data["color"]
            prayed_list_display_specific.append(item)
        prayed_for_list_to_render = prayed_list_display_specific
        current_country_name = current_app.config["COUNTRIES_CONFIG"][country_code][
            "name"
        ]

    now = datetime.now()
    return render_template(
        "prayed.html",
        prayed_for_list=prayed_for_list_to_render,
        country_code=country_code,
        country_name=current_country_name,
        now=now,
    )


@bp.route("/")
def prayed_list_default_redirect():
    if current_app.config["COUNTRIES_CONFIG"]:
        default_country_code = list(current_app.config["COUNTRIES_CONFIG"].keys())[0]
        return redirect(
            url_for("prayer.prayed_list_page_html", country_code=default_country_code)
        )
    return "No countries configured for prayed list.", 404
