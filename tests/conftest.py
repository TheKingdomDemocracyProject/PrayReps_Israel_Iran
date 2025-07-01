import pytest
from project import create_app

@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    # Setup for tests, e.g., using a test config
    # For now, using default config which should point to a test DB if FLASK_ENV=testing
    # or if DATABASE_URL is overridden for tests.
    # This basic setup doesn't explicitly set a test database,
    # which might be an issue if tests interact with the DB.
    # For now, focusing on app creation and basic route testing.
    app = create_app()

    # TODO: Configure a separate test database
    # app.config.update({
    #     "TESTING": True,
    #     "DATABASE_URL": "your_test_database_url_here",
    # })

    yield app

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test runner for the app's Click commands."""
    return app.test_cli_runner()
