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


def test_interlock_templates_are_concrete(tmp_path: Path):
    """Interlock templates must carry concrete commands, not vague advice.

    Regression guard: the Copilot template was once three vague bullets with
    no workflow. Every agent template must name the exact gate commands.
    """
    from dafg.init import COPILOT_INSTRUCTIONS_TEMPLATE, CLAUDE_MD_TEMPLATE, AGENTS_MD_TEMPLATE

    required_commands = [
        "uv run gates --lint GATES.md",
        "uv run gates --approve GATES.md",
        "uv run gates --run GATES.md",
        "uv run stop-hook GATES.md --json",
    ]
    for name, template in [
        ("copilot", COPILOT_INSTRUCTIONS_TEMPLATE),
        ("claude", CLAUDE_MD_TEMPLATE),
        ("agents", AGENTS_MD_TEMPLATE),
    ]:
        for cmd in required_commands:
            assert cmd in template, f"{name} template missing concrete command: {cmd}"
        assert "ABANDON:" in template, f"{name} template missing gate-retraction rule"

    # scaffolded files carry the concrete templates
    ret = scaffold_project(target_dir=tmp_path, agents="copilot,claude")
    assert ret == 0
    copilot_text = (tmp_path / ".github" / "copilot-instructions.md").read_text()
    assert "uv run stop-hook GATES.md --json" in copilot_text
