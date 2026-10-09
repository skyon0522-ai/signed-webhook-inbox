"""Run byte-unchanged upstream tests against the original or namespaced copy."""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

root = Path(__file__).resolve().parents[1]
mode = sys.argv[1]
if mode == "original":
    sys.path.insert(0, str(root / "upstream" / "standard-webhooks"))
    package = importlib.import_module("standardwebhooks")
    module = importlib.import_module("standardwebhooks.webhooks")
elif mode == "copy":
    package = importlib.import_module("signed_webhook_inbox._vendor.standardwebhooks")
    module = importlib.import_module("signed_webhook_inbox._vendor.standardwebhooks.webhooks")
    # The upstream test import is the only adapter; its file remains unchanged.
    sys.modules["standardwebhooks"] = package
    sys.modules["standardwebhooks.webhooks"] = module
else:
    raise ValueError("expected original or copy")
path = Path(module.__file__)
print(
    json.dumps(
        {
            "mode": mode,
            "module_file": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    ),
    flush=True,
)
raise SystemExit(
    pytest.main(
        [
            str(root / "upstream/standard-webhooks/tests/test_webhooks.py"),
            "-q",
            "-p",
            "no:cacheprovider",
            "--import-mode=importlib",
        ]
    )
)
