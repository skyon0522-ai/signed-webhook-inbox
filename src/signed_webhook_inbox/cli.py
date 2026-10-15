"""Small CLI; secrets come from the environment and are never printed."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from .demo import run_demo, send, signed_headers
from .html_report import write_report
from .server import ID_PATTERN, MAX_BODY_BYTES, InboxServer, verifier_for
from .storage import Inbox


def port_number(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A local, durable signed webhook inbox")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="listen only on 127.0.0.1")
    serve.add_argument("--db", type=Path, required=True)
    serve.add_argument("--port", type=port_number, default=8099)
    inspect = commands.add_parser(
        "inspect", help="read event metadata without changing the database"
    )
    inspect.add_argument("--db", type=Path, required=True)
    report = commands.add_parser("report", help="write a new offline HTML metadata snapshot")
    report.add_argument("--db", type=Path, required=True)
    report.add_argument("--html", type=Path, required=True, help="new HTML file; parent must exist")
    sender = commands.add_parser("send", help="send a signed JSON fixture to loopback")
    sender.add_argument("--port", type=port_number, default=8099)
    sender.add_argument("--id", required=True)
    sender.add_argument("--payload-file", type=Path, required=True)
    demo = commands.add_parser("demo", help="run valid/retry/tamper/stale/conflict cases locally")
    demo.add_argument("--output-dir", type=Path, help="retain synthetic outputs in a new directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            return run_demo(args.output_dir)
        if args.command == "inspect":
            print(json.dumps(Inbox(args.db).inspect(), indent=2))
            return 0
        if args.command == "report":
            write_report(Inbox(args.db), args.html)
            print(f"HTML report: {args.html.resolve()}")
            return 0
        secret = os.environ.get("WEBHOOK_SECRET", "")
        verifier_for(secret)
        if args.command == "send":
            if not ID_PATTERN.fullmatch(args.id):
                raise ValueError("invalid event ID")
            with args.payload_file.open("rb") as fixture:
                body = fixture.read(MAX_BODY_BYTES + 1)
            if not 0 < len(body) <= MAX_BODY_BYTES:
                raise ValueError("invalid fixture size")
            status, result = send(
                args.port, body, signed_headers(secret, args.id, body, datetime.now(UTC))
            )
            print(json.dumps({"status": status, **result}, separators=(",", ":")))
            return 0 if 200 <= status < 300 else 1
        inbox = Inbox(args.db)
        inbox.initialize()
        with InboxServer(inbox, secret, args.port) as server:
            print(f"listening: http://127.0.0.1:{server.server_address[1]}/webhooks", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    except FileExistsError:
        print("error: output already exists; choose a new file or directory", file=sys.stderr)
    except (ValueError, UnicodeError):
        print("error: invalid configuration or fixture", file=sys.stderr)
    except (sqlite3.Error, OSError):
        print("error: local storage or transport unavailable", file=sys.stderr)
    return 1
