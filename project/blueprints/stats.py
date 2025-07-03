from flask import Blueprint, render_template, current_app, jsonify, redirect, url_for
import os
import sys
import json

# --- Import Helper ---
# try:
from ..services import prayer_service
# from ..utils import format_pretty_timestamp # Not directly used in this BP's routes, but good to have if templates needed it
# except (ImportError, ValueError):
#     PROJECT_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#     if PROJECT_ROOT_PATH not in sys.path:
#         sys.path.append(PROJECT_ROOT_PATH)
#     from project.services import prayer_service
    # try:
    #     from utils import format_pretty_timestamp
    # except ImportError:
    #     def format_pretty_timestamp(ts_str): return ts_str
    #     if current_app:
    #         current_app.logger.error("Critical: format_pretty_timestamp could not be imported for stats blueprint.")
# --- End Import Helper ---

bp = Blueprint('stats', __name__, url_prefix='/stats')

@bp.route('/<country_code>')
def statistics_page(country_code):
    current_app.logger.info(f"Statistics page requested for: {country_code}")

    if country_code != 'overall' and country_code not in current_app.config['COUNTRIES_CONFIG']:
        current_app.logger.warning(f"Invalid country code '{country_code}' for statistics. Redirecting to default.")
        default_redirect_code = list(current_app.config['COUNTRIES_CONFIG'].keys())[0] if current_app.config['COUNTRIES_CONFIG'] else 'overall'
        return redirect(url_for('stats.statistics_page', country_code=default_redirect_code))

    current_country_name = "Overall"
    current_party_info_map_for_js = {} # Default to empty for 'overall'

    if country_code != 'overall':
        current_country_name = current_app.config['COUNTRIES_CONFIG'][country_code]['name']
        current_party_info_map_for_js = current_app.config['PARTY_INFO'].get(country_code, {})

    # The main statistics.html page will setup containers for charts.
    # Actual data is fetched by client-side JS using the JSON endpoints below.
    # We pass initial config data that JS might need, like party colors.
    return render_template('statistics.html',
                           country_code=country_code,
                           country_name=current_country_name,
                           # Pass party color mapping for the selected country to JS via data attribute or JS var
                           current_country_party_info_json=json.dumps(current_party_info_map_for_js)
                           )

@bp.route('/')
def statistics_default_redirect():
    default_code = list(current_app.config['COUNTRIES_CONFIG'].keys())[0] if current_app.config['COUNTRIES_CONFIG'] else 'overall'
    return redirect(url_for('stats.statistics_page', country_code=default_code))

@bp.route('/data/<country_code>')
def statistics_data_json(country_code):
    current_app.logger.debug(f"Statistics data JSON requested for: {country_code}")

    if country_code == 'overall':
        total_prayed_count = prayer_service.get_overall_prayed_count()
        data_to_return = {'Overall': total_prayed_count}
        current_app.logger.debug(f"Overall statistics data: {data_to_return}")
        return jsonify(data_to_return)

    if country_code not in current_app.config['COUNTRIES_CONFIG']:
        current_app.logger.error(f"Invalid country code '{country_code}' for statistics data JSON.")
        return jsonify({"error": "Country not found"}), 404

    sorted_party_counts_list, _ = prayer_service.get_party_statistics(country_code)
    party_counts_dict = dict(sorted_party_counts_list) # Convert list of tuples to dict

    current_app.logger.debug(f"Party statistics data for {country_code}: {party_counts_dict}")
    return jsonify(party_counts_dict)

@bp.route('/timedata/<country_code>')
def statistics_timedata_json(country_code):
    current_app.logger.debug(f"Statistics timedata JSON requested for: {country_code}")

    if country_code != 'overall' and country_code not in current_app.config['COUNTRIES_CONFIG']:
        current_app.logger.error(f"Invalid country code '{country_code}' for statistics timedata JSON.")
        return jsonify({"error": "Country not found"}), 404

    timedata = prayer_service.get_timedata_statistics(country_code) # Handles 'overall' case

    current_country_name_for_response = "Overall"
    if country_code != 'overall':
        current_country_name_for_response = current_app.config['COUNTRIES_CONFIG'][country_code]['name']

    response_data = {
        'timestamps': timedata['timestamps'],
        'values': timedata['values'],
        'country_name': current_country_name_for_response
    }
    current_app.logger.debug(f"Timedata for {country_code} prepared: {len(response_data['timestamps'])} entries.")
    return jsonify(response_data)
