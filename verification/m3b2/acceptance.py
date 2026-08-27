#!/usr/bin/env python3
"""Frozen acceptance for M3B2's JSONL build-event report CLI."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else Path.cwd()


class JsonLogReportAcceptance(unittest.TestCase):
    """Exercise the owner-facing contract independently of project tests."""

    def run_cli(self, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "jsonlog_report", str(source), str(output)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def build(self) -> str:
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = temporary / "events.jsonl"
        output = temporary / "report.html"
        source.write_text(
            "\n".join(
                (
                    '{"task":"Compile & Link","status":"ok","duration_ms":125}',
                    '{"task":"alpha","status":"failed","duration_ms":75}',
                    '{"task":"Compile & Link","status":"ok","duration_ms":25}',
                )
            )
            + "\n",
            encoding="utf-8",
        )
        result = self.run_cli(source, output)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertTrue(output.is_file())
        return output.read_text(encoding="utf-8")

    def test_generates_complete_utf8_html(self) -> None:
        report = self.build().lower()
        self.assertIn("<!doctype html>", report)
        self.assertIn('charset="utf-8"', report)

    def test_task_names_are_sorted_and_escaped(self) -> None:
        report = self.build()
        self.assertLess(report.index("alpha"), report.index("Compile &amp; Link"))
        self.assertNotIn("Compile & Link", report)

    def test_per_task_counts_are_reported(self) -> None:
        report = self.build()
        self.assertRegex(report, r"Compile &amp; Link[\s\S]*?2")
        self.assertRegex(report, r"alpha[\s\S]*?1")

    def test_per_task_durations_are_exact_integers(self) -> None:
        report = self.build()
        self.assertRegex(report, r"Compile &amp; Link[\s\S]*?150")
        self.assertRegex(report, r"alpha[\s\S]*?75")

    def test_overall_status_counts_and_duration_are_reported(self) -> None:
        report = self.build()
        self.assertRegex(report, r"(?:Overall|Total)[\s\S]*?3")
        self.assertRegex(report, r"(?:Overall|Total)[\s\S]*?2[\s\S]*?1")
        self.assertRegex(report, r"(?:Overall|Total)[\s\S]*?225")

    def test_output_is_deterministic(self) -> None:
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)

    def test_invalid_event_fails_cleanly_and_preserves_existing_output(self) -> None:
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = temporary / "bad.jsonl"
        output = temporary / "report.html"
        source.write_text(
            '{"task":"alpha","status":"unknown","duration_ms":-1}\n',
            encoding="utf-8",
        )
        output.write_text("keep-me", encoding="utf-8")
        result = self.run_cli(source, output)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep-me")
        self.assertNotIn("Traceback", result.stderr + result.stdout)

    def test_project_ships_runnable_own_tests(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("OK", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
