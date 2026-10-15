"""A deterministic local scenario; timestamps refresh but printed outcomes stay stable."""

import base64
import http.client
import json
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ._vendor.standardwebhooks import Webhook
from .html_report import write_report
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


def run_demo(output_dir: Path | None = None) -> int:
    if output_dir is not None:
        output_dir.mkdir()
        return _run_scenario(output_dir, retain=True)
    with tempfile.TemporaryDirectory(prefix="webhook-inbox-") as directory:
        return _run_scenario(Path(directory), retain=False)


def _run_scenario(directory: Path, *, retain: bool) -> int:
    outcomes = []

    def record(line: str) -> None:
        outcomes.append(line)
        print(line)

    inbox = Inbox(directory / "inbox.sqlite3")
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
            record(f"{name}: {status} {response['result']}")
            if (status, response["result"]) != (expected_status, expected_result):
                return 1
        snapshot = inbox.inspect()
        record(f"events: {snapshot['count']}")
        record(f"duplicate_count: {snapshot['events'][0]['duplicate_count']}")
        record(f"sha256: {snapshot['events'][0]['sha256']}")
        success = snapshot["count"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    if retain and success:
        documents = {
            "invoice-paid.json": DEMO_BODY.decode("utf-8"),
            "inspect.json": json.dumps(snapshot, indent=2) + "\n",
            "outcomes.txt": "\n".join(outcomes) + "\n",
        }
        for name, content in documents.items():
            with (directory / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        write_report(inbox, directory / "report.html")
        print(f"Demo outputs: {directory.resolve()}")
    return 0 if success else 1
