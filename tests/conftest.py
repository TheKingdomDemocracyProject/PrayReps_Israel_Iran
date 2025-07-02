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
    print("CONFTTEST_FIXTURE_APP: Attempting 'from project import create_app' INSIDE fixture.")
    from project import create_app # Moved import here
    print("CONFTTEST_FIXTURE_APP: Successfully imported 'create_app' from 'project'.")
    """Create and configure a new app instance for each test."""
    # Setup for tests, e.g., using a test config
    # For now, using default config which should point to a test DB if FLASK_ENV=testing
    # or if DATABASE_URL is overridden for tests.
    # This basic setup doesn't explicitly set a test database,
    # which might be an issue if tests interact with the DB.
    # For now, focusing on app creation and basic route testing.
    app_instance = create_app()

    # TODO: Configure a separate test database
    # app.config.update({
    #     "TESTING": True,
    #     "DATABASE_URL": "your_test_database_url_here",
    # })

    yield app_instance

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test runner for the app's Click commands."""
    return app.test_cli_runner()
