"""SQLite is the acknowledgment boundary; each connection belongs to one request."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


class Inbox:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def initialize(self) -> None:
        with closing(sqlite3.connect(self.path, timeout=1)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise sqlite3.DatabaseError("unsupported inbox version")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    raw_body BLOB NOT NULL,
                    sha256 TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    signed_at INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    last_received_at TEXT NOT NULL,
                    duplicate_count INTEGER NOT NULL DEFAULT 0,
                    verifier TEXT NOT NULL
                ) STRICT
            """)
            connection.execute("PRAGMA user_version=1")

    def receive(self, event_id: str, body: bytes, event_type: str, signed_at: int) -> str:
        # minimalism: retain IDs indefinitely; no retention job or processing queue.
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=1)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT raw_body FROM events WHERE event_id=?", (event_id,)
            ).fetchone()
            received_at = datetime.now(UTC).isoformat(timespec="seconds")
            if existing:
                if existing[0] != body:
                    return "conflict"
                connection.execute(
                    "UPDATE events SET duplicate_count=duplicate_count+1, last_received_at=? "
                    "WHERE event_id=?",
                    (received_at, event_id),
                )
                result = "duplicate"
            else:
                connection.execute(
                    "INSERT INTO events (event_id, raw_body, sha256, event_type, signed_at, "
                    "received_at, last_received_at, verifier) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        body,
                        hashlib.sha256(body).hexdigest(),
                        event_type,
                        signed_at,
                        received_at,
                        received_at,
                        "standardwebhooks/1.1.0:v1",
                    ),
                )
                result = "stored"
            connection.commit()
            return result
        finally:
            # Closing rolls back conflicts and failed writes; none get a success acknowledgment.
            connection.close()

    def inspect(self) -> dict:
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT event_id, event_type, length(raw_body) AS bytes, sha256, signed_at, "
                "received_at, last_received_at, duplicate_count, verifier FROM events "
                "ORDER BY event_id"
            ).fetchall()
            return {"count": len(rows), "events": [dict(row) for row in rows]}
        finally:
            connection.close()
