"""Run the standing rendered UI canon against one isolated data-bearing fixture.

PLAN M2ST4 and SPEC B.6 require the owner findings to run locally and in clean-room CI.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONS = (
    (
        "m2st4",
        "verification.m2st4.scenario_app:create_scenario_app",
        "M2ST4 REGRESSION",
        (
            ("fixture-curtain", "verification/m3fx/browser_check.mjs"),
            ("sweep-v2", "verification/m2ux1/browser_check.mjs"),
            ("stage", "verification/m2st1/browser_check.mjs"),
            ("controls", "verification/m2st2/browser_check.mjs"),
            ("human-numbers", "verification/m2st3/browser_check.mjs"),
        ),
    ),
    (
        "sym13",
        "verification.sym13.scenario_app:create_scenario_app",
        "SYM13 REGRESSION",
        (
            ("fixture-curtain", "verification/m3fx/browser_check.mjs"),
            ("recipe-grid", "verification/sym13/browser_check.mjs"),
        ),
    ),
)


def main() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in ("src", ".", environment.get("PYTHONPATH", "")) if part
    )

    with tempfile.TemporaryDirectory(prefix="nocturne-m2st4-canon-") as temporary:
        output_root = Path(temporary)
        for canon_name, fixture_path, fixture_identity, suites in CANONS:
            _run_canon(
                output_root / canon_name,
                fixture_path,
                fixture_identity,
                suites,
                environment,
            )

    print(
        "UI canon PASS: fixture curtain, sweep v2, live controls, "
        "human numbers, Stage, and SYM13 recipe"
    )


def _run_canon(
    output_root: Path,
    fixture_path: str,
    fixture_identity: str,
    suites: tuple[tuple[str, str], ...],
    base_environment: dict[str, str],
) -> None:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = base_environment.copy()
    environment["NOCTURNE_HOME"] = str(output_root / "nocturne-home")
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "fixture.log"
    with log_path.open("w", encoding="utf-8") as fixture_log:
        fixture = subprocess.Popen(
            [
                _fixture_python(),
                "-m",
                "verification.run_fixture",
                fixture_path,
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=environment,
            stdout=fixture_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_for_fixture(base_url, fixture, fixture_identity)
            for name, script in suites:
                evidence_dir = output_root / name
                subprocess.run(
                    [
                        "node",
                        script,
                        "--base-url",
                        base_url,
                        "--fixture",
                        fixture_identity,
                        "--evidence-dir",
                        str(evidence_dir),
                    ],
                    cwd=ROOT,
                    env=environment,
                    check=True,
                )
        except BaseException:
            fixture_log.flush()
            print(log_path.read_text(encoding="utf-8"), file=sys.stderr)
            raise
        finally:
            fixture.terminate()
            try:
                fixture.wait(timeout=10)
            except subprocess.TimeoutExpired:
                fixture.kill()
                fixture.wait(timeout=5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _fixture_python() -> str:
    managed = ROOT / ".venv" / "bin" / "python"
    return str(managed) if managed.is_file() else sys.executable


def _wait_for_fixture(base_url: str, process: subprocess.Popen[str], fixture_identity: str) -> None:
    identity_url = (
        f"{base_url}/__scenario__/identity?fixture={urllib.parse.quote(fixture_identity)}"
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"fixture exited before readiness with status {process.returncode}")
        try:
            with urllib.request.urlopen(identity_url, timeout=1) as response:
                payload = json.load(response)
            if payload == {"fixture": fixture_identity, "deterministic": True}:
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.1)
    raise TimeoutError("M2ST4 fixture did not become ready within 20 seconds")


if __name__ == "__main__":
    main()
