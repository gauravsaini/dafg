# DAFG — Agent Instructions

> This file is read automatically by Antigravity (`agy`), Codex, and other agents
> that support `AGENTS.md`. It describes how to work with this project.

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

## Core Workflow

Every task in this project follows the **gate-driven workflow**:

### 1. Author Gates (`GATES.md`)

Before implementing, define verifiable outcomes in `GATES.md`:

```markdown
- [ ] G1: Module imports cleanly
  CHECK: uv run python -c "import dafg; print('OK')"
  EXPECT: OK
  OWNS: src/dafg/module.py
  EVIDENCE: pending
```

### 2. Lint the Ledger

```bash
uv run gates --lint GATES.md
```

### 3. Approve Gate Commands

```bash
uv run gates --approve GATES.md
```

### 4. Implement & Run

```bash
uv run dafg run --gates GATES.md --state state.json
```

### 5. Verify Stop Readiness

```bash
uv run stop-hook GATES.md --json
```

The stop hook returns `{"decision": "block"}` while any gate is pending,
unverified, or unapproved. Only when all gates are `MET` with recorded evidence
(or validly `ABANDON`ed) does it return `{"decision": "allow"}`.

## Rules

1. **Always use `uv`** to run Python, pytest, and CLI commands.
2. **Never delete a gate** — use `ABANDON: <id> <reason>` instead.
3. **Never mark a gate as met** without running its `CHECK:` command and
   confirming `EXPECT:` matches.
4. **Gate commands must be approved** before execution — run
   `uv run gates --approve GATES.md` first.
5. **Zero runtime dependencies** — use the Python standard library. Do not add
   packages to `[project.dependencies]`.
6. **Atomic state** — the runtime persists to `state.json` atomically. Do not
   manually edit it.

## Running Tests

```bash
uv run pytest -q
```

All 425 tests pass in ~7s, 100% offline.

## CLI Entry Points

| Command | Description |
|---|---|
| `uv run dafg run` | Run DAFG task graph |
| `uv run dafg organism --goal "<goal>"` | Autonomous reactive & self-improving execution organism |
| `uv run gates --status GATES.md` | Show gate status |
| `uv run gates --lint GATES.md` | Lint gate ledger |
| `uv run gates --approve GATES.md` | Approve gate commands |
| `uv run gates --run GATES.md` | Execute pending gates |
| `uv run gates --reverify GATES.md` | Re-run all gates |
| `uv run stop-hook GATES.md` | Check completion readiness |
| `uv run stop-hook GATES.md --json` | JSON completion decision |

## File Ownership

Tasks declare file ownership via `OWNS:` in gates. The runtime prevents
parallel execution of tasks with overlapping ownership. Respect these boundaries
when making changes.
