"""One loopback endpoint: bounded transport, official verification, durable receipt."""

import base64
import binascii
import json
import re
import socket
import sqlite3
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ._vendor.standardwebhooks import Webhook, WebhookVerificationError
from .storage import Inbox

MAX_BODY_BYTES = 65_536
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
TYPE_PATTERN = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*\Z")


def verifier_for(secret: str) -> Webhook:
    if not secret.startswith("whsec_"):
        raise ValueError("invalid secret configuration")
    try:
        key = base64.b64decode(secret[6:], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("invalid secret configuration") from None
    if not 24 <= len(key) <= 64:
        raise ValueError("invalid secret configuration")
    return Webhook(secret)


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


class InboxServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, inbox: Inbox, secret: str, port: int = 0, request_timeout: float = 5):
        self.inbox = inbox
        self.verifier = verifier_for(secret)
        self.request_timeout = request_timeout
        super().__init__(("127.0.0.1", port), Receiver)


class Receiver(BaseHTTPRequestHandler):
    server: InboxServer
    server_version = "SignedWebhookInbox/0.1"
    sys_version = ""

    def handle(self) -> None:
        self.expired = False
        self.connection.settimeout(self.server.request_timeout)
        timer = threading.Timer(self.server.request_timeout, self.expire)
        timer.daemon = True
        timer.start()
        try:
            super().handle()
        finally:
            timer.cancel()

    def expire(self) -> None:
        self.expired = True
        try:
            self.connection.shutdown(socket.SHUT_RD)
        except OSError:
            pass

    def log_message(self, format: str, *args) -> None:
        # No access logs: even rejected request targets and headers can contain secrets.
        pass

    def reply(self, status: int, result: str) -> None:
        self.close_connection = True
        payload = json.dumps({"result": result}, separators=(",", ":")).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            if status == 503:
                self.send_header("Retry-After", "1")
            self.end_headers()
            if getattr(self, "command", None) != "HEAD":
                self.wfile.write(payload)
        except OSError:
            # The row may already be committed; a sender retry is safe after a lost response.
            pass

    def send_error(self, code: int, message=None, explain=None) -> None:
        self.reply(code, HTTPStatus(code).phrase)

    def single_header(self, name: str) -> str:
        values = self.headers.get_all(name, [])
        if len(values) != 1 or "\r" in values[0] or "\n" in values[0]:
            raise ValueError("missing or ambiguous header")
        return values[0]

    def do_GET(self) -> None:
        self.reply(405, "method_not_allowed")

    do_PUT = do_GET
    do_PATCH = do_GET
    do_DELETE = do_GET
    do_HEAD = do_GET
    do_OPTIONS = do_GET

    def do_POST(self) -> None:
        if self.path != "/webhooks":
            self.reply(404, "not_found")
            return
        if self.headers.get_all("Transfer-Encoding"):
            self.reply(400, "unsupported_framing")
            return
        if self.headers.get_all("Expect"):
            self.reply(417, "unsupported_expectation")
            return
        if self.headers.get_all("Content-Encoding"):
            self.reply(415, "unsupported_content_encoding")
            return
        try:
            length_header = self.single_header("Content-Length")
        except ValueError:
            self.reply(400 if self.headers.get_all("Content-Length") else 411, "invalid_length")
            return
        if not re.fullmatch(r"[0-9]{1,6}", length_header):
            self.reply(400, "invalid_length")
            return
        length = int(length_header)
        if length > MAX_BODY_BYTES:
            self.reply(413, "body_too_large")
            return
        if not length:
            self.reply(400, "empty_body")
            return
        try:
            content_type = self.single_header("Content-Type")
            if not re.fullmatch(
                r"application/json(?:\s*;\s*charset=utf-8)?", content_type, re.IGNORECASE
            ):
                self.reply(415, "unsupported_content_type")
                return
            headers = {
                name: self.single_header(name)
                for name in ("webhook-id", "webhook-timestamp", "webhook-signature")
            }
            if not ID_PATTERN.fullmatch(headers["webhook-id"]):
                raise ValueError("invalid ID")
            if not re.fullmatch(r"[1-9][0-9]{0,10}", headers["webhook-timestamp"]):
                raise ValueError("invalid timestamp")
            signatures = headers["webhook-signature"]
            if len(signatures) > 1024:
                raise ValueError("signature header too long")
            # Validate syntax before the SDK's split/base64 parser; still delegate verification.
            for signature in signatures.split(" "):
                version, encoded = signature.split(",")
                if not re.fullmatch(r"v[0-9]{1,3}[a-z]?", version):
                    raise ValueError("invalid signature version")
                decoded = base64.b64decode(encoded, validate=True)
                if not decoded or (version == "v1" and len(decoded) != 32):
                    raise ValueError("invalid signature")
        except (ValueError, binascii.Error):
            self.reply(400, "invalid_headers")
            return
        try:
            body = self.rfile.read(length)
        except (TimeoutError, OSError):
            self.reply(408, "request_timeout")
            return
        if self.expired or len(body) != length:
            self.reply(408 if self.expired else 400, "incomplete_body")
            return
        try:
            # Exactly the received bytes; no JSON parse/serialization before verification.
            self.server.verifier.verify(body, headers, json_parse=False)
        except (WebhookVerificationError, ValueError, UnicodeError, binascii.Error):
            self.reply(401, "verification_failed")
            return
        try:
            payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
            )
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            event_type = payload.get("type")
            if (
                not isinstance(event_type, str)
                or len(event_type) > 128
                or not TYPE_PATTERN.fullmatch(event_type)
                or not isinstance(payload.get("data"), dict)
            ):
                raise ValueError("invalid payload contract")
        except (ValueError, UnicodeError, RecursionError):
            self.reply(400, "invalid_payload")
            return
        try:
            result = self.server.inbox.receive(
                headers["webhook-id"], body, event_type, int(headers["webhook-timestamp"])
            )
        except (sqlite3.Error, OSError):
            self.reply(503, "storage_unavailable")
            return
        self.reply(409 if result == "conflict" else 200, result)
