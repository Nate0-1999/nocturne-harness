#!/usr/bin/env python3
"""Fixed pre-round acceptance for the M3BT1 CSV summary-report CLI."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else Path.cwd()


class CsvReportAcceptance(unittest.TestCase):
    def run_cli(self, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "csvreport", str(source), str(output)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def build(self) -> str:
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = temporary / "sales.csv"
        output = temporary / "report.html"
        source.write_text(
            "category,amount\nBooks,10.10\nGames,4.00\nBooks,2.30\nA&B,1.00\n",
            encoding="utf-8",
        )
        result = self.run_cli(source, output)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertTrue(output.is_file())
        return output.read_text(encoding="utf-8")

    def test_generates_complete_utf8_html(self) -> None:
        report = self.build()
        self.assertIn("<!doctype html>", report.lower())
        self.assertIn('charset="utf-8"', report.lower())

    def test_categories_are_sorted_and_escaped(self) -> None:
        report = self.build()
        self.assertLess(report.index("A&amp;B"), report.index("Books"))
        self.assertLess(report.index("Books"), report.index("Games"))
        self.assertNotIn("<td>A&B</td>", report)

    def test_category_counts_are_reported(self) -> None:
        report = self.build()
        self.assertRegex(report, r"Books[\s\S]*?2")
        self.assertRegex(report, r"Games[\s\S]*?1")

    def test_category_totals_use_exact_two_decimal_money(self) -> None:
        report = self.build()
        self.assertIn("12.40", report)
        self.assertIn("4.00", report)
        self.assertIn("1.00", report)

    def test_category_averages_are_reported(self) -> None:
        report = self.build()
        self.assertIn("6.20", report)

    def test_overall_count_and_total_are_reported(self) -> None:
        report = self.build()
        self.assertIn("17.40", report)
        self.assertRegex(report, r"(?:Overall|Total)[\s\S]*?4")

    def test_invalid_amount_fails_without_partial_output_or_traceback(self) -> None:
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = temporary / "bad.csv"
        output = temporary / "report.html"
        source.write_text("category,amount\nBooks,not-money\n", encoding="utf-8")
        result = self.run_cli(source, output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
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

