# Signed Webhook Inbox

Webhook retries can create duplicate invoice, subscription, or CRM updates. This
local integration reference verifies a signed event before writing it to SQLite,
acknowledges it only after commit, and keeps one immutable payload per event ID.
An identical retry succeeds; changed bytes under an existing ID return `409`.

The pinned Standard Webhooks 1.1.0 source is copied unchanged into this package
and executes for verification and signing. This assembly reuses the existing
inbox extension for HTTP limits, a small JSON contract, durable deduplication,
and read-only inspection. It is a local integration reference with no external
runtime dependencies. Its source lineage is recorded in
[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json).

## Try the complete scenario

Python 3.11 or newer and SQLite 3.37 or newer are required. The [verification record](docs/verification.json)
records the exact tested runtime. In a fresh checkout:

```sh
python -m venv .venv
# POSIX / WSL:
.venv/bin/python -m pip install .
.venv/bin/python -m signed_webhook_inbox demo
# Windows PowerShell: use .venv\Scripts\python.exe for the same commands.
```

The demo starts its own server on `127.0.0.1` with an OS-assigned port, sends
five requests, reads the database, and removes its temporary database on exit.
Its fixture and outcome lines are deterministic; each run signs fresh timestamps.
Actual output is recorded in [docs/example-output.txt](docs/example-output.txt).

```text
valid: 200 stored
retry: 200 duplicate
tampered: 401 verification_failed
stale: 401 verification_failed
conflict: 409 conflict
events: 1
duplicate_count: 1
sha256: 1858de5efce540080ac8d1bff5d7d72501b0c8222ebd4573328de36d095f879b
```

## Run a persistent inbox

Create a new random key locally and keep it in the environment. The key must use
the `whsec_` prefix followed by padded Base64 for 24–64 random bytes.

```sh
export WEBHOOK_SECRET="$(.venv/bin/python -c 'import base64,secrets; print("whsec_"+base64.b64encode(secrets.token_bytes(32)).decode())')"
.venv/bin/python -m signed_webhook_inbox serve --db inbox.sqlite3 --port 8099
```

PowerShell key generation and startup:

```powershell
$env:WEBHOOK_SECRET = .venv\Scripts\python.exe -c 'import base64,secrets; print("whsec_"+base64.b64encode(secrets.token_bytes(32)).decode())'
.venv\Scripts\python.exe -m signed_webhook_inbox serve --db inbox.sqlite3 --port 8099
```

In a second terminal with the same `WEBHOOK_SECRET`, send the fixture twice:

```sh
.venv/bin/python -m signed_webhook_inbox send --id msg_invoice_042 --payload-file examples/invoice-paid.json
.venv/bin/python -m signed_webhook_inbox send --id msg_invoice_042 --payload-file examples/invoice-paid.json
.venv/bin/python -m signed_webhook_inbox inspect --db inbox.sqlite3
```

The sender prints `{"status":200,"result":"stored"}` followed by
`{"status":200,"result":"duplicate"}`. `inspect` prints JSON with one event,
its original payload hash, byte count, receipt metadata, and `duplicate_count: 1`.
It opens SQLite in read-only mode and fails if the file does not exist.
`Ctrl+C` stops the server; restarting with the same database keeps event IDs.
The server and sender expose no host or remote URL option and use only loopback.

## Request contract

Send `POST /webhooks` with exactly one each of `Content-Length`, `Content-Type`,
`webhook-id`, `webhook-timestamp`, and `webhook-signature`. The content type is
`application/json`, optionally with `charset=utf-8`. The body limit is 65,536
bytes. The total connection read deadline is five seconds, including headers;
SQLite lock waiting is bounded to one second.

An ID contains 1–128 ASCII letters, digits, underscores, or hyphens. The timestamp
is an integer Unix second. The SDK accepts attempts within five minutes of the
server's clock in either direction, so the clock must be accurate. Retries use
the same ID and exact body bytes with a fresh signed attempt timestamp.

The payload is a UTF-8 JSON object containing a `type` such as `invoice.paid` and
a `data` object. Event types contain dot-separated ASCII letters, digits, or
underscores, up to 128 characters. Other fields are preserved. Duplicate JSON
keys and nonstandard `NaN`/`Infinity` literals are rejected. JSON is validated
after signature verification, and the original bytes are stored without rewriting.

| Response | Meaning |
| --- | --- |
| `200 stored` | Verification and validation passed; a new row committed. |
| `200 duplicate` | Exact stored bytes matched; the retry counter committed. |
| `409 conflict` | A correctly signed request reused an ID with different bytes; the original row stayed unchanged. |
| `401 verification_failed` | Signature, UTF-8 verification input, or timestamp tolerance failed. |
| `400` | Malformed headers, framing, truncated body, or invalid JSON contract. |
| `411` / `413` | Missing length / body over the limit. |
| `415` / `417` | Unsupported media or encoding / unsupported `Expect`. |
| `408` | Body read deadline expired. A stalled or disconnected client may receive a closed connection instead. |
| `404` / `405` / `501` | Unknown route / explicitly rejected method / method not implemented by the development server. |
| `503 storage_unavailable` | Storage or commit failed; no success acknowledgment. Includes `Retry-After: 1`. |

Chunked requests, duplicate framing headers, compressed bodies, and
`Expect: 100-continue` are intentionally unsupported. Responses close the
connection. Methods not implemented by Python's development server, such as
`TRACE`, receive `501` with the JSON result `Not Implemented`. Only Standard Webhooks `v1`
symmetric signatures are verified; the
library may accept a valid `v1` alongside syntactically valid unknown versions.
This endpoint accepts `webhook-*` headers, not Svix's legacy `svix-*` aliases.

## Verify the contracts

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m build
```

Install `.[dev]` to run development checks. The suite uses real loopback HTTP for valid, tampered, stale, malformed,
duplicate, conflict, framing, deadline, and parallel-race cases. It exercises
real SQLite locks and trigger failures, injects a commit failure, and terminates
and restarts a CLI server process to check persistence. The demo is executed
twice to compare printed outcomes. CI uses pinned action commits and dependencies.
It has not been executed on GitHub. The unchanged upstream SDK tests can be run
against the source snapshot or the local copy with the receipt runner documented
in [REFERENCES.md](REFERENCES.md). The original-to-copy comparison and installed
wheel execution evidence are summarized in [VERIFICATION.md](VERIFICATION.md)
and [docs/verification.json](docs/verification.json).

## Design and limits

See [architecture](docs/architecture.md), [reference provenance](REFERENCES.md),
and [third-party notices](THIRD_PARTY_NOTICES.md). Each ID represents one stored
event, not exactly-once execution of business side effects. There is no consumer,
queue, delivery service, dashboard, key rotation manager, or remote integration.

SQLite uses WAL and `synchronous=FULL`; actual crash durability still depends on
the filesystem and hardware honoring synchronization. Keep the database and its
WAL files together; stop the process before a file copy or use SQLite's backup
API. IDs are retained indefinitely. The database contains raw event data and
must be protected with local file permissions. Payloads, signatures, and secrets
are not logged by the receiver; `inspect` prints only metadata.

Python's development HTTP server, unbounded request threads, plain loopback HTTP,
and a single configured key are deliberate local-demo limits. No public hosting,
provider account, customer deployment, or revenue result is demonstrated here.

## Research background

[RESEARCH.md](RESEARCH.md) relates the selected HMAC construction and signed
message fields to the original HMAC paper and Standard Webhooks specification.
It separates cryptographic background from this application's storage and HTTP checks.
