import os

# Application Root and Data Directory
# Assuming app.py (and thus this config when used by app.py) is in the 'src' root.
# If project structure changes, these might need adjustment or be passed in.
APP_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)  # This will point to the directory containing 'project'
APP_DATA_DIR = os.path.join(APP_ROOT, "data")

# Configuration for countries
COUNTRIES_CONFIG = {
    "israel": {
        "csv_path": os.path.join(APP_DATA_DIR, "20221101_israel.csv"),
        "geojson_path": os.path.join(APP_DATA_DIR, "ISR_Parliament_120.geojson"),
        "map_shape_path": os.path.join(APP_DATA_DIR, "ISR_Parliament_120.geojson"),
        "post_label_mapping_path": None,
        "total_representatives": 120,
        "name": "Israel",
        "flag": "🇮🇱",
    },
    "iran": {
        "csv_path": os.path.join(APP_DATA_DIR, "20240510_iran.csv"),
        "geojson_path": os.path.join(
            APP_DATA_DIR, "IRN_IslamicParliamentofIran_290_v2.geojson"
        ),
        "map_shape_path": os.path.join(
            APP_DATA_DIR, "IRN_IslamicParliamentofIran_290_v2.geojson"
        ),
        "post_label_mapping_path": None,
        "total_representatives": 290,
        "name": "Iran",
        "flag": "🇮🇷",
    },
}

# Heart image path (relative to static folder)
HEART_IMG_PATH = (
    "static/heart_icons/heart_red.png"  # Path for map plotting logic in app.py
)
# Note: project/config.py sets app.config['HEART_IMG_PATH_RELATIVE'] = 'heart_icons/heart_red.png'
# This HEART_IMG_PATH is used by app.py's update_queue if thumbnail is missing.
# Need to ensure consistency or pick one source of truth.
# For now, replicating the one used by app.py's update_queue.

# Party information
party_info = {
    "israel": {
        "Likud": {"short_name": "Likud", "color": "#00387A"},
        "Yesh Atid": {"short_name": "Yesh Atid", "color": "#ADD8E6"},
        "Shas": {"short_name": "Shas", "color": "#FFFF00"},
        "Resilience": {"short_name": "Resilience", "color": "#0000FF"},
        "Labor": {"short_name": "Labor", "color": "#FF0000"},
        "Other": {"short_name": "Other", "color": "#CCCCCC"},
    },
    "iran": {
        "Principlist": {"short_name": "Principlist", "color": "#006400"},
        "Reformists": {"short_name": "Reformists", "color": "#90EE90"},
        "Independent": {"short_name": "Independent", "color": "#808080"},
        "Other": {"short_name": "Other", "color": "#CCCCCC"},
    },
}

# Logging configuration (could also be moved here or kept in app.py / project/__init__.py)
# For now, keeping logging setup in app.py and project/__init__.py as it's tied to app context.
# LOG_DIR_APP = os.path.join(APP_ROOT, 'logs_app')
# LOG_FILE_PATH_APP = os.path.join(LOG_DIR_APP, "app.log")
# os.makedirs(LOG_DIR_APP, exist_ok=True) # Would require os import
