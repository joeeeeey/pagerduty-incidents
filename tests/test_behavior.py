import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pd_api as cli


class Behavior(unittest.TestCase):
    def run_cli(self, argv):
        args = cli.build_parser().parse_args(argv)
        with contextlib.redirect_stdout(io.StringIO()):
            return args.func(args)

    def test_event_dry_run_no_credentials(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("pd_api._events_post") as req,
        ):
            self.assertEqual(
                self.run_cli(["events", "resolve", "--dedup-key", "synthetic"]), 0
            )
            req.assert_not_called()

    def test_trigger_requires_payload(self):
        with patch("pd_api._events_post") as req:
            self.assertEqual(
                self.run_cli(["events", "trigger", "--dedup-key", "synthetic"]), 2
            )
            req.assert_not_called()

    def test_batch_guard_and_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "ids"
            f.write_text("a\na\nb\n")
            with (
                patch.dict(
                    os.environ,
                    {"PAGERDUTY_EVENTS_ROUTING_KEY": "synthetic"},
                    clear=True,
                ),
                patch("pd_api._events_post", return_value=(202, "{}")) as req,
            ):
                self.assertEqual(
                    self.run_cli(
                        ["events", "batch-resolve", "--file", str(f), "--execute"]
                    ),
                    2,
                )
                req.assert_not_called()
                self.assertEqual(
                    self.run_cli(
                        [
                            "events",
                            "batch-resolve",
                            "--file",
                            str(f),
                            "--execute",
                            "--confirm",
                        ]
                    ),
                    0,
                )
                self.assertEqual(req.call_count, 2)

    def test_nested_preview_secret(self):
        value = cli._redact_payload_for_preview(
            {"routing_key": "abc", "payload": {"custom_details": {"password": "xyz"}}}
        )
        self.assertNotIn("xyz", json.dumps(value))
        self.assertNotIn("abc", json.dumps(value))
