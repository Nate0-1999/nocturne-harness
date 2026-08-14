"""M2MI agent-file jump-start discovery regressions."""

from pathlib import Path

from harness.seed_identity import seed_batch_uid
from harness.seed_jump_start import discover_agent_files


def test_agent_file_discovery_offers_bounded_workspace_markdown_without_ingesting_it(
    tmp_path: Path,
) -> None:
    """PLAN M2MI/P1.5 offers agent files without creating a second write path."""

    (tmp_path / "AGENTS.md").write_text("# Root rules\n\nKeep owner consent.\n", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()
    (package / "CLAUDE.md").write_text(
        "# Package rules\n\nPreserve provenance.\n", encoding="utf-8"
    )
    ignored = tmp_path / ".venv"
    ignored.mkdir()
    (ignored / "AGENTS.md").write_text("# Dependency rules\n", encoding="utf-8")
    (package / "notes.md").write_text("# Not an agent file\n", encoding="utf-8")

    result = discover_agent_files(tmp_path)

    assert result.truncated is False
    assert [offer.relative_path for offer in result.files] == ["AGENTS.md", "package/CLAUDE.md"]
    assert result.files[0].batch_uid == seed_batch_uid(
        "AGENTS.md", "# Root rules\n\nKeep owner consent.\n"
    )
    assert result.files[0].markdown == "# Root rules\n\nKeep owner consent.\n"


def test_agent_file_discovery_deduplicates_identical_named_documents(tmp_path: Path) -> None:
    """P1.5 keeps the jump-start offer quiet when nested agent files are exact copies."""

    markdown = "# Shared rules\n\nNothing auto-admits.\n"
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    (tmp_path / "one" / "AGENTS.md").write_text(markdown, encoding="utf-8")
    (tmp_path / "two" / "AGENTS.md").write_text(markdown, encoding="utf-8")

    result = discover_agent_files(tmp_path)

    assert [offer.relative_path for offer in result.files] == ["one/AGENTS.md"]
