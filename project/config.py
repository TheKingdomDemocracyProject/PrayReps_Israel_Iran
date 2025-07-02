import os
# Import static configurations from project.app_config
from .app_config import (
    APP_ROOT as PROJECT_APP_ROOT, # Renaming to avoid clash if Config defines its own APP_ROOT
    APP_DATA_DIR as PROJECT_APP_DATA_DIR, # Renaming
    COUNTRIES_CONFIG as APP_DEFINED_COUNTRIES_CONFIG,
    party_info as APP_DEFINED_PARTY_INFO, # Corrected case for party_info
    HEART_IMG_PATH as APP_DEFINED_HEART_IMG_PATH
)

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', os.urandom(24))

    # PROJECT_ROOT is the directory containing the 'project' package (e.g., src/)
    # This is consistent with PROJECT_APP_ROOT from app_config.py
    PROJECT_ROOT = PROJECT_APP_ROOT

    # DATABASE_URL for PostgreSQL on Render, with a fallback to local SQLite path for development if not set
    # The primary source of DATABASE_URL for database functions is now project.db_utils.DATABASE_URL
    # This app.config['DATABASE_URL'] is for Flask's knowledge, and for tests.
    # For testing, this will be overridden by TestingConfig.
    # For dev, if DATABASE_URL env var is not set, it defaults to a local SQLite file.
    # Note: The path construction for default SQLite DB needs to use PROJECT_ROOT.
    _default_sqlite_path = 'sqlite:///' + os.path.join(PROJECT_ROOT, 'data', 'local_dev_queue.sqlite')
    DATABASE_URL = os.environ.get('DATABASE_URL') or _default_sqlite_path

    # LOG_DIR uses PROJECT_ROOT.
    LOG_DIR = os.path.join(PROJECT_ROOT, 'logs_project_cfg')

    # DATA_DIR from app_config is PROJECT_APP_DATA_DIR
    DATA_DIR = PROJECT_APP_DATA_DIR

    # Static and Template folders are relative to PROJECT_ROOT
    STATIC_FOLDER = os.path.join(PROJECT_ROOT, 'static')
    TEMPLATE_FOLDER = os.path.join(PROJECT_ROOT, 'templates')

    # Application specific configurations imported from project.app_config
    COUNTRIES_CONFIG = APP_DEFINED_COUNTRIES_CONFIG
    PARTY_INFO = APP_DEFINED_PARTY_INFO

    # HEART_IMG_PATH_RELATIVE is used for templates with url_for.
    # APP_DEFINED_HEART_IMG_PATH is 'static/heart_icons/heart_red.png'
    # We need the part relative to static folder for url_for.
    if APP_DEFINED_HEART_IMG_PATH.startswith('static/'):
        HEART_IMG_PATH_RELATIVE = APP_DEFINED_HEART_IMG_PATH[len('static/'):]
    else:
        HEART_IMG_PATH_RELATIVE = APP_DEFINED_HEART_IMG_PATH


class DevelopmentConfig(Config):
    DEBUG = True
    # Add any development specific configs

class ProductionConfig(Config):
    DEBUG = False
    # Add any production specific configs, e.g. logging level

class TestingConfig(Config):
    TESTING = True
    # For mocked DB tests, the actual value is less critical, but make it clear.
    # If some code still tries to parse it, a valid URI format might be useful.
    DATABASE_URL = 'postgresql://mocked_user:mocked_pass@mocked_host:5432/mocked_db'
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
