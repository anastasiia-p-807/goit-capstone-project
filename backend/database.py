from contextlib import contextmanager
from pathlib import Path
import sqlite3


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    mood INTEGER CHECK (mood BETWEEN 1 AND 5),
                    topic TEXT,
                    analysis TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS entry_date_idx ON entries(entry_date)")
            # Additive migration: legacy journal text stays intact and unassigned.
            columns = {row[1] for row in connection.execute("PRAGMA table_info(entries)")}
            if "user_id" not in columns:
                connection.execute("ALTER TABLE entries ADD COLUMN user_id TEXT")
            connection.execute("CREATE INDEX IF NOT EXISTS entry_owner_idx ON entries(user_id, entry_date)")
            connection.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, created_at TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL)""")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

