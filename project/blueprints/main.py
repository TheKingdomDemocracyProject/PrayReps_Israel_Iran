from flask import Blueprint, render_template, current_app, redirect, url_for, jsonify
from datetime import datetime
import os
import sys

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
#              current_app.logger.error("Critical: format_pretty_timestamp could not be imported for main blueprint.")
# --- End Import Helper ---

bp = Blueprint('main', __name__)

@bp.route('/')
def home():
    current_app.logger.info("Home page requested.")

    total_possible_in_csvs = 0
    for country_code_iter in current_app.config['COUNTRIES_CONFIG']: # Changed variable name
        df = prayer_service.fetch_csv_data(country_code_iter)
        num_to_select = current_app.config['COUNTRIES_CONFIG'][country_code_iter].get('total_representatives', len(df))
        total_possible_in_csvs += min(len(df), num_to_select if num_to_select is not None else float('inf'))

    prayed_count_overall = prayer_service.get_overall_prayed_count()
    current_remaining = total_possible_in_csvs - prayed_count_overall

    current_item_display = prayer_service.get_next_queued_representative()
    current_queue_items = prayer_service.get_queued_representatives()

    map_to_display_country = list(current_app.config['COUNTRIES_CONFIG'].keys())[0]
    if current_item_display:
        map_to_display_country = current_item_display.get('country_code', map_to_display_country)

    current_app.logger.debug(f"Home page: Displaying map for {map_to_display_country}. Current item: {current_item_display.get('person_name') if current_item_display else 'None'}")

    prayed_for_map_country = prayer_service.get_prayed_representatives(country_code=map_to_display_country)

    map_service.generate_country_map_image(
        map_to_display_country,
        prayed_for_map_country,
        current_queue_items
    )
    map_image_path = url_for('static', filename='hex_map.png') + f"?v={datetime.now().timestamp()}"
    now = datetime.now()

    return render_template('index.html',
                           remaining=current_remaining,
                           current=current_item_display,
                           queue_size=len(current_queue_items),
                           map_image_path=map_image_path,
                           current_country_name=current_app.config['COUNTRIES_CONFIG'][map_to_display_country]['name'],
                           initial_map_country_code=map_to_display_country,
                           now=now
                           )

@bp.route('/about')
def about_page():
    current_app.logger.info("About page requested.")
    now = datetime.now()
    return render_template('about.html', now=now)

@bp.route('/generate_map_for_country_json/<country_code>')
def generate_map_for_country_json_route(country_code):
    current_app.logger.info(f"JSON map generation request for country: {country_code}")
    if country_code not in current_app.config['COUNTRIES_CONFIG']:
        current_app.logger.error(f"Invalid country code '{country_code}' for map generation.")
        return jsonify(error='Invalid country code', map_image_path=None), 404

    prayed_for_map_country = prayer_service.get_prayed_representatives(country_code=country_code)
    current_queue_items = prayer_service.get_queued_representatives()

    success = map_service.generate_country_map_image(
        country_code,
        prayed_for_map_country,
        current_queue_items
    )

    map_image_filename = "hex_map.png"
    map_image_path = url_for('static', filename=map_image_filename) + f"?v={datetime.now().timestamp()}"

    if success:
        current_app.logger.debug(f"Map for {country_code} generated, path: {map_image_path}")
        return jsonify(status=f'Map generated for {country_code}', map_image_path=map_image_path), 200
    else:
        current_app.logger.error(f"Map generation failed for {country_code}, serving placeholder path.")
        return jsonify(error=f'Map generation failed for {country_code}', map_image_path=map_image_path), 500

@bp.route('/purge')
def purge_data_route():
    current_app.logger.info("Purge data route accessed.")
    success = prayer_service.purge_all_data()
    if not success:
        current_app.logger.error("Data purge operation failed.")
        return redirect(url_for('main.home'))

    from ..data_initializer import _seed_initial_prayer_queue # Corrected import
    with current_app.app_context():
        _seed_initial_prayer_queue()

    current_app.logger.info("Data purged and queue re-seeded successfully.")
    default_country = list(current_app.config['COUNTRIES_CONFIG'].keys())[0]
    if default_country:
         with current_app.app_context():
            map_service.generate_country_map_image(default_country, [], [])

    return redirect(url_for('main.home'))

@bp.route('/refresh')
def refresh_data_route():
    current_app.logger.info("Refresh endpoint called. Redirecting to home.")
    return redirect(url_for('main.home'))

bp.add_app_template_filter(format_pretty_timestamp)

@bp.app_context_processor
def inject_global_template_variables():
    return dict(
        party_info_all_countries=current_app.config['PARTY_INFO'],
        all_countries_config=current_app.config['COUNTRIES_CONFIG'],
        HEART_IMG_PATH_RELATIVE=current_app.config['HEART_IMG_PATH_RELATIVE']
    )
