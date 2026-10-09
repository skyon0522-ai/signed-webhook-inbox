import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from signed_webhook_inbox.demo import DEMO_BODY
from signed_webhook_inbox.storage import Inbox


class ConnectionOwnershipTests(unittest.TestCase):
    def test_each_owned_connection_closes_on_success_conflict_and_failure(self):
        connections = []
        real_connect = sqlite3.connect

        class ObservedConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if sql.startswith("INSERT INTO events") and parameters[0] == "fail":
                    raise sqlite3.OperationalError("injected write failure")
                return super().execute(sql, parameters)

        def observed_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs, factory=ObservedConnection)
            connections.append(connection)
            return connection

        with tempfile.TemporaryDirectory() as directory:
            inbox = Inbox(Path(directory) / "inbox.sqlite3")
            with patch("signed_webhook_inbox.storage.sqlite3.connect", observed_connect):
                inbox.initialize()
                self.assertEqual(inbox.receive("one", DEMO_BODY, "invoice.paid", 1), "stored")
                self.assertEqual(inbox.receive("one", DEMO_BODY, "invoice.paid", 2), "duplicate")
                self.assertEqual(
                    inbox.receive("one", DEMO_BODY + b" ", "invoice.paid", 3), "conflict"
                )
                with self.assertRaises(sqlite3.OperationalError):
                    inbox.receive("fail", DEMO_BODY, "invoice.paid", 4)
                self.assertEqual(inbox.inspect()["events"][0]["duplicate_count"], 1)
            self.assertEqual(len(connections), 6)
            for connection in connections:
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
