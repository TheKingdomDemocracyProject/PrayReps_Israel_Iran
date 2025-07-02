import logging

class MockCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self.rowcount = -1
        self._results = []
        self._query = None
        self._params = None
        # Allow tests to set expected return values for fetchone/fetchall
        self.fetchone_return_value = None
        self.fetchall_return_value = []
        self.expected_rowcount = 0 # For update/delete operations

    def execute(self, query, params=None):
        self._query = query
        self._params = params
        logging.debug(f"MockCursor executed: {query} with params: {params}")
        # Simulate rowcount for DML, or set up for DQL
        if query.strip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            self.rowcount = self.expected_rowcount
        else: # SELECT
            self.rowcount = len(self.fetchall_return_value) if self.fetchall_return_value else \
                            (1 if self.fetchone_return_value else 0)


    def fetchone(self):
        logging.debug(f"MockCursor fetchone called. Returning: {self.fetchone_return_value}")
        return self.fetchone_return_value

    def fetchall(self):
        logging.debug(f"MockCursor fetchall called. Returning: {self.fetchall_return_value}")
        return self.fetchall_return_value

    def close(self):
        logging.debug("MockCursor closed.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class MockConnection:
    def __init__(self, dsn=None):
        self.dsn = dsn
        self.closed = False
        self._cursor = MockCursor(self) # Each connection gets one main cursor for simplicity in mock
        self.autocommit = False # Mimic psycopg2 connection attribute

    def cursor(self, cursor_factory=None):
        logging.debug(f"MockConnection cursor called (factory: {cursor_factory}). Returning shared mock cursor.")
        # Return the shared cursor or a new one if advanced mocking needed per cursor
        return self._cursor

    def commit(self):
        logging.debug("MockConnection commit called.")

    def rollback(self):
        logging.debug("MockConnection rollback called.")

    def close(self):
        self.closed = True
        logging.debug("MockConnection closed.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

def get_mock_db_conn(*args, **kwargs):
    """Factory function to be used by monkeypatch for project.db_utils.get_db_conn."""
    logging.debug(f"get_mock_db_conn called with args: {args}, kwargs: {kwargs}. Returning MockConnection.")
    # The DSN from DATABASE_URL will be passed as the first arg if present in the original call
    dsn = args[0] if args else kwargs.get('dsn')
    return MockConnection(dsn=dsn)

def mock_init_db(*args, **kwargs):
    """To be used by monkeypatch for app.init_db during tests."""
    logging.info("Mocked app.init_db called. Skipping actual DB initialization.")
    pass

# Example of how a test might configure the cursor:
# mock_cursor_instance = my_mock_connection.cursor()
# mock_cursor_instance.fetchall_return_value = [{'id': 1, 'name': 'Test1'}, {'id': 2, 'name': 'Test2'}]
# mock_cursor_instance.fetchone_return_value = {'id': 1, 'name': 'Test1'}
# mock_cursor_instance.expected_rowcount = 1 # For an update
