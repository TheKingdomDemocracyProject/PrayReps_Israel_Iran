import os
import psycopg2
from psycopg2.extras import DictCursor
import logging

# DATABASE_URL will be fetched from environment variables
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    # This logging might occur at import time, which is generally okay for critical configs.
    # However, app-level logging (current_app.logger) isn't available here directly.
    # Using standard Python logging.
    logging.error("CRITICAL: project.db_utils - DATABASE_URL environment variable not set at import time.")
    # Depending on desired behavior, could raise an error or allow None to be handled by consumers.
    # For now, functions using it will need to check.

def get_db_conn():
    """Establishes a connection to the PostgreSQL database."""
    if not DATABASE_URL:
        # Logged at import, but good to check again if function is called when it was None.
        logging.error("project.db_utils.get_db_conn - DATABASE_URL is not set. Cannot connect to the database.")
        raise ValueError("DATABASE_URL not configured")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.Error as e:
        logging.error(f"project.db_utils.get_db_conn - Error connecting to PostgreSQL database: {e}")
        raise
