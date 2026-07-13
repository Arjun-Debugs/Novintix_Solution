import os
import sqlite3

# BASE_DIR and DEFAULT_DB_PATH relative to workspace
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "decisions.db")

class LibsqlCursor:
    def __init__(self, client):
        self.client = client
        self.results = None
        self.index = 0

    def execute(self, sql, params=None):
        if params is None:
            self.results = self.client.execute(sql)
        else:
            # libsql-client expects a list of parameters
            self.results = self.client.execute(sql, list(params))
        self.index = 0
        return self

    def fetchone(self):
        if self.results is None or self.index >= len(self.results.rows):
            return None
        row = self.results.rows[self.index]
        self.index += 1
        return tuple(row)

    def fetchall(self):
        if self.results is None:
            return []
        rows = [tuple(r) for r in self.results.rows[self.index:]]
        self.index = len(self.results.rows)
        return rows

class LibsqlConnection:
    def __init__(self, url, token):
        import libsql_client
        self.client = libsql_client.create_client_sync(url, auth_token=token)

    def cursor(self):
        return LibsqlCursor(self.client)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.client.close()

def get_connection(db_path: str = None):
    """
    Returns a Turso (libSQL) connection if LIBSQL_URL and LIBSQL_AUTH_TOKEN env
    vars are both set. Otherwise falls back to the local SQLite file at db_path or DEFAULT_DB_PATH.
    This is the ONLY place a DB connection is opened anywhere in the app.
    """
    libsql_url = os.environ.get("LIBSQL_URL")
    libsql_token = os.environ.get("LIBSQL_AUTH_TOKEN")

    if libsql_url and libsql_token:
        return LibsqlConnection(libsql_url, libsql_token)

    target_path = db_path if db_path is not None else DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    return sqlite3.connect(target_path)
