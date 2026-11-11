"""M7LF: scoped verdicts and hashed evidence in each repository's own coverage report."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path("/Users/nateoswalt/relay/m7lf")
GARDEN = ROOT / "garden/verification/m7lf"
OBSERVED = {
    "FL-210": (
        "PASS three fresh Linux bundle runs (18:21–18:25Z, 2026-11-11), each on real "
        "OpenRouter gpt-4.1-mini with the local Palace rung under F214. From the Jobs module, "
        "Run now starts the saved bundle; its agent uses bash to create shell.txt inside its "
        "location, calls the sealed forecast tool, writes its actual output, then receives "
        "Read-only file system for the outside write and Permission denied for the vault read. "
        "The fenced exit passes on both the manual and unattended cron run each time. "
        "The ten-rule real-OS table passes on macOS and Linux, including TCP and pathname "
        "Unix sockets (denied by default, allowed with remote), symlinks, scratch and vault "
        "denial with remote, credentials and workspace grants. Doctor receipts show a usable, "
        "missing and deliberately failing fence with remedies. Docker requested --privileged; "
        "the inner shell unshares user/mount/PID/network namespaces, drops all capabilities, "
        "disables nested user namespaces and loads its socket filter without remote. "
        "Images viewed: all three run-N/FL-210.png and FL-185-detail.png; raw tool events "
        "and walk receipts are beside them. macOS retains its Seatbelt profile."
    ),
    "FL-209": (
        "PASS as a Linux neighbour, three fresh bundle runs and three fresh grant pairs. "
        "In run-1/2/3 the agent's plain nocturne tool run forecast Austin executes the saved "
        "tool outside the network fence; the fixture accepts its key and the actual report "
        "lands in forecast.md. No fixture key enters transcripts or captures' page text. "
        "In run-g1/g2/g3, an undeclared curl parks waiting with no request; n at jobs save "
        "saves nothing; --yes confirms remote once and the run fetches the notice, writes "
        "it inside the fence and passes its exit without a card. The Jobs detail names "
        "Crosses unattended remote. All three detail captures were viewed. The bundle "
        "digest/sealing and read-tool rules are inherited from M7WB, not rebuilt."
    ),
    "FL-185": (
        "PASS for its local managed-agent half on Linux, three fresh bundle jobs. Each "
        "manual run is followed by a cron-triggered run with nobody steering; both use the "
        "sealed tool with its key and pass the fenced exit. Each Jobs detail shows two "
        "completed runs, digest, tool summary and key NAME only. All three FL-185-detail "
        "captures were viewed. The row remains partial: remote target push/promote is M7TG."
    ),
}
CONTEXT = (
    "Context only under F086, not a new regression verdict: this row maps a shared adapter, "
    "onboarding, test or package path touched for F217. Its own full gesture was not repeated. "
    "Only FL-210, FL-209 and FL-185 are charged; those have three fresh Linux walks. "
    "In particular, the Linux shell's vault corner passed, but FL-208's full archive/database "
    "secrecy walk was not repeated. The image is the final Linux Jobs detail, viewed before "
    "the scoped verdict. No existing row is promoted from this context-only capture."
)


def hashes(folder):
    lines = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.name not in {"SHA256SUMS", "impacted.json"}:
            lines.append(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(folder)}"
            )
    (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def reason(path):
    if "/verification/m7lf/" in path or path in {"garden/BOARD.md", "garden/reports/306-M7LF.md"}:
        return "M7LF's own evidence, coverage, handoff or coordination record; no feature behavior."
    if path.endswith("/.github/workflows/ci.yml"):
        return (
            "PLAN M7LF explicitly grants the same shell-rule tests on Linux CI; "
            "no other CI behavior changes."
        )
    if path.endswith(("docs/feature-ledger.yaml", "docs/frozen-law.json")):
        return (
            "Frozen FL-210 and its recorded walks, refreshed only on M7LF branches "
            "under the owner's instruction."
        )
    if path in {
        "garden/notes/feature-ledger.yaml",
        "garden/notes/feature-ledger.md",
        "garden/FLAGS.md",
        "garden/notes/dormant-ideas.md",
    }:
        return (
            "FL-210, Linux neighbour walk records and F217's dated resolution; no other behavior."
        )
    if path.endswith(
        ("/__init__.py", "/openapi.json", "/tests/test_packaging.py", "/pyproject.toml")
    ):
        return (
            "Package pair 0.1.92 and generated package metadata only; "
            "Memory API contract remains 0.1.92."
        )
    if path.endswith("/DECISIONS.md"):
        return "Required P4.2 implementation journal for F217; no feature behavior."
    if "/tests/" in path:
        return (
            "Real-fence regression expectations for F217 and the cross-host rule table, "
            "covered by FL-210."
        )
    raise ValueError(f"Unreviewed impact path: {path}")


def main():
    ranges = {
        repo: subprocess.check_output(
            ["git", "-C", str(ROOT / repo), "rev-parse", "HEAD"], text=True
        ).strip()
        for repo in ("harness", "spine")
    }
    for repo in ("garden", "harness", "spine"):
        folder = ROOT / repo / "verification/m7lf"
        folder.mkdir(parents=True, exist_ok=True)
        diffs = [
            f"{r}=origin/main..{sha}" for r, sha in ranges.items() if repo == "garden" or repo == r
        ]
        args = ["python3", "bin/ledger", "report", "M7LF"]
        for diff in diffs:
            args.extend(("--diff", diff))
        data = json.loads(subprocess.check_output(args, cwd=ROOT / repo, text=True))
        for row_id, row in data["rows"].items():
            image = GARDEN / "run-3/FL-210.png"
            if row_id == "FL-185":
                image = GARDEN / "run-3/FL-185-detail.png"
            elif row_id == "FL-209":
                image = GARDEN / "run-g3/FL-209-detail.png"
            row.update(
                verdict="PASS" if row_id in OBSERVED else "FAIL",
                flag="" if row_id in OBSERVED else "F086",
                screenshot=f"{row_id}.png",
                observed=OBSERVED.get(row_id, CONTEXT),
            )
            shutil.copyfile(image, folder / f"{row_id}.png")
        for path in data["unmapped"]:
            data["unmapped"][path] = reason(path)
        for name in ("garden", "harness", "spine"):
            if repo != "garden" and repo != name:
                continue
            for path in (ROOT / name / "verification/m7lf").rglob("*"):
                if path.is_file():
                    key = f"{name}/{path.relative_to(ROOT / name)}"
                    data["unmapped"][key] = reason(key)
        data["unmapped"][f"{repo}/verification/m7lf/ledger-report.json"] = reason(
            f"{repo}/verification/m7lf/ledger-report.json"
        )
        if repo == "garden":
            for path in (
                "garden/BOARD.md",
                "garden/FLAGS.md",
                "garden/reports/306-M7LF.md",
                "garden/notes/feature-ledger.yaml",
                "garden/notes/feature-ledger.md",
                "garden/notes/dormant-ideas.md",
            ):
                data["unmapped"][path] = reason(path)
        (folder / "ledger-report.json").write_text(json.dumps(data, indent=2) + "\n")
        hashes(folder)
        print(
            repo, "rows", len(data["rows"]), "charged PASS", len(set(data["rows"]) & set(OBSERVED))
        )


if __name__ == "__main__":
    main()
