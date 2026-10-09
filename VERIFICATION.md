# Recorded source-composition verification

## Original → unchanged copy → inbox

The complete Standard Webhooks 1.1.0 Python package is preserved at commit `dc4aed97b92dd04afc6c62428fe936bae7251b6b`, with its tests, metadata, README and MIT license. The same upstream test file passed all 15 tests against the original source snapshot and again against the unchanged namespaced copy. A test-only import alias selects the latter; no assertions or cryptographic behavior are rewritten.

The existing inbox extension now imports the local copy for verification and signing and has no external runtime dependencies. The existing 25 product contracts remain; a connection-ownership check makes 26. All 26 passed locally and against a fresh installed wheel. Lint, formatting, build, console demo and the fresh environment's dependency check passed.

The installed-wheel probe observed five verification calls and seven signing calls. The external `standardwebhooks` module and distribution were absent. The copied verifier, initializer, exception re-export, typing marker and MIT license had equal bytes across the source snapshot, namespaced source, final wheel and installed files. [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json) and [docs/verification.json](docs/verification.json) record the source identities and outcomes.

## Narrow correction and preserved attempts

Two inherited test helpers used a SQLite transaction context without explicitly closing connections. A preliminary 25-test run reported 24 unclosed-database warnings. Using `contextlib.closing` in those helpers preserved their transactions and reduced observed ResourceWarnings to zero. Storage implementation code did not change. The added check retains six handles and confirms closure after initialization, receive, duplicate, conflict, injected write failure and inspection.

The first private package build omitted the upstream exception re-export. Its artifacts were preserved and a complete package was rebuilt before final byte/readback proof. The installed product-test command began 0.768 seconds before its pip command completed; both succeeded. The receipt preserves the recovered tool output and this ordering limitation. The separate installed-module byte and runtime-call proof ran after both commands completed. No claim is made that those first two commands ran sequentially.

## Scope

Observed runtime: Python 3.13.16, SQLite 3.53.1, Linux under Ubuntu 24.04/WSL2. The final wheel was installed into a fresh environment without index access or dependency installation. Existing local development/build tools were used. Native Windows, Python 3.11, fresh dependency downloads and GitHub CI execution are unverified.

The checks exercise raw-body authentication before JSON parsing, bounded HTTP handling, exact-byte duplicate/conflict decisions, commit before acknowledgment, lock/write/commit failures and CLI restart inspection. The server is a loopback development reference with unbounded request threads, one key and indefinite retention. Receipt deduplication does not guarantee exactly-once business effects, production capacity, key lifecycle or filesystem/hardware crash durability.

Raw private logs and task paths are excluded from this source bundle. The public summary reports observed outcomes, not customer deployment, paid demand or production certification.
