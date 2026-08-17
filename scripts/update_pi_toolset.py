"""Mechanically update and verify Nocturne's exact PI dependency receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src" / "harness" / "_pi"
PACKAGE = "@earendil-works/pi-coding-agent"
REPOSITORY = "https://github.com/earendil-works/pi"
LEGACY_REPOSITORY = "https://github.com/badlogic/pi-mono"


def _run(*args: str) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=None,
    )
    return result.stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _metadata(version: str) -> dict[str, Any]:
    raw = _run(
        "npm",
        "view",
        f"{PACKAGE}@{version}",
        "version",
        "gitHead",
        "dist.integrity",
        "dist.shasum",
        "dist.tarball",
        "repository.url",
        "license",
        "engines.node",
        "--json",
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("npm returned non-object package metadata")
    return value


def _publishers() -> list[str]:
    return sorted(line for line in _run("npm", "owner", "ls", PACKAGE).splitlines() if line)


def _tag_commit(version: str) -> str:
    tag = f"refs/tags/v{version}"
    lines = _run("git", "ls-remote", f"{REPOSITORY}.git", tag, f"{tag}^{{}}").splitlines()
    candidates = [line.split()[0] for line in lines if line.strip()]
    if not candidates:
        raise RuntimeError(f"canonical upstream has no v{version} tag")
    return candidates[-1]


def _license(version: str) -> bytes:
    url = f"https://raw.githubusercontent.com/earendil-works/pi/v{version}/LICENSE"
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read()


def update(version: str) -> None:
    if re.fullmatch(r"0\.[0-9]+\.[0-9]+", version) is None:
        raise ValueError("PI version must be an exact 0.MINOR.PATCH release")

    existing = json.loads((RUNTIME / "dependency.json").read_text(encoding="utf-8"))
    publishers = _publishers()
    if publishers != existing["publishers"]:
        raise RuntimeError("PI npm publisher custody changed; owner review is required")

    metadata = _metadata(version)
    repository = str(metadata.get("repository.url", "")).removesuffix(".git")
    if repository not in {REPOSITORY, f"git+{REPOSITORY}"}:
        raise RuntimeError(f"PI npm package points at unexpected repository {repository!r}")
    if metadata.get("version") != version:
        raise RuntimeError("npm resolved a different PI version")
    if metadata.get("license") != "MIT":
        raise RuntimeError("PI npm package is no longer MIT")
    git_head = metadata.get("gitHead")
    tag_commit = _tag_commit(version)
    if not isinstance(git_head, str) or git_head != tag_commit:
        raise RuntimeError("PI npm gitHead does not match the canonical release tag")

    license_bytes = _license(version)
    license_sha256 = hashlib.sha256(license_bytes).hexdigest()
    node_engine = metadata.get("engines.node")
    if not isinstance(node_engine, str) or not node_engine:
        raise RuntimeError("PI npm package has no Node engine boundary")

    package_json = {
        "name": "nocturne-pi-toolset-runtime",
        "version": "0.0.0",
        "private": True,
        "engines": {"node": node_engine},
        "dependencies": {PACKAGE: version},
    }
    receipt = {
        "schema_version": 1,
        "package": PACKAGE,
        "version": version,
        "source_repository": REPOSITORY,
        "legacy_repository_redirect": LEGACY_REPOSITORY,
        "source_tag": f"v{version}",
        "source_commit": tag_commit,
        "npm_git_head": git_head,
        "artifact_integrity": metadata["dist.integrity"],
        "artifact_shasum": metadata["dist.shasum"],
        "artifact_tarball": metadata["dist.tarball"],
        "license": "MIT",
        "license_file": "LICENSE.upstream",
        "license_sha256": license_sha256,
        "node_engine": node_engine,
        "publishers": publishers,
    }
    _write_json(RUNTIME / "package.json", package_json)
    _write_json(RUNTIME / "dependency.json", receipt)
    (RUNTIME / "LICENSE.upstream").write_bytes(license_bytes)

    _run(
        "npm",
        "install",
        "--package-lock-only",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        "--save-exact",
        "--prefix",
        str(RUNTIME),
        f"{PACKAGE}@{version}",
    )
    _run(
        "npm",
        "ci",
        "--ignore-scripts",
        "--no-audit",
        "--no-fund",
        "--prefix",
        str(RUNTIME),
    )
    _run(sys.executable, "scripts/pi_toolset_smoke.py")
    _run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/golden",
        "tests/test_pi_toolset.py",
    )
    print(f"PI {version} receipt, install, RPC smoke, seam tests, and goldens passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="exact PI version, for example 0.84.2")
    args = parser.parse_args()
    update(args.version)


if __name__ == "__main__":
    main()
