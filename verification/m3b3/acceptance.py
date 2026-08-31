#!/usr/bin/env python3
"""Frozen acceptance for round three's INI audit-report CLI."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else Path.cwd()


class IniAuditAcceptance(unittest.TestCase):
    """Exercise the owner-facing contract independently of project tests."""

    def run_cli(self, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "inireport", str(source), str(output)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def build(self) -> str:
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = temporary / "service.ini"
        output = temporary / "audit.html"
        source.write_text(
            "\n".join(
                (
                    "[database]",
                    "workers = 4",
                    "password = hunter2",
                    "host = localhost",
                    "",
                    "[app]",
                    "name = Alpha & Beta",
                    "api_token = token-value-123",
                    "",
                )
            ),
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

    def test_sections_are_sorted_and_values_are_escaped(self) -> None:
        report = self.build()
        self.assertLess(report.lower().index("app"), report.lower().index("database"))
        self.assertIn("Alpha &amp; Beta", report)
        self.assertNotIn("Alpha & Beta", report)

    def test_keys_are_sorted_within_each_section(self) -> None:
        report = self.build().lower()
        app_start = report.index("app")
        database_start = report.index("database", app_start + 1)
        app = report[app_start:database_start]
        database = report[database_start:]
        self.assertLess(app.index("api_token"), app.index("name"))
        self.assertLess(database.index("host"), database.index("password"))
        self.assertLess(database.index("password"), database.index("workers"))

    def test_secret_like_values_are_redacted(self) -> None:
        report = self.build()
        self.assertNotIn("hunter2", report)
        self.assertNotIn("token-value-123", report)
        self.assertGreaterEqual(report.upper().count("REDACTED"), 2)

    def test_summary_counts_sections_keys_and_redactions(self) -> None:
        report = self.build()
        self.assertRegex(report, r"(?i)sections?[\s\S]{0,80}?2")
        self.assertRegex(report, r"(?i)keys?[\s\S]{0,80}?5")
        self.assertRegex(report, r"(?i)redacted[\s\S]{0,80}?2")

    def test_output_is_deterministic(self) -> None:
        self.assertEqual(self.build(), self.build())

    def test_invalid_ini_fails_cleanly_and_preserves_existing_output(self) -> None:
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = temporary / "bad.ini"
        output = temporary / "audit.html"
        source.write_text("[app]\nname=one\nname=two\n", encoding="utf-8")
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
