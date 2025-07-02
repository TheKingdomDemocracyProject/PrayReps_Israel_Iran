# tests/conftest.py
print("CONFTTEST_TOP: Conftest.py is being loaded.")
import sys
import os
import pytest # Moved pytest import higher
import sqlite3 # Import sqlite3 for manual DDL execution

# Add the project root directory to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
print(f"CONFTTEST_SYSPATH: Modifying sys.path. PROJECT_ROOT='{PROJECT_ROOT}'")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
    print(f"CONFTTEST_SYSPATH: Added PROJECT_ROOT. sys.path[0]='{sys.path[0]}'")
else:
    print(f"CONFTTEST_SYSPATH: PROJECT_ROOT already in sys.path.")
print(f"CONFTTEST_SYSPATH: Full sys.path now: {sys.path}")


@pytest.fixture
def app():
    print("CONFTTEST_FIXTURE_APP: app() fixture called.")

    # Set FLASK_ENV to 'testing' before creating the app
    # This ensures create_app() picks up TestingConfig
    os.environ['FLASK_ENV'] = 'testing'
    print("CONFTTEST_FIXTURE_APP: FLASK_ENV set to 'testing'.")

    print("CONFTTEST_FIXTURE_APP: Attempting 'from project import create_app' INSIDE fixture.")
    from project import create_app
    from project.config import get_config, TestingConfig # For verification
    print("CONFTTEST_FIXTURE_APP: Successfully imported 'create_app' and config utils from 'project'.")

    # Verify get_config() behavior
    cfg_obj = get_config()
    print(f"CONFTTEST_FIXTURE_APP: get_config() returned type: {type(cfg_obj)}")
    assert cfg_obj == TestingConfig, f"get_config() returned {cfg_obj}, expected TestingConfig class"

    app_instance = create_app() # This will now use TestingConfig
    print("CONFTTEST_FIXTURE_APP: DB connection type: <class 'sqlite3.Connection'>") # This will be printed by the assertion below now
    # Assert that the DATABASE_URL is the file path defined in TestingConfig
    expected_db_path_suffix = 'test_prayreps.db'
    actual_db_url = app_instance.config['DATABASE_URL']
    print(f"CONFTTEST_FIXTURE_APP: Actual DATABASE_URL from app.config: {actual_db_url}")
    assert expected_db_path_suffix in actual_db_url, \
        f"App is not configured for file-based SQLite DB. Expected '{expected_db_path_suffix}' in '{actual_db_url}'"

    # Ensure a clean state by deleting the test DB file if it exists
    # The path needs to be extracted from the URI 'sqlite:///path/to/file'
    db_file_path = actual_db_url.replace('sqlite:///', '')
    if os.path.exists(db_file_path):
        print(f"CONFTTEST_FIXTURE_APP: Removing existing test database: {db_file_path}")
        os.remove(db_file_path)

    # Setup database schema for file-based SQLite
    with app_instance.app_context():
        from project.database import get_db, close_db
        db = get_db() # This will now connect to the file-based DB
        print(f"CONFTTEST_FIXTURE_APP: DB connection type for file DB: {type(db)}")

        # SQLite-compatible DDL
        ddl_prayer_candidates = """
        CREATE TABLE prayer_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_name TEXT NOT NULL,
            post_label TEXT,
            country_code TEXT NOT NULL,
            party TEXT,
            thumbnail TEXT,
            status TEXT NOT NULL,
            status_timestamp TEXT NOT NULL,
            initial_add_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            hex_id TEXT
        );
        """
        ddl_unique_index = """
        CREATE UNIQUE INDEX idx_candidates_unique
        ON prayer_candidates (person_name, post_label, country_code);
        """
        try:
            print("CONFTTEST_FIXTURE_APP: Executing DDL for prayer_candidates table.")
            db.executescript(ddl_prayer_candidates)
            print("CONFTTEST_FIXTURE_APP: prayer_candidates table created.")
            print("CONFTTEST_FIXTURE_APP: Executing DDL for idx_candidates_unique index.")
            db.executescript(ddl_unique_index)
            print("CONFTTEST_FIXTURE_APP: idx_candidates_unique index created.")
            db.commit()
            print("CONFTTEST_FIXTURE_APP: DB schema committed.")
        except Exception as e:
            print(f"CONFTTEST_FIXTURE_APP: Error creating schema: {e}")
            raise

    yield app_instance

    with app_instance.app_context():
        close_db()
        print("CONFTTEST_FIXTURE_APP: DB connection closed after test.")

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test runner for the app's Click commands."""
    return app.test_cli_runner()
