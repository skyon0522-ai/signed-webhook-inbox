"""A deterministic local scenario; timestamps refresh but printed outcomes stay stable."""

import base64
import http.client
import json
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ._vendor.standardwebhooks import Webhook
from .server import InboxServer
from .storage import Inbox

# Public test fixture only. Never configure a non-demo receiver with this key.
DEMO_SECRET = "whsec_" + base64.b64encode(b"local-demo-key-do-not-use-outside!").decode()
DEMO_BODY = b'{"type":"invoice.paid","data":{"invoice_id":"inv_042","amount":12500}}'


def signed_headers(secret: str, event_id: str, body: bytes, timestamp: datetime) -> dict:
    return {
        "Content-Type": "application/json",
        "webhook-id": event_id,
        "webhook-timestamp": str(int(timestamp.timestamp())),
        "webhook-signature": Webhook(secret).sign(event_id, timestamp, body.decode("utf-8")),
    }


def send(port: int, body: bytes, headers: dict) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=7)
    try:
        connection.request("POST", "/webhooks", body, headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def run_demo() -> int:
    with tempfile.TemporaryDirectory(prefix="webhook-inbox-") as directory:
        inbox = Inbox(Path(directory) / "inbox.sqlite3")
        inbox.initialize()
        server = InboxServer(inbox, DEMO_SECRET)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            now = datetime.now(UTC)
            headers = signed_headers(DEMO_SECRET, "msg_invoice_042", DEMO_BODY, now)
            changed = DEMO_BODY.replace(b"12500", b"12501")
            cases = [
                ("valid", DEMO_BODY, headers, 200, "stored"),
                ("retry", DEMO_BODY, headers, 200, "duplicate"),
                ("tampered", changed, headers, 401, "verification_failed"),
                (
                    "stale",
                    DEMO_BODY,
                    signed_headers(DEMO_SECRET, "msg_stale", DEMO_BODY, now - timedelta(minutes=6)),
                    401,
                    "verification_failed",
                ),
                (
                    "conflict",
                    changed,
                    signed_headers(DEMO_SECRET, "msg_invoice_042", changed, now),
                    409,
                    "conflict",
                ),
            ]
            for name, body, case_headers, expected_status, expected_result in cases:
                status, response = send(port, body, case_headers)
                print(f"{name}: {status} {response['result']}")
                if (status, response["result"]) != (expected_status, expected_result):
                    return 1
            snapshot = inbox.inspect()
            print(f"events: {snapshot['count']}")
            print(f"duplicate_count: {snapshot['events'][0]['duplicate_count']}")
            print(f"sha256: {snapshot['events'][0]['sha256']}")
            return 0 if snapshot["count"] == 1 else 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
