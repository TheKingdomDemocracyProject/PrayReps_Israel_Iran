# This file can be empty or can be used to mark the directory as a package.
# It could also contain application factory function if we go that route.
# For now, keeping it simple.
from flask import Flask
import os

# App specific imports (will be services, blueprints etc.)
# from . import routes # Example if routes were in a single file
# from .services import prayer_service # Example

def create_app():
    app = Flask(__name__, instance_relative_config=True)

    # Configuration
    # Paths should be relative to the 'project' directory or absolute
    # APP_ROOT is the directory containing this __init__.py (i.e., 'project')
    # Load configuration from config.py
    # This determines which config (Dev, Prod) to use based on FLASK_ENV
    from .config import get_config
    app.config.from_object(get_config())

    # Ensure instance_path exists (though not heavily used yet)
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Set static and template folders from config
    # These paths are already absolute in config.py
    app.static_folder = app.config['STATIC_FOLDER']
    app.template_folder = app.config['TEMPLATE_FOLDER']

    # Initialize logging
    import logging
    from logging.handlers import RotatingFileHandler

    os.makedirs(app.config['LOG_DIR'], exist_ok=True)
    log_file = os.path.join(app.config['LOG_DIR'], "app.log")

    # Basic logging setup
    # For production, consider more robust logging (e.g., Gunicorn logging, structured logging)
    if not app.debug: # More restrictive logging in production
        file_handler = RotatingFileHandler(log_file, maxBytes=10240, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

        # Also log to stdout for PaaS platforms like Render
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        app.logger.addHandler(stream_handler)

    else: # Debug mode logging
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler() # Log to console as well in debug
        ])

    app.logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    app.logger.info("PrayReps application starting up...")
    app.logger.info(f"Flask Environment: {os.environ.get('FLASK_ENV', 'development')}")
    app.logger.info(f"Database URL: {app.config['DATABASE_URL']}")
    app.logger.info(f"Static folder: {app.static_folder}")
    app.logger.info(f"Template folder: {app.template_folder}")

    # Initialize global data stores (these will be populated by a data service)
    # These are placeholders; their management will be refactored.
    app.hex_map_data_store = {}
    app.post_label_mappings_store = {}
    app.deputies_data = {
        country: {'with_images': [], 'without_images': []}
        for country in app.config['COUNTRIES_CONFIG'].keys()
    }
    # prayed_for_data will be loaded from DB by a service.

    # Initialize database and load initial data
    # This needs to be done within app_context
    with app.app_context():
        from . import database
        database.init_app(app) # For potential CLI commands like init-db

        # The original `initialize_app_data` logic will be refactored
        # into a data_loader or service, and called here.
        # For now, let's placeholder this.
        from . import data_initializer # This will be a new module
        data_initializer.initialize_application(app)
        app.logger.info("Application data initialization complete.")


    # Import and register blueprints
    from .blueprints.main import bp as main_bp
    app.register_blueprint(main_bp)

    from .blueprints.prayer import bp as prayer_bp
    app.register_blueprint(prayer_bp)

    from .blueprints.stats import bp as stats_bp
    app.register_blueprint(stats_bp)

    # from .blueprints.map_routes import map_bp # Example for map specific routes if any
    # app.register_blueprint(map_bp)

    app.logger.info("Blueprints registered.")

    return app
