#!/usr/bin/env python3
"""Fixed pre-round acceptance for the M3BT1 Markdown site generator."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else Path.cwd()


class MarkdownSiteAcceptance(unittest.TestCase):
    def run_cli(self, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "notes2site", str(source), str(output)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def build(self) -> tuple[Path, str, str]:
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        notes = temporary / "notes"
        site = temporary / "site"
        notes.mkdir()
        (notes / "alpha-note.md").write_text(
            "# Alpha & One\n\nOpening <tag> paragraph.\n\n## Details\n\n- first\n- second\n",
            encoding="utf-8",
        )
        (notes / "beta.md").write_text(
            "# Beta\n\nUse `safe()` and visit [Alpha](alpha-note.md).\n",
            encoding="utf-8",
        )
        result = self.run_cli(notes, site)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return site, (site / "alpha-note.html").read_text(), (site / "beta.html").read_text()

    def test_creates_index_and_one_page_per_note(self) -> None:
        site, _, _ = self.build()
        self.assertEqual(
            sorted(path.name for path in site.glob("*.html")),
            ["alpha-note.html", "beta.html", "index.html"],
        )

    def test_index_is_deterministic_and_links_both_notes(self) -> None:
        site, _, _ = self.build()
        index = (site / "index.html").read_text()
        self.assertLess(index.index("Alpha &amp; One"), index.index("Beta"))
        self.assertIn('href="alpha-note.html"', index)
        self.assertIn('href="beta.html"', index)

    def test_headings_paragraphs_and_lists_render(self) -> None:
        _, alpha, _ = self.build()
        self.assertIn("<h1>Alpha &amp; One</h1>", alpha)
        self.assertIn("<h2>Details</h2>", alpha)
        self.assertIn("<p>Opening &lt;tag&gt; paragraph.</p>", alpha)
        self.assertIn("<ul>", alpha)
        self.assertIn("<li>first</li>", alpha)

    def test_inline_code_and_markdown_links_render(self) -> None:
        _, _, beta = self.build()
        self.assertIn("<code>safe()</code>", beta)
        self.assertIn('href="alpha-note.html"', beta)

    def test_every_note_page_has_navigation(self) -> None:
        _, alpha, beta = self.build()
        for page in (alpha, beta):
            self.assertIn('href="index.html"', page)
            self.assertIn('href="alpha-note.html"', page)
            self.assertIn('href="beta.html"', page)

    def test_html_is_a_complete_utf8_document(self) -> None:
        site, alpha, _ = self.build()
        self.assertIn("<!doctype html>", alpha.lower())
        self.assertIn('charset="utf-8"', alpha.lower())
        self.assertTrue((site / "alpha-note.html").read_bytes().decode("utf-8"))

    def test_missing_input_fails_without_traceback(self) -> None:
        temporary = Path(self.enterContext(tempfile.TemporaryDirectory()))
        result = self.run_cli(temporary / "missing", temporary / "site")
        self.assertNotEqual(result.returncode, 0)
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

