import os

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', os.urandom(24))

    # Determine APP_ROOT (project directory) and PROJECT_ROOT (one level up)
    # This assumes config.py is inside the 'project' directory.
    APP_ROOT = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(APP_ROOT)

    # DATABASE_URL for PostgreSQL on Render, with a fallback to local SQLite path for development if not set
    # The primary source of DATABASE_URL for database functions is os.environ.get('DATABASE_URL') in app.py
    # This ensures app.config['DATABASE_URL'] is also correctly set.
    DATABASE_URL = os.environ.get('DATABASE_URL') or \
                   'sqlite:///' + os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'local_dev_queue.sqlite') # Fallback for local dev with sqlite:///

    # LOG_DIR should also be environment-aware or use a simpler default for non-Render environments
    # For Render, stdout/stderr is preferred. For local, a local path.
    # The logging in create_app already uses app.config['LOG_DIR']
    # If app.py's LOG_DIR_APP is the main one for file logging, ensure consistency or remove one.
    # For file logging, use a consistent local path. Render will capture stdout/stderr.
    LOG_DIR = os.path.join(PROJECT_ROOT, 'logs_project_cfg') # For logs configured by create_app

    DATA_DIR = os.path.join(PROJECT_ROOT, 'data') # For CSVs, GeoJSONs

    # Static and Template folders are relative to PROJECT_ROOT
    STATIC_FOLDER = os.path.join(PROJECT_ROOT, 'static')
    TEMPLATE_FOLDER = os.path.join(PROJECT_ROOT, 'templates')

    # Application specific configurations
    COUNTRIES_CONFIG = {
        'israel': {
            'csv_path': os.path.join(DATA_DIR, '20221101_israel.csv'),
            'geojson_path': os.path.join(DATA_DIR, 'ISR_Parliament_120.geojson'),
            'map_shape_path': os.path.join(DATA_DIR, 'ISR_Parliament_120.geojson'),
            'post_label_mapping_path': None, # Not used for random allocation
            'total_representatives': 120,
            'name': 'Israel',
            'flag': '🇮🇱'
        },
        'iran': {
            'csv_path': os.path.join(DATA_DIR, '20240510_iran.csv'),
            'geojson_path': os.path.join(DATA_DIR, 'IRN_IslamicParliamentofIran_290_v2.geojson'),
            'map_shape_path': os.path.join(DATA_DIR, 'IRN_IslamicParliamentofIran_290_v2.geojson'),
            'post_label_mapping_path': None, # Not used for random allocation
            'total_representatives': 290,
            'name': 'Iran',
            'flag': '🇮🇷'
        }
    }

    PARTY_INFO = {
        'israel': {
            'Likud': {'short_name': 'Likud', 'color': '#00387A'},
            'Yesh Atid': {'short_name': 'Yesh Atid', 'color': '#ADD8E6'},
            'Shas': {'short_name': 'Shas', 'color': '#FFFF00'},
            'Resilience': {'short_name': 'Resilience', 'color': '#0000FF'},
            'Labor': {'short_name': 'Labor', 'color': '#FF0000'},
            'Other': {'short_name': 'Other', 'color': '#CCCCCC'}
        },
        'iran': {
            'Principlist': {'short_name': 'Principlist', 'color': '#006400'},
            'Reformists': {'short_name': 'Reformists', 'color': '#90EE90'},
            'Independent': {'short_name': 'Independent', 'color': '#808080'},
            'Other': {'short_name': 'Other', 'color': '#CCCCCC'}
        },
    }

    # Path for the heart image used in map plotting (relative to static folder)
    # The full path will be constructed as os.path.join(STATIC_FOLDER, HEART_IMG_PATH_RELATIVE)
    # However, for templates, it's often easier to use url_for, so this might be just for backend use.
    HEART_IMG_PATH_RELATIVE = 'heart_icons/heart_red.png'


class DevelopmentConfig(Config):
    DEBUG = True
    # Add any development specific configs

class ProductionConfig(Config):
    DEBUG = False
    # Add any production specific configs, e.g. logging level

class TestingConfig(Config):
    TESTING = True
    # Use a file-based SQLite DB for tests to ensure persistence across contexts
    DATABASE_URL = os.path.join(Config.PROJECT_ROOT, 'test_prayreps.db') # Raw file path
    DEBUG = True # Often useful for tests to get more detailed error output
    # Add any other test-specific overrides, e.g., disable CSRF, etc.

# Helper to get config class based on environment variable
def get_config():
    env = os.environ.get('FLASK_ENV', 'development')
    if env == 'production':
        return ProductionConfig
    if env == 'testing':
        return TestingConfig
    return DevelopmentConfig

# Global config object that can be imported by the app
# This approach is simple but makes config an import-time fixed object.
# Using app.config.from_object(get_config()) in create_app is more flexible.
# For now, let's keep this and see how it fits.
# CurrentConfig = get_config()
