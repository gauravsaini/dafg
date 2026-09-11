# DAFG — Claude Code Instructions

> This file is read automatically by Claude Code at session start.
> It describes how to work with this project.

## Project Overview

**DAFG** (Dynamic Autonomous Flow Graph) is a Python-native agent coordination
and completion-discipline framework. It combines a dynamic task graph runtime
with runnable acceptance gate ledgers (`GATES.md`), cryptographic approval
security, and agent stop hook enforcement.

## Tech Stack & Constraints

- **Language**: Python 3.10+
- **Package Manager**: Always use `uv` — never `pip` or `pip install` directly
- **Runtime Dependencies**: Zero (stdlib only)
- **Dev Dependencies**: `pytest>=8.0.0`
- **Build Backend**: Hatchling

## Stop Hook Integration

This project configures a **Stop hook** in `.claude/settings.json`. When you
attempt to finish, the hook runs:

```bash
uv run stop-hook GATES.md --json
```

If any gate in `GATES.md` is pending, unverified, or unapproved, the hook
returns `{"decision": "block"}` and you must continue working. Only when all
gates are `MET` with recorded evidence (or validly `ABANDON`ed) does it return
`{"decision": "allow"}`.

## Core Workflow

### 1. Author Gates (`GATES.md`)

Before implementing, define verifiable outcomes:

```markdown
- [ ] G1: Module imports cleanly
  CHECK: uv run python -c "import dafg; print('OK')"
  EXPECT: OK
  OWNS: src/dafg/module.py
  EVIDENCE: pending
```

### 2. Lint → Approve → Implement → Verify

```bash
uv run gates --lint GATES.md        # Catch errors early
uv run gates --approve GATES.md     # Approve commands for execution
# ... implement ...
uv run dafg run --gates GATES.md    # Run task graph
uv run stop-hook GATES.md --json    # Check completion readiness
```

## Rules

1. **Always use `uv`** to run Python, pytest, and CLI commands.
2. **Never delete a gate** — use `ABANDON: <id> <reason>` instead.
3. **Never mark a gate as met** without running its `CHECK:` command and
   confirming `EXPECT:` matches.
4. **Gate commands must be approved** before execution.
5. **Zero runtime dependencies** — use the Python standard library only.
6. **Atomic state** — do not manually edit `state.json`.

## Running Tests

```bash
uv run pytest -q    # 117 tests, ~1s, 100% offline
```

## CLI Entry Points

| Command | Description |
|---|---|
| `uv run dafg run` | Run DAFG task graph |
| `uv run gates --status GATES.md` | Show gate status |
| `uv run gates --lint GATES.md` | Lint gate ledger |
| `uv run gates --approve GATES.md` | Approve gate commands |
| `uv run gates --run GATES.md` | Execute pending gates |
| `uv run gates --reverify GATES.md` | Re-run all gates |
| `uv run stop-hook GATES.md` | Check completion readiness |
| `uv run stop-hook GATES.md --json` | JSON completion decision |
