# Source lineage and executable reuse

This local source-based assembly preserves the old `signed-webhook-inbox`
candidate separately. It starts with a pinned concrete implementation, duplicates
its source, and runs that duplicate as the signing and verification component.

## Inspected original

Standard Webhooks Python SDK 1.1.0, commit
`dc4aed97b92dd04afc6c62428fe936bae7251b6b`, uses Python's standard-library HMAC,
SHA-256, constant-time comparison, UTF-8 input, and a five-minute attempt timestamp
tolerance. Its `verify(..., json_parse=False)` separates verification from JSON
handling. Its tests cover empty secrets, missing headers, invalid signatures,
old/new timestamps, multiple signatures, prefixed/unpadded secrets, and a known
signing vector. The upstream development process uses pytest and formatter/type
checks declared in its metadata; these metadata files are preserved unchanged.

The files were inspected before composition and fetched as raw bytes from these
immutable sources:

- [Verifier](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/python/standardwebhooks/webhooks.py)
- [Initializer and version](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/python/standardwebhooks/__init__.py)
- [Exception re-export](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/python/standardwebhooks/exceptions.py)
- [Typing marker](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/python/standardwebhooks/py.typed)
- [Package metadata](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/python/pyproject.toml)
- [Upstream tests](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/python/tests/test_webhooks.py)
- [README](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/python/README.md)
- [MIT license](https://github.com/standard-webhooks/standard-webhooks/blob/dc4aed97b92dd04afc6c62428fe936bae7251b6b/libraries/LICENSE)

The SDK verifier SHA-256 is
`b701369347325085aea04be18a2a6f441ae40a69dc920fd9b3f29b125c15a0ff`.
The fetched files were compared with the old pinned inspection snapshots where
available. The source-path-to-copy-path mappings and all hashes are in
[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json).

## Original -> unchanged copy -> composed inbox

1. **Original extraction:** `upstream/standard-webhooks/` contains the complete
   Python module package, original tests, metadata, README, and release MIT license.
   The unchanged upstream tests execute this package from that directory.
2. **Unchanged runtime copy:** `src/signed_webhook_inbox/_vendor/standardwebhooks/`
   contains the same verifier, initializer, exception re-export, typing marker,
   and license bytes.
   The same unchanged upstream test file executes this namespaced package through
   a test-only import alias. No crypto or verifier behavior is changed.
3. **Composition:** `server.py` and `demo.py` import this explicit local namespace.
   Requests call its `Webhook.verify` on received bytes before JSON parsing, and
   the demo/CLI sender calls its `Webhook.sign`. The former external SDK dependency
   is removed. A fresh wheel environment has no installed `standardwebhooks`
   distribution or top-level module, while the local component still executes.

The recorded results are summarized in [VERIFICATION.md](VERIFICATION.md) and
[docs/verification.json](docs/verification.json). The two SDK baselines use the
identical upstream test file, so the comparison concerns source placement and
execution rather than rewritten assertions. Full task-local attempt logs retain
the initial incomplete-package build and the overlapping install/test receipt;
they are excluded from the public source.

## Reused extension and narrow adaptations

The prior local candidate supplies the receiver, SQLite storage, CLI, fixture,
demo, and 25 product contracts. This assembly changes two imports, removes the
external SDK runtime dependency, includes the copied component/license in wheels,
and adds provenance and baseline verification. Existing transport and storage
behavior is retained: bounded raw body; strict header syntax; signature before
payload validation; commit before acknowledgment; exact-byte duplicate/conflict
handling; retry count; read-only inspection; and restart persistence.

Two copied test helpers formerly used `with sqlite3.connect(...)`, which commits
or rolls back but does not close the connection. Their narrow fix uses
`contextlib.closing`; the trigger setup keeps its transaction context inside the
closing context. A connection ownership check verifies that initialization,
receive success, duplicate, conflict, failure, and inspection close their handles.
This does not change the SDK or storage schema.

The earlier receiver patterns came from Svix commit
`2f06f3d9bd98249f5f955bde4b23ae4d2d1ceeb9`:
[bridge receiver](https://github.com/svix/svix-webhooks/blob/2f06f3d9bd98249f5f955bde4b23ae4d2d1ceeb9/bridge/svix-bridge/src/webhook_receiver/mod.rs)
verifies before payload handling and acknowledges after successful handling.
Its remote forwarding, transformations, plugins, and adapters remain outside
this local slice. The original candidate's `.reference` files and prior receipt
remain protected and are not runtime components of this new package.

## Linux workflow and offline view references (2026-10-15)

The inspected companion implementations were `ops-daily-report`'s
`src/ops_daily_report/cli.py`, `html_report.py`, README and `docs/DESIGN.md`, and
`pii-redaction-review`'s `redaction_cli.py` and README. The inbox adopts their
installed-command first run, retained synthetic outputs, summary counts before
details, escaped metadata, labeled horizontal table scrolling, keyboard focus,
print treatment and self-contained offline view. The static report needs no
JavaScript or new rendering dependency. Those references informed the structure;
no third-party parser or redaction implementation is included here.

The existing `Inbox.inspect()` query supplies report metadata. It does not select
raw bodies or signing material. The original demo keeps its no-flag temporary
behavior; `--output-dir` selects a new retained directory and uses the same public
synthetic body already embedded in the installed package. The HTTP server, schema,
signature verifier and signing path are unchanged. New reports use exclusive file
creation, and retained demos refuse an existing directory before starting HTTP.

## Reproduce and understand the limits

Install `.[dev]` in a fresh environment, then run:

```sh
python tools/source_contract.py original
python tools/source_contract.py copy
python -m unittest discover -s tests -v
python -m signed_webhook_inbox demo
python -m build
```

The source-contract runner, test contracts and pinned source snapshots are
included. Raw task-local logs, virtual environments, caches and private
verification tooling are excluded. The standard runtime uses no PyPI SDK or
third-party runtime package. Development tools and build isolation can still
download their pinned dependencies.

Python's development HTTP server, unbounded request threads, loopback HTTP,
one key, indefinite event retention, and filesystem-dependent crash durability
remain limits. Receipt deduplication does not provide exactly-once business side
effects. The base revision `a1e2cfa9dab431736bc4d38bb5febb649cc1c8e7` has a
[successful GitHub contracts run](https://github.com/skyon0522-ai/signed-webhook-inbox/actions/runs/38060147600),
observed on 2026-10-15 JST. The new local candidate has not run remotely.
Local Python 3.11 execution, external integrations, customer use, paid
demand, revenue, and production security certification are unverified. No public
or cloud changes are part of this source-composition stage.
