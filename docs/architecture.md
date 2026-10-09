# Receipt before acknowledgment

The business boundary demonstrated here is accepting an authenticated event
without creating duplicate records when a sender retries. A successful response
means the event is durably recorded, not that an invoice or customer system has
been updated.

```text
loopback POST /webhooks
  -> validate one bounded, uncompressed Content-Length body
  -> validate ID, timestamp, and signature header syntax
  -> unchanged local SDK source verifies received bytes + ID + timestamp
  -> validate UTF-8 JSON {type, data}
  -> BEGIN IMMEDIATE in SQLite
       new ID             -> insert raw bytes + SHA-256 + receipt metadata
       same ID, same bytes -> increment duplicate count
       same ID, new bytes  -> rollback, retain original, 409
  -> COMMIT succeeds -> 200
  -> storage/commit fails -> rollback/close, 503
```

## Identity and audit data

The primary key is the signed event ID. Comparison uses the stored BLOB itself;
the SHA-256 is audit metadata and is not the sole equality check. Two bodies with
the same JSON meaning but different whitespace are conflicting payloads under
one ID. Retrying producers must preserve bytes. A retry may sign a fresh attempt
timestamp and use a new matching signature.

Each row stores the original bytes, hash, event type, first signed timestamp,
first/last accepted receipt times, retry count, and verifier version/scheme.
Rejected requests and conflicts are not persisted. This is deliberately a
receipt audit, not an exhaustive attempt log. Signatures and signing secrets
are not stored or printed. Inspection exposes metadata without raw payloads.

## Concurrency and recovery

Each HTTP request gets its own SQLite connection. `BEGIN IMMEDIATE` serializes
the ID lookup, insertion, and retry-counter update. A racing request waits for
the previous transaction or gets `503` after one second. The primary key also
enforces uniqueness in the database. Conflicts return without commit, and closing
the connection rolls back. `synchronous=FULL` is set on write connections;
initialization selects WAL mode.

If a response is lost after commit, the sender cannot know it succeeded. Retrying
produces a duplicate success. If a commit fails, no successful acknowledgment is
sent. The test suite covers these boundaries with a real database, a real socket,
parallel callers, lock contention, a write-aborting trigger, injected commit
failure, and a terminated/restarted CLI process.

## Transport boundary

The listener is fixed to IPv4 `127.0.0.1`. No remote address can be configured.
The body is at most 65,536 bytes; a timer ends reads after five seconds across
headers and body, even if bytes arrive slowly. Python's HTTP parser also bounds
header count and line size. Every response closes the connection, so extra body
bytes are never interpreted as a second request. Duplicate lengths, transfer
encoding, folded authentication headers, compressed payloads, and `Expect`
are rejected. The application returns sanitized JSON errors and disables
request logging so it does not echo attacker-supplied targets or secrets.

This is a local development server with unbounded request threads and no TLS.
It demonstrates a receipt contract; production availability, capacity control,
filesystem hardening, signing-key lifecycle, retention, monitoring, and business
side-effect transactions are not implemented or validated by this reference.
