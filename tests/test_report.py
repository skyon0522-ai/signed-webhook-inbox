import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from signed_webhook_inbox.demo import DEMO_BODY, DEMO_SECRET
from signed_webhook_inbox.html_report import render_html, write_report
from signed_webhook_inbox.storage import Inbox


class ReportContractTests(unittest.TestCase):
    def test_report_escapes_metadata_and_omits_payload_and_signing_material(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Inbox(Path(directory) / "inbox.sqlite3")
            inbox.initialize()
            inbox.receive('<script>alert("id")</script>', DEMO_BODY, 'type<&"', 1)
            page = render_html(inbox.inspect())
            self.assertIn("&lt;script&gt;alert(&quot;id&quot;)&lt;/script&gt;", page)
            self.assertIn("type&lt;&amp;&quot;", page)
            for excluded in ("<script>", "invoice_id", "inv_042", DEMO_SECRET, str(inbox.path)):
                self.assertNotIn(excluded, page)
            self.assertIn("default-src 'none'", page)

    def test_report_is_read_only_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Inbox(Path(directory) / "inbox.sqlite3")
            inbox.initialize()
            inbox.receive("one", DEMO_BODY, "invoice.paid", 1)
            before = inbox.path.read_bytes()
            target = Path(directory) / "review.html"
            write_report(inbox, target)
            original = target.read_bytes()
            with self.assertRaises(FileExistsError):
                write_report(inbox, target)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(inbox.path.read_bytes(), before)
            self.assertEqual(inbox.inspect()["count"], 1)

    def test_missing_database_creates_neither_database_nor_report(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.sqlite3"
            target = Path(directory) / "report.html"
            with self.assertRaises(sqlite3.OperationalError):
                write_report(Inbox(missing), target)
            self.assertFalse(missing.exists())
            self.assertFalse(target.exists())
            result = self.cli("report", "--db", str(missing), "--html", str(target))
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertFalse(missing.exists())
            self.assertFalse(target.exists())

    def test_empty_inbox_has_explicit_empty_state(self):
        page = render_html({"count": 0, "events": []})
        self.assertIn("No accepted events in this inbox.", page)
        self.assertIn("<strong>0</strong><span>Stored events</span>", page)

    @staticmethod
    def cli(*args, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "signed_webhook_inbox", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=15,
        )

    def test_demo_retains_reusable_outputs_from_other_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "retained"
            result = self.cli("demo", "--output-dir", str(output), cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            names = {
                "inbox.sqlite3",
                "invoice-paid.json",
                "inspect.json",
                "report.html",
                "outcomes.txt",
            }
            self.assertTrue(names.issubset(path.name for path in output.iterdir()))
            self.assertEqual((output / "invoice-paid.json").read_bytes(), DEMO_BODY)
            snapshot = json.loads((output / "inspect.json").read_text())
            self.assertEqual(snapshot, Inbox(output / "inbox.sqlite3").inspect())
            self.assertEqual(snapshot["count"], 1)
            self.assertEqual(snapshot["events"][0]["duplicate_count"], 1)
            self.assertEqual(snapshot["events"][0]["sha256"], hashlib.sha256(DEMO_BODY).hexdigest())
            self.assertIn(
                "tampered: 401 verification_failed", (output / "outcomes.txt").read_text()
            )
            self.assertIn(
                "<strong>2</strong><span>Accepted receipts</span>",
                (output / "report.html").read_text(),
            )
            target = Path(directory) / "regenerated.html"
            report = self.cli(
                "report",
                "--db",
                str(output / "inbox.sqlite3"),
                "--html",
                str(target),
                cwd=directory,
            )
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertEqual(target.read_bytes(), (output / "report.html").read_bytes())

    def test_existing_demo_directory_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("keep")
            result = self.cli("demo", "--output-dir", str(output), cwd=directory)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("output already exists", result.stderr)
            self.assertEqual(list(output.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
