import hashlib
import http.client
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from signed_webhook_inbox.demo import DEMO_BODY, DEMO_SECRET, send, signed_headers
from signed_webhook_inbox.server import MAX_BODY_BYTES, InboxServer, verifier_for
from signed_webhook_inbox.storage import Inbox


class ReceiverContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "inbox.sqlite3"
        self.inbox = Inbox(self.path)
        self.inbox.initialize()
        self.start_server()

    def start_server(self, timeout=5):
        self.server = InboxServer(self.inbox, DEMO_SECRET, request_timeout=timeout)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.directory.cleanup()

    def headers(self, body=DEMO_BODY, event_id="msg_042", age=0):
        return signed_headers(
            DEMO_SECRET, event_id, body, datetime.now(UTC) + timedelta(seconds=age)
        )

    def rows(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute("SELECT * FROM events ORDER BY event_id").fetchall()

    def raw_request(self, headers: list[str], body=DEMO_BODY):
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as connection:
            request = "POST /webhooks HTTP/1.1\r\nHost: localhost\r\n" + "\r\n".join(headers)
            connection.sendall(request.encode() + b"\r\n\r\n" + body)
            response = http.client.HTTPResponse(connection)
            response.begin()
            response.read()
            return response.status

    def test_valid_event_stores_exact_bytes_hash_and_metadata(self):
        body = b'{ "type": "invoice.paid", "data": {"name":"\xe6\xa4\x9c\xe8\xa8\xbc"}}\n'
        self.assertEqual(send(self.port, body, self.headers(body)), (200, {"result": "stored"}))
        row = self.rows()[0]
        self.assertEqual(
            row[0:4], ("msg_042", body, hashlib.sha256(body).hexdigest(), "invoice.paid")
        )
        self.assertEqual(row[7], 0)
        self.assertEqual(row[8], "standardwebhooks/1.1.0:v1")
        self.assertTrue(row[5].endswith("+00:00"))

    def test_retry_with_fresh_timestamp_keeps_one_event(self):
        self.assertEqual(send(self.port, DEMO_BODY, self.headers())[0], 200)
        self.assertEqual(
            send(self.port, DEMO_BODY, self.headers(age=1)), (200, {"result": "duplicate"})
        )
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.inbox.inspect()["events"][0]["duplicate_count"], 1)

    def test_conflicting_signed_bytes_never_replace_original(self):
        send(self.port, DEMO_BODY, self.headers())
        original = self.rows()
        changed = DEMO_BODY + b" "  # Same JSON semantics, different signed bytes.
        self.assertEqual(
            send(self.port, changed, self.headers(changed)), (409, {"result": "conflict"})
        )
        self.assertEqual(self.rows(), original)

    def test_tampered_body_id_and_timestamp_cannot_write(self):
        headers = self.headers()
        cases = [
            (DEMO_BODY + b" ", headers),
            (DEMO_BODY, {**headers, "webhook-id": "different_id"}),
            (
                DEMO_BODY,
                {**headers, "webhook-timestamp": str(int(headers["webhook-timestamp"]) + 1)},
            ),
        ]
        for body, case_headers in cases:
            with self.subTest(headers=case_headers["webhook-id"]):
                self.assertEqual(send(self.port, body, case_headers)[0], 401)
        self.assertEqual(self.rows(), [])

    def test_stale_and_future_attempts_are_rejected_even_with_valid_signatures(self):
        for age in (-360, 360):
            with self.subTest(age=age):
                self.assertEqual(send(self.port, DEMO_BODY, self.headers(age=age))[0], 401)
        self.assertEqual(self.rows(), [])

    def test_malformed_signature_headers_do_not_crash_or_store(self):
        for value in ("v1", "v1,a,b", "v1,%%%", "v1,", "v1,AAAA", "v1,AA== "):
            with self.subTest(signature=value):
                headers = {**self.headers(), "webhook-signature": value}
                self.assertEqual(send(self.port, DEMO_BODY, headers)[0], 400)
        self.assertEqual(send(self.port, DEMO_BODY, self.headers())[0], 200)
        self.assertEqual(len(self.rows()), 1)

    def test_multiple_signatures_accept_one_valid_signature(self):
        headers = self.headers()
        headers["webhook-signature"] = "v2,AAAA " + headers["webhook-signature"]
        self.assertEqual(send(self.port, DEMO_BODY, headers)[0], 200)

    def test_invalid_ids_and_non_integer_timestamps_are_rejected(self):
        for event_id in ("", "bad.id", "bad id", "x" * 129):
            headers = {**self.headers(), "webhook-id": event_id}
            with self.subTest(event_id=event_id):
                self.assertEqual(send(self.port, DEMO_BODY, headers)[0], 400)
        for timestamp in ("nan", "1e9", "123.5", "000123", "-123"):
            with self.subTest(timestamp=timestamp):
                headers = {**self.headers(), "webhook-timestamp": timestamp}
                self.assertEqual(send(self.port, DEMO_BODY, headers)[0], 400)
        self.assertEqual(self.rows(), [])

    def test_signed_invalid_json_and_payload_contracts_are_rejected(self):
        for body in (
            b"not json",
            b"[]",
            b"{}",
            b'{"type":"invoice paid","data":{}}',
            b'{"type":"invoice.paid","data":[]}',
            b'{"type":"invoice.paid","data":{},"data":{}}',
            b'{"type":"invoice.paid","data":{"amount":NaN}}',
            b'{"type":"invoice.paid","data":' + b"[" * 1100 + b"0" + b"]" * 1100 + b"}",
        ):
            with self.subTest(body=body[:80]):
                self.assertEqual(send(self.port, body, self.headers(body))[0], 400)
        self.assertEqual(self.rows(), [])

    def test_non_utf8_body_is_rejected_without_storage(self):
        self.assertEqual(send(self.port, b"\xff", self.headers())[0], 401)
        self.assertEqual(self.rows(), [])

    def test_missing_or_duplicate_authentication_headers_are_rejected(self):
        headers = self.headers()
        for missing in ("webhook-id", "webhook-timestamp", "webhook-signature"):
            with self.subTest(missing=missing):
                reduced = {key: value for key, value in headers.items() if key != missing}
                self.assertEqual(send(self.port, DEMO_BODY, reduced)[0], 400)
        raw = [f"{key}: {value}" for key, value in headers.items()]
        raw += [f"Content-Length: {len(DEMO_BODY)}", "Webhook-Id: msg_other"]
        self.assertEqual(self.raw_request(raw), 400)
        self.assertEqual(self.rows(), [])

    def test_unsupported_or_ambiguous_framing_is_rejected_before_body_read(self):
        cases = [
            (["Transfer-Encoding: chunked", "Content-Length: 3"], 400),
            (["Content-Length: 3", "Content-Length: 3"], 400),
            (["Content-Length: 1, 1"], 400),
            (["Content-Length: -1"], 400),
            ([], 411),
            (["Content-Length: 0"], 400),
            (["Content-Length: 3", "Expect: 100-continue"], 417),
            (["Content-Length: 3", "Content-Encoding: gzip"], 415),
            ([f"Content-Length: {MAX_BODY_BYTES + 1}"], 413),
        ]
        for headers, expected in cases:
            with self.subTest(headers=headers):
                self.assertEqual(self.raw_request(headers, b""), expected)
        self.assertEqual(self.rows(), [])

    def test_folded_auth_header_is_rejected(self):
        headers = [f"{key}: {value}" for key, value in self.headers().items()]
        headers += [" x-folded", f"Content-Length: {len(DEMO_BODY)}"]
        self.assertEqual(self.raw_request(headers), 400)
        self.assertEqual(self.rows(), [])

    def test_wrong_media_type_route_and_method_do_not_store(self):
        self.assertEqual(
            send(self.port, DEMO_BODY, {**self.headers(), "Content-Type": "text/plain"})[0], 415
        )
        for method, path, expected in (("GET", "/webhooks", 405), ("POST", "/other", 404)):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
            connection.request(method, path, DEMO_BODY, self.headers())
            response = connection.getresponse()
            self.assertEqual(response.status, expected)
            response.read()
            connection.close()
        self.assertEqual(self.rows(), [])

    def test_slow_body_has_total_deadline_and_never_acknowledges(self):
        self.stop_server()
        self.start_server(timeout=0.2)
        headers = [f"{key}: {value}" for key, value in self.headers().items()]
        headers += [f"Content-Length: {len(DEMO_BODY)}"]
        start = time.monotonic()
        self.assertEqual(self.raw_request(headers, b"{"), 408)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(self.rows(), [])

    def test_truncated_body_is_a_failure(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as connection:
            headers = [f"{key}: {value}" for key, value in self.headers().items()]
            headers += [f"Content-Length: {len(DEMO_BODY)}"]
            request = "POST /webhooks HTTP/1.1\r\nHost: localhost\r\n" + "\r\n".join(headers)
            connection.sendall(request.encode() + b"\r\n\r\n{")
            connection.shutdown(socket.SHUT_WR)
            response = http.client.HTTPResponse(connection)
            response.begin()
            self.assertEqual(response.status, 400)
            response.read()
        self.assertEqual(self.rows(), [])

    def test_parallel_duplicate_race_has_one_original_and_nine_retries(self):
        barrier = threading.Barrier(10)
        headers = self.headers()

        def attempt(index):
            barrier.wait(timeout=3)
            return send(self.port, DEMO_BODY, headers)

        with ThreadPoolExecutor(max_workers=10) as workers:
            responses = list(workers.map(attempt, range(10)))
        self.assertTrue(all(status == 200 for status, _ in responses))
        self.assertEqual(sum(result["result"] == "stored" for _, result in responses), 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.inbox.inspect()["events"][0]["duplicate_count"], 9)

    def test_restart_retains_payload_and_duplicate_identity(self):
        send(self.port, DEMO_BODY, self.headers())
        original = self.rows()[0][1:6]
        self.stop_server()
        self.inbox = Inbox(self.path)
        self.inbox.initialize()
        self.start_server()
        self.assertEqual(send(self.port, DEMO_BODY, self.headers())[1]["result"], "duplicate")
        self.assertEqual(self.rows()[0][1:6], original)

    def test_locked_database_returns_retryable_503_then_recovery_stores(self):
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            status, result = send(self.port, DEMO_BODY, self.headers())
            self.assertEqual((status, result), (503, {"result": "storage_unavailable"}))
            self.assertEqual(connection.execute("SELECT count(*) FROM events").fetchone()[0], 0)
        finally:
            connection.rollback()
            connection.close()
        self.assertEqual(send(self.port, DEMO_BODY, self.headers())[1]["result"], "stored")

    def test_database_write_failure_does_not_acknowledge_or_insert(self):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "CREATE TRIGGER deny_write BEFORE INSERT ON events "
                "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        self.assertEqual(send(self.port, DEMO_BODY, self.headers())[0], 503)
        self.assertEqual(self.rows(), [])

    def test_commit_failure_rolls_back_without_success_acknowledgment(self):
        real_connect = sqlite3.connect

        class FailingCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError("injected commit failure")

        def failing_connect(*args, **kwargs):
            return real_connect(*args, **kwargs, factory=FailingCommit)

        with patch("signed_webhook_inbox.storage.sqlite3.connect", failing_connect):
            self.assertEqual(send(self.port, DEMO_BODY, self.headers())[0], 503)
        self.assertEqual(self.rows(), [])
        self.assertEqual(send(self.port, DEMO_BODY, self.headers())[1]["result"], "stored")

    def test_inspection_is_read_only_and_does_not_create_missing_database(self):
        missing = Inbox(self.path.parent / "missing.sqlite3")
        with self.assertRaises(sqlite3.OperationalError):
            missing.inspect()
        self.assertFalse(missing.path.exists())
        send(self.port, DEMO_BODY, self.headers())
        original = self.rows()
        self.assertEqual(self.inbox.inspect()["count"], 1)
        self.assertEqual(self.rows(), original)


class CliContractTests(unittest.TestCase):
    def test_demo_output_is_repeatable_and_successful(self):
        outputs = []
        for _ in range(2):
            result = subprocess.run(
                [sys.executable, "-m", "signed_webhook_inbox", "demo"],
                text=True,
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("conflict: 409 conflict", outputs[0])
        self.assertIn("events: 1", outputs[0])

    def test_loopback_cli_survives_process_restart_with_committed_data(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "persist.sqlite3"
            environment = {**os.environ, "WEBHOOK_SECRET": DEMO_SECRET}
            for expected in ("stored", "duplicate"):
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "signed_webhook_inbox",
                        "serve",
                        "--db",
                        str(db),
                        "--port",
                        "0",
                    ],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                )
                try:
                    ready = process.stdout.readline().strip()
                    self.assertTrue(ready.startswith("listening: http://127.0.0.1:"), ready)
                    port = int(ready.split(":")[-1].split("/")[0])
                    headers = signed_headers(
                        DEMO_SECRET, "msg_restart", DEMO_BODY, datetime.now(UTC)
                    )
                    self.assertEqual(send(port, DEMO_BODY, headers)[1]["result"], expected)
                finally:
                    process.terminate()
                    process.communicate(timeout=5)
            result = subprocess.run(
                [sys.executable, "-m", "signed_webhook_inbox", "inspect", "--db", str(db)],
                text=True,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(result.stdout)
            self.assertEqual(snapshot["count"], 1)
            self.assertEqual(snapshot["events"][0]["duplicate_count"], 1)

    def test_invalid_secret_is_not_logged_or_used_to_create_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "never.sqlite3"
            secret = "private-invalid-value"
            result = subprocess.run(
                [sys.executable, "-m", "signed_webhook_inbox", "serve", "--db", str(path)],
                env={**os.environ, "WEBHOOK_SECRET": secret},
                text=True,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertFalse(path.exists())
        for value in ("whsec_%%%%", "whsec_YQ==", "", "whsec_"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                verifier_for(value)


if __name__ == "__main__":
    unittest.main()
