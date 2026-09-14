#!/usr/bin/env python3
"""Enforce SPEC B.6 r14 on core-loop refusals, bounds and web gates."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from pathlib import Path

CORE = tuple(
    f"src/harness/{name}.py"
    for name in (
        "agent_runtime",
        "run_loop",
        "pydantic_harness_adapter",
        "envelope",
        "transcript",
        "agent",
        "memory_gate",
        "toolset_runtime",
        "memory_bridge",
        "spine_client",
        "progressive_prompt",
    )
)
CITATION = re.compile(r"\b(?:(?:WALL|INCIDENT)\s+\S+|F\d{3}\b|A-\d{3}\b|D\.2\s+\d+\b)")
BOUNDS = {"gt", "ge", "lt", "le", "min_length", "max_length", "pattern"}


def literals(node: ast.AST) -> list[str]:
    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def check_python(root: Path) -> list[str]:
    quoted = []
    for path in (root / "tests").rglob("*.py"):
        tree = ast.parse(path.read_text())
        quoted.extend(" ".join(value.split()) for value in literals(tree))
    errors = []
    for relative in CORE:
        path = root / relative
        source = path.read_text()
        lines = source.splitlines()
        tree = ast.parse(source)
        parents = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            refusal = isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
            assertion = isinstance(node, ast.Assert)
            bounded = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Field"
                and any(k.arg in BOUNDS for k in node.keywords)
            )
            if not (refusal or assertion or bounded):
                continue
            # A declaration's comment precedes the assignment, including multiline Field calls.
            site = node
            if bounded:
                while site in parents and not isinstance(site, (ast.Assign, ast.AnnAssign)):
                    site = parents[site]
            nearby = lines[max(0, site.lineno - 2) : site.lineno]
            if bounded:
                nearby += lines[node.lineno - 1 : node.end_lineno]
            parent = parents.get(node)
            if refusal and isinstance(parent, ast.If):
                nearby += lines[max(0, parent.lineno - 2) : parent.lineno]
            if not any("#" in line and CITATION.search(line.split("#", 1)[1]) for line in nearby):
                errors.append(
                    f"{relative}:{site.lineno}: guard lacks adjacent WALL/incident citation"
                )
            if refusal:
                # Typed exceptions forwarding a response have no local message to duplicate.
                messages = [
                    arg for arg in node.exc.args if isinstance(arg, (ast.Constant, ast.JoinedStr))
                ]
                for message in messages:
                    fragments = [s for s in literals(message) if s.strip()]
                    for fragment in fragments:
                        fragment = " ".join(fragment.split())
                        if not any(
                            fragment in text or re.escape(fragment) in text for text in quoted
                        ):
                            errors.append(
                                f"{relative}:{node.lineno}: message unquoted by tests: {fragment!r}"
                            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--python-only", action="store_true")
    args = parser.parse_args()
    errors = check_python(args.root)
    for error in errors:
        print(error)
    web = (
        0
        if args.python_only
        else subprocess.run(
            ["node", str(args.root / "scripts/check_guard_citations.mjs"), str(args.root)],
            check=False,
        ).returncode
    )
    print(f"Guard citations: {'FAIL' if errors or web else 'PASS'}")
    return int(bool(errors or web))


if __name__ == "__main__":
    raise SystemExit(main())
