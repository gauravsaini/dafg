"""Project initialization and agent interlock scaffolding for DAFG."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


AGENTS_MD_TEMPLATE = """# Acceptance Gate Protocol & Instructions

This repository enforces **grounded completion discipline** via DAFG.
You cannot declare completion based on conversational self-reports. Work is only complete when all acceptance gates in `GATES.md` are objectively verified with machine evidence.

## Core Workflow

1. **Review or Author Gates**: Check `GATES.md`. If new capabilities or bugfixes are requested, define verifiable outcomes before coding:
   ```markdown
   - [ ] G1: Description of verifiable outcome
     CHECK: command to run
     EXPECT: regex pattern matching stdout/stderr
     OWNS: src/modified_file.py
   ```
2. **Lint the Ledger**:
   ```bash
   uv run gates --lint GATES.md
   ```
3. **Approve Gate Commands**:
   ```bash
   uv run gates --approve GATES.md
   ```
4. **Implement & Execute**:
   Write the code and verify gates:
   ```bash
   uv run gates --run GATES.md
   ```
5. **Verify Stop Readiness**:
   ```bash
   uv run stop-hook GATES.md --json
   ```
   If any gate is pending or unverified, StopHook returns `{"decision": "block"}`. You MUST remain in the loop and fix the failures until StopHook returns `{"decision": "allow"}`.

## Rules
- Never delete a gate; use `ABANDON: <id> <reason>` if a requirement is legitimately retracted.
- Never mark a gate as met manually without running its `CHECK:` command and verifying its `EXPECT:` output.
- All gate commands must be approved with `uv run gates --approve GATES.md` before execution.
"""

CLAUDE_MD_TEMPLATE = """# Claude Code Project Guidelines

This project uses **DAFG** (Dynamic Autonomous Flow Graph) for objective completion verification.
A StopHook is registered in `.claude/settings.json` that will automatically intercept and block exit attempts if any gate in `GATES.md` is unmet or unverified. You cannot declare completion based on conversational self-reports.

## Required Workflow
1. Declare verifiable acceptance criteria in `GATES.md` before coding:
   ```markdown
   - [ ] G1: Description of verifiable outcome
     CHECK: command to run
     EXPECT: regex pattern matching stdout/stderr
     OWNS: src/modified_file.py
   ```
2. Lint the ledger: `uv run gates --lint GATES.md`.
3. Approve check commands: `uv run gates --approve GATES.md`.
4. Implement your changes.
5. Verify gates: `uv run gates --run GATES.md`.
6. Check stop readiness: `uv run stop-hook GATES.md --json`.
Do not attempt to complete the session while gates are unverified. If the decision is `block`, remain in the loop and fix the failures.

## Rules
- Never delete a gate; use `ABANDON: <id> <reason>` if a requirement is legitimately retracted.
- Never mark a gate as met manually without running its `CHECK:` command and verifying its `EXPECT:` output.
"""

COPILOT_INSTRUCTIONS_TEMPLATE = """# GitHub Copilot Instructions

This project enforces **grounded completion discipline** via DAFG.
You cannot declare a task complete based on conversational self-reports. Work is only complete when all acceptance gates in `GATES.md` are objectively verified with machine evidence.

## Core Workflow

1. **Review or Author Gates**: Check `GATES.md`. If new capabilities or bugfixes are requested, define verifiable outcomes before coding:
   ```markdown
   - [ ] G1: Description of verifiable outcome
     CHECK: command to run
     EXPECT: regex pattern matching stdout/stderr
     OWNS: src/modified_file.py
   ```
2. **Lint the Ledger**:
   ```bash
   uv run gates --lint GATES.md
   ```
3. **Approve Gate Commands**:
   ```bash
   uv run gates --approve GATES.md
   ```
4. **Implement & Execute**: Write the code, then verify:
   ```bash
   uv run gates --run GATES.md
   ```
5. **Verify Stop Readiness**:
   ```bash
   uv run stop-hook GATES.md --json
   ```
   If the decision is `block`, you MUST remain in the loop and fix the failures. Completion is only valid when the decision is `allow`.

## Rules
- Never delete a gate; use `ABANDON: <id> <reason>` if a requirement is legitimately retracted.
- Never mark a gate as met manually without running its `CHECK:` command and verifying its `EXPECT:` output.
- All gate commands must be approved with `uv run gates --approve GATES.md` before execution.
"""

CURSOR_RULE_TEMPLATE = """---
description: DAFG Completion Discipline & Gate Ledger Rules
globs: ["*"]
alwaysApply: true
---

# DAFG Rules

- This repository uses `GATES.md` for objective verification.
- Always run `uv run gates --lint GATES.md` to ensure ledger validity.
- Always run `uv run gates --approve GATES.md` when check commands change.
- When implementing features or fixes, verify them using `uv run gates --run GATES.md`.
- Completion is only valid when `uv run stop-hook GATES.md --json` returns `{"decision": "allow"}`.
"""

GATES_MD_TEMPLATE = """# Project Acceptance Gates

- [ ] G1: Baseline environment and unit test verification
  CHECK: uv run python -c "print('OK')"
  EXPECT: OK
  OWNS: src/
  EVIDENCE: pending
"""

CLAUDE_SETTINGS_TEMPLATE = {
    "hooks": {
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "uv run stop-hook GATES.md --json"
                    }
                ]
            }
        ]
    }
}

CODEX_HOOKS_TEMPLATE = {
    "hooks": {
        "Stop": [
            {
                "type": "command",
                "command": "uv run stop-hook GATES.md --json"
            }
        ]
    }
}


def scaffold_project(
    target_dir: Optional[Path] = None,
    agents: str = "all",
    force: bool = False,
) -> int:
    """Scaffold DAFG ledger and agent hook configuration files in the target directory."""
    root = Path(target_dir) if target_dir else Path.cwd()
    selected = [a.strip().lower() for a in agents.split(",") if a.strip()]
    install_all = "all" in selected

    created: List[str] = []
    skipped: List[str] = []

    def _write(rel_path: str, content: str) -> None:
        dest = root / rel_path
        if dest.exists() and not force:
            skipped.append(rel_path)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        created.append(rel_path)

    # 1. Base Gate Ledger
    _write("GATES.md", GATES_MD_TEMPLATE)

    # 2. Antigravity / Generic Agent Instructions
    if install_all or "antigravity" in selected or "agents" in selected:
        _write("AGENTS.md", AGENTS_MD_TEMPLATE)

    # 3. Claude Code Instructions & StopHook
    if install_all or "claude" in selected:
        _write("CLAUDE.md", CLAUDE_MD_TEMPLATE)
        _write(".claude/settings.json", json.dumps(CLAUDE_SETTINGS_TEMPLATE, indent=2) + "\n")

    # 4. OpenAI Codex Instructions & StopHook
    if install_all or "codex" in selected:
        if "AGENTS.md" not in created and "AGENTS.md" not in skipped:
            _write("AGENTS.md", AGENTS_MD_TEMPLATE)
        _write(".codex/hooks.json", json.dumps(CODEX_HOOKS_TEMPLATE, indent=2) + "\n")

    # 5. Cursor Rules
    if install_all or "cursor" in selected:
        _write(".cursor/rules/dafg.mdc", CURSOR_RULE_TEMPLATE)

    # 6. GitHub Copilot Instructions
    if install_all or "copilot" in selected:
        _write(".github/copilot-instructions.md", COPILOT_INSTRUCTIONS_TEMPLATE)

    # Report results
    print("=" * 60)
    print("DAFG PROJECT & AGENT INTERLOCK INITIALIZATION")
    print("=" * 60)
    for p in created:
        print(f"  ✓ Created: {p}")
    for p in skipped:
        print(f"  - Skipped (already exists): {p} (use --force to overwrite)")
    print("=" * 60)
    print("Next steps:")
    print("  1. Edit GATES.md to define your project's verifiable acceptance gates.")
    print("  2. Approve the gate commands: uv run gates --approve GATES.md")
    print("  3. Your AI agents are now constrained by the DAFG StopHook boundary.")
    print("=" * 60)
    return 0
