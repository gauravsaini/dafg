import json
import pytest
from pathlib import Path
from dafg.init import scaffold_project


def test_scaffold_all(tmp_path: Path):
    ret = scaffold_project(target_dir=tmp_path, agents="all")
    assert ret == 0

    assert (tmp_path / "GATES.md").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".codex" / "hooks.json").exists()
    assert (tmp_path / ".cursor" / "rules" / "dafg.mdc").exists()
    assert (tmp_path / ".github" / "copilot-instructions.md").exists()

    claude_settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "Stop" in claude_settings["hooks"]

    codex_hooks = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    assert "Stop" in codex_hooks["hooks"]


def test_scaffold_subset(tmp_path: Path):
    ret = scaffold_project(target_dir=tmp_path, agents="claude,cursor")
    assert ret == 0

    assert (tmp_path / "GATES.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()
    assert (tmp_path / ".cursor" / "rules" / "dafg.mdc").exists()
    assert not (tmp_path / ".codex" / "hooks.json").exists()
    assert not (tmp_path / ".github" / "copilot-instructions.md").exists()


def test_scaffold_no_overwrite_without_force(tmp_path: Path):
    gates = tmp_path / "GATES.md"
    gates.write_text("# Custom Gates")
    
    ret = scaffold_project(target_dir=tmp_path, agents="all", force=False)
    assert ret == 0
    assert gates.read_text() == "# Custom Gates"

    ret_force = scaffold_project(target_dir=tmp_path, agents="all", force=True)
    assert ret_force == 0
    assert "Baseline environment" in gates.read_text()
