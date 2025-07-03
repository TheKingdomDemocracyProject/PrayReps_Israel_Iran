# tests/conftest.py
import sys
import os
import pytest  # Moved pytest import higher

print("CONFTTEST_TOP: Conftest.py is being loaded.")

# Add the project root directory to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
print(f"CONFTTEST_SYSPATH: Modifying sys.path. PROJECT_ROOT='{PROJECT_ROOT}'")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
    print(f"CONFTTEST_SYSPATH: Added PROJECT_ROOT. sys.path[0]='{sys.path[0]}'")
else:
    print(f"CONFTTEST_SYSPATH: PROJECT_ROOT already in sys.path.")
print("CONFTTEST_SYSPATH: Full sys.path now: " + str(sys.path))


@pytest.fixture
def app(monkeypatch):  # Add monkeypatch as an argument
    print("CONFTTEST_FIXTURE_APP: app() fixture called.")

    os.environ["FLASK_ENV"] = "testing"
    print("CONFTTEST_FIXTURE_APP: FLASK_ENV set to 'testing'.")

    from project.config import TestingConfig

    # This is app.config['DATABASE_URL'] which is 'postgresql://mocked...'
    # project.db_utils.DATABASE_URL will also pick this up from env var if we set it.
    test_db_url_for_env = TestingConfig.DATABASE_URL

    original_db_url_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_db_url_for_env
    print(
        f"CONFTTEST_FIXTURE_APP: Set os.environ['DATABASE_URL'] to: {test_db_url_for_env}"
    )

    # Apply monkeypatches BEFORE create_app() is called
    from tests.mocks import db_mocks

    monkeypatch.setattr("project.db_utils.get_db_conn", db_mocks.get_mock_db_conn)
    print("CONFTTEST_FIXTURE_APP: Patched 'project.db_utils.get_db_conn' with mock.")

    monkeypatch.setattr(
        "app.init_db", db_mocks.mock_init_db
    )  # Patches init_db in app.py module
    print(
        "CONFTTEST_FIXTURE_APP: Patched 'app.init_db' (from root app.py module) with mock."
    )

    # Also mock other app.py functions that data_initializer calls and that interact with DB
    # to prevent them from running with a mock connection that might not return expected data for their logic.
    # For app creation, it's often enough that they don't raise errors.
    def mock_load_prayed_from_db():
        print("Mocked app.load_prayed_for_data_from_db called.")
        # current_app.prayed_for_data should already be initialized as {} by create_app
        pass  # Does not attempt to load from DB

    monkeypatch.setattr("app.load_prayed_for_data_from_db", mock_load_prayed_from_db)
    print(
        "CONFTTEST_FIXTURE_APP: Patched 'app.load_prayed_for_data_from_db' with mock."
    )

    def mock_update_queue():
        print("Mocked app.update_queue called.")
        # This function is complex; for app creation test, just ensure it doesn't error.
        # It uses current_app.hex_map_data_store, which should be {}
        pass

    monkeypatch.setattr("app.update_queue", mock_update_queue)
    print("CONFTTEST_FIXTURE_APP: Patched 'app.update_queue' with mock.")

    print(
        "CONFTTEST_FIXTURE_APP: Attempting 'from project import create_app' (after patching)."
    )
    from project import create_app

    app_instance = create_app()

    # Restore original DATABASE_URL in environment
    if original_db_url_env is None:
        if "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]
    else:
        os.environ["DATABASE_URL"] = original_db_url_env
    print("CONFTTEST_FIXTURE_APP: Restored os.environ['DATABASE_URL'] (if any).")

    print(
        f"CONFTTEST_FIXTURE_APP: app.config['DATABASE_URL'] is: {app_instance.config['DATABASE_URL']}"
    )
    expected_mock_db_url_part = "mocked_db"
    actual_app_config_db_url = app_instance.config["DATABASE_URL"]
    print(
        f"CONFTTEST_FIXTURE_APP: Actual DATABASE_URL from app.config: {actual_app_config_db_url}"
    )
    assert (
        expected_mock_db_url_part in actual_app_config_db_url
    ), (
        f"App.config['DATABASE_URL'] not using mocked URL. "
        f"Expected '{expected_mock_db_url_part}' in path '{actual_app_config_db_url}'"
    )

    yield app_instance

    print("CONFTTEST_FIXTURE_APP: Mocked app fixture teardown.")


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """A test runner for the app's Click commands."""
    return app.test_cli_runner()
