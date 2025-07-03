from flask import (
    Blueprint,
    render_template,
    current_app,
    redirect,
    url_for,
    jsonify,
)
from datetime import datetime

# --- Import Helper ---
# try:
from ..services import prayer_service, map_service
from ..utils import format_pretty_timestamp

# except (ImportError, ValueError):
#     PROJECT_ROOT_PATH = os.path.dirname(
#         os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#     )
#     if PROJECT_ROOT_PATH not in sys.path:
#         sys.path.append(PROJECT_ROOT_PATH)
#     from project.services import prayer_service, map_service
#     try:
#         # Assuming utils.py is in root for now
#         from utils import format_pretty_timestamp
#     except ImportError:
#         def format_pretty_timestamp(ts_str): return ts_str
#         if current_app:
#             current_app.logger.error(
#                 "Critical: format_pretty_timestamp could not be "
#                 "imported for main blueprint."
#             )
# --- End Import Helper ---

from hex_map import plot_hex_map_with_hearts  # For the new route


bp = Blueprint("main", __name__)


@bp.route("/generate_map_direct/<country_code>")
def generate_map_for_country_direct(country_code):
    current_app.logger.debug(
        f"[main.bp] Direct map generation for country: {country_code}"
    )
    if country_code not in current_app.config["COUNTRIES_CONFIG"]:
        current_app.logger.error(
            f"Invalid country code '{country_code}' for direct map generation."
        )
        return jsonify(error="Invalid country code"), 404

    # Access data stores from current_app, populated by data_initializer
    hex_map_gdf = current_app.hex_map_data_store.get(country_code)
    post_label_df = current_app.post_label_mappings_store.get(country_code)

    # Use prayer_service to get prayed and queued items
    prayed_list_for_map = prayer_service.get_prayed_representatives(
        country_code=country_code
    )
    current_queue_for_map = prayer_service.get_queued_representatives()

    if hex_map_gdf is None or hex_map_gdf.empty:
        current_app.logger.error(
            f"Map data (GeoDataFrame) not available for {country_code} in "
            f"direct generation."
        )
        return jsonify(error=f"Map data not available for {country_code}"), 500

    # plot_hex_map_with_hearts is imported from hex_map.py
    # It saves the map to static/hex_map.png (this path is hardcoded in
    # plot_hex_map_with_hearts)
    plot_hex_map_with_hearts(
        hex_map_gdf,
        post_label_df,  # This can be None or empty for random allocation
        prayed_list_for_map,
        current_queue_for_map,
        country_code,
    )
    # This endpoint doesn't return the map path, just confirms generation.
    # The client would then fetch the known static/hex_map.png path.
    status_msg = (
        f"Map directly generated for {country_code} at static/hex_map.png"
    )
    return (
        jsonify(status=status_msg),
        200,
    )


@bp.route("/", endpoint="home")  # Explicitly name the endpoint
def home():
    current_app.logger.info("Home page requested.")

    total_possible_in_csvs = 0
    for country_code_iter in current_app.config["COUNTRIES_CONFIG"]:
        df = prayer_service.fetch_csv_data(country_code_iter)
        num_to_select = current_app.config["COUNTRIES_CONFIG"][
            country_code_iter
        ].get("total_representatives", len(df))
        total_possible_in_csvs += min(
            len(df),
            num_to_select if num_to_select is not None else float("inf"),
        )

    prayed_count_overall = prayer_service.get_overall_prayed_count()
    current_remaining = total_possible_in_csvs - prayed_count_overall

    current_item_display = prayer_service.get_next_queued_representative()
    current_queue_items = prayer_service.get_queued_representatives()

    map_to_display_country = list(
        current_app.config["COUNTRIES_CONFIG"].keys()
    )[0]
    if current_item_display:
        map_to_display_country = current_item_display.get(
            "country_code", map_to_display_country
        )
    person_name_display = (
        current_item_display.get("person_name") if current_item_display else "None"
    )
    current_app.logger.debug(
        f"Home page: Displaying map for {map_to_display_country}. "
        f"Current item: {person_name_display}"
    )

    prayed_for_map_country = prayer_service.get_prayed_representatives(
        country_code=map_to_display_country
    )

    map_service.generate_country_map_image(
        map_to_display_country, prayed_for_map_country, current_queue_items
    )
    map_image_path = url_for(
        "static", filename="hex_map.png"
    ) + f"?v={datetime.now().timestamp()}"
    now = datetime.now()

    return render_template(
        "index.html",
        remaining=current_remaining,
        current=current_item_display,
        queue_size=len(current_queue_items),
        map_image_path=map_image_path,
        current_country_name=current_app.config["COUNTRIES_CONFIG"][
            map_to_display_country
        ]["name"],
        initial_map_country_code=map_to_display_country,
        now=now,
    )


@bp.route("/about")
def about_page():
    current_app.logger.info("About page requested.")
    now = datetime.now()
    return render_template("about.html", now=now)


@bp.route("/generate_map_for_country_json/<country_code>")
def generate_map_for_country_json_route(country_code):
    current_app.logger.info(
        f"JSON map generation request for country: {country_code}"
    )
    if country_code not in current_app.config["COUNTRIES_CONFIG"]:
        current_app.logger.error(
            f"Invalid country code '{country_code}' for map generation."
        )
        return jsonify(error="Invalid country code", map_image_path=None), 404

    prayed_for_map_country = prayer_service.get_prayed_representatives(
        country_code=country_code
    )
    current_queue_items = prayer_service.get_queued_representatives()

    success = map_service.generate_country_map_image(
        country_code, prayed_for_map_country, current_queue_items
    )

    map_image_filename = "hex_map.png"
    map_image_path = url_for(
        "static", filename=map_image_filename
    ) + f"?v={datetime.now().timestamp()}"

    if success:
        current_app.logger.debug(
            f"Map for {country_code} generated, path: {map_image_path}"
        )
        return (
            jsonify(
                status=f"Map generated for {country_code}",
                map_image_path=map_image_path,
            ),
            200,
        )
    else:
        current_app.logger.error(
            f"Map generation failed for {country_code}, "
            f"serving placeholder path."
        )
        return (
            jsonify(
                error=f"Map generation failed for {country_code}",
                map_image_path=map_image_path,
            ),
            500,
        )


@bp.route("/purge")
def purge_data_route():
    current_app.logger.info("Purge data route accessed.")
    success = prayer_service.purge_all_data()
    if not success:
        current_app.logger.error("Data purge operation failed.")
        return redirect(url_for("main.home"))

    # Corrected import
    from ..data_initializer import _seed_initial_prayer_queue

    with current_app.app_context():
        _seed_initial_prayer_queue()

    current_app.logger.info("Data purged and queue re-seeded successfully.")
    default_country = list(current_app.config["COUNTRIES_CONFIG"].keys())[0]
    if default_country:
        with current_app.app_context():
            map_service.generate_country_map_image(default_country, [], [])

    return redirect(url_for("main.home"))


@bp.route("/refresh")
def refresh_data_route():
    current_app.logger.info("Refresh endpoint called. Redirecting to home.")
    return redirect(url_for("main.home"))


bp.add_app_template_filter(format_pretty_timestamp)


@bp.app_context_processor
def inject_global_template_variables():
    return dict(
        party_info_all_countries=current_app.config["PARTY_INFO"],
        all_countries_config=current_app.config["COUNTRIES_CONFIG"],
        HEART_IMG_PATH_RELATIVE=(
            current_app.config["HEART_IMG_PATH_RELATIVE"]
        ),
    )
