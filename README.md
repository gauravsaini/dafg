# DAFG — Dynamic Autonomous Flow Graph

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/badge/package%20manager-uv-blueviolet)](https://github.com/astral-sh/uv)
[![Tests](https://img.shields.io/badge/tests-117%20passed-brightgreen.svg)]()
[![Zero Runtime Dependencies](https://img.shields.io/badge/dependencies-0%20runtime%20deps-success.svg)]()

**DAFG** is a Python-native agent coordination framework that enforces **grounded completion discipline**. It combines a dynamic task graph runtime with runnable acceptance gate ledgers (`GATES.md`), cryptographic approval security, evidence verification, and agent stop hook enforcement.

> Agents don't decide they're done. The gates decide.

---

## Table of Contents

- [Why DAFG?](#why-dafg)
- [Capability Overview](#capability-overview)
- [Key Features](#key-features)
- [Prerequisites & Installation](#prerequisites--installation)
- [Quick Start in 3 Minutes](#quick-start-in-3-minutes)
- [The Gate Ledger Contract (`GATES.md`)](#the-gate-ledger-contract-gatesmd)
- [CLI Reference](#cli-reference)
  - [`gates` (Ledger Runner & Linter)](#gates-ledger-runner--linter)
  - [`dafg run` (Task Graph Runtime)](#dafg-run-task-graph-runtime)
  - [`stop-hook` (Agent Completion Guard)](#stop-hook-agent-completion-guard)
- [Python API Usage](#python-api-usage)
  - [1. Programmatic Gate Execution](#1-programmatic-gate-execution)
  - [2. Dynamic Task Graph & Dependency Injection](#2-dynamic-task-graph--dependency-injection)
  - [3. Typed Schemas & Robust JSON Recovery](#3-typed-schemas--robust-json-recovery)
- [Integrating with AI Agents (Antigravity, Claude Code, Codex, Cursor)](#integrating-with-ai-agents)
- [Testing & Quality Assurance](#testing--quality-assurance)
- [Architecture & File Structure](#architecture--file-structure)

---

## Why DAFG?

Most multi-agent systems rely on **model self-certification**: an LLM worker does work, and the model (or another LLM) says *"Looks good to me!"* This creates false completions, undetected hallucinations, and premature exits.

DAFG enforces **grounded completion discipline**:

1. **Acceptance Ledgers First** — Work outcomes are declared in advance as runnable shell checks (`CHECK:`) with expected patterns (`EXPECT:`).
2. **Security Boundary** — Check commands cannot execute unless cryptographically approved (`.approved_gates.json`).
3. **Objective Verification** — A task node is **only** marked `ACCEPTED` when its assigned gates execute with exit code 0 and decisive output match.
4. **Stop Hook Enforcement** — Agents are blocked from finishing while any gates are pending, unmet, or unapproved.
5. **Zero Runtime Dependencies** — Built stdlib-first (Python 3.10+) for extreme portability and speed.

---

## Capability Overview

DAFG fuses two architectural planes into a single runtime:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                              DAFG                                      │
│                                                                        │
│   Execution & Coordination             Verification & Discipline       │
│   ─────────────────────────            ──────────────────────────       │
│   • Dynamic DAG Planning               • Acceptance Gate Ledger        │
│   • Prerequisite Expansion (needs)      • Cryptographic Approvals      │
│   • Wave Scheduler (Disjoint OWNS)      • Shell Check Evidence         │
│   • Persona Compiler & Router           • Ledger Linter & Reverify     │
│   • Budget Engine & State Persistence   • Stop Hook Completion Guard   │
│   • Bounded Persona Adaptation          • Honest Abandonment (ABANDON) │
└────────────────────────────────────────────────────────────────────────┘
```

### Capability Matrix

| Capability | DAFG |
|---|---|
| Autonomous agent loop | `DAFG.run()` with pluggable executor |
| Dynamic DAG & prerequisite spawning | `needs` + rolling waves |
| Capability-aware model routing | `AgentRouter` + `PolicyEngine` |
| Structured persona compilation | `PersonaProfile` + heuristic compiler |
| Node acceptance via objective evidence | Shell checks → `exit_code=0` + `EXPECT` match |
| Cryptographic approval boundary | `ApprovalStore` (SHA-256 per command) |
| Interruption & resume | Atomic `StateStore` + budget checkpoints |
| Agent stop discipline | `CompletionGuard` → `{"decision": "block"}` |
| Disjoint file ownership | `OWNS:` declarations prevent parallel conflicts |
| Bounded failure adaptation | `FailureClassifier` + `PersonaSwitcher` |

---

## Key Features

- **Runnable Gate Ledger Engine (`src/dafg/gates.py`)** — Parses and serializes markdown ledgers (`GATES.md`), preserving comments and layout.
- **Cryptographic Approval Store (`ApprovalStore`)** — Hashes command, expectation, working directory, and environment to prevent prompt injection and unauthorized script execution.
- **Ledger Linter (`GateLinter`)** — Catches empty titles, duplicate IDs, tautological or unfalsifiable checks, and missing tokens before execution.
- **Reverification (`--reverify`)** — Re-runs previously passed gates to detect regressions across child/parent task boundaries.
- **Dynamic Task Graph (`DAFG`)** — Dynamic planning, specialist role assignments, prerequisite expansion (`AgentResponse.needs`), and depth tree wave orchestration.
- **Disjoint File Ownership (`OWNS:`)** — Detects conflicting tasks and schedules non-conflicting tasks in parallel rolling waves.
- **Atomic State Persistence (`state.json`)** — Resumes interrupted or paused runs cleanly, preserving consumed budgets (`calls`, `nodes`, `revisions`, `deadline`).
- **Agent Stop Hook Guard (`src/dafg/hook.py`)** — Intercepts agent exit attempts and returns `{ "decision": "block" }` until every gate is verified with recorded evidence or validly abandoned (`ABANDON: <id> <reason>`).
- **Typed Schemas & JSON Repair (`src/dafg/schema.py`)** — Validates agent outputs with typed schemas and auto-repairs malformed JSON (code fences, trailing commas, Python booleans).

---

## Prerequisites & Installation

### 1. Prerequisites
- **Python**: `>= 3.10`
- **uv**: Fast Python package installer and runner ([Install uv](https://docs.astral.sh/uv/getting-started/installation/))

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or on macOS via Homebrew:
# brew install uv
```

### 2. Install Project Dependencies

Clone this repository and sync using `uv`:

```bash
cd dafg

# Create venv and sync all dependencies (pytest, etc.)
uv sync
```

### 3. (Optional) Install CLI Tools Globally or in Editable Mode

To install the commands (`dafg`, `gates`, `stop-hook`) into your current environment:

```bash
uv pip install -e .
```

---

## Quick Start in 3 Minutes

### Step 1: Create an Acceptance Gate Ledger (`GATES.md`)

Create a `GATES.md` file defining the verifiable outcomes of your task:

```markdown
# Acceptance Gates: User Profile Feature

- [ ] G1: User profile module imports cleanly
  CHECK: uv run python -c "import dafg; print('IMPORT_OK')"
  EXPECT: IMPORT_OK
  OWNS: src/profile.py
  EVIDENCE: pending

- [ ] G2: Profile unit tests pass
  CHECK: uv run pytest tests/test_profile.py -q
  EXPECT: 5 passed
  OWNS: src/profile.py, tests/test_profile.py
  EVIDENCE: pending
```

### Step 2: Lint the Ledger

Ensure the ledger has no syntax errors, duplicates, or missing expectations:

```bash
uv run gates --lint GATES.md
# Output: ✓ Ledger lint passed: 0 issues found.
```

### Step 3: Approve the Gate Commands

For security, runnable shell checks must be inspected and approved:

```bash
uv run gates --approve GATES.md
# Output: ✓ Approved 2 check command(s) in 'GATES.md' (saved to .approved_gates.json)
```

### Step 4: Run the DAFG Workflow

Execute the task graph. DAFG will load the gates, schedule tasks, execute workers, and record verification evidence:

```bash
uv run dafg run --gates GATES.md --state state.json
# Output:
# Initialized new DAFG with 2 tasks from GATES.md.
# DAFG run status: COMPLETED
```

### Step 5: Check Stop Hook Readiness

Verify that the agent stop hook approves completion:

```bash
uv run stop-hook GATES.md
# Output: ✓ STOP ALLOWED: All acceptance gates are met with evidence or validly abandoned.
```

---

## The Gate Ledger Contract (`GATES.md`)

Each gate in a markdown ledger uses the standard checklist item `- [ ] G<id>: <title>` followed by indented attributes:

```markdown
- [ ] G1: Descriptive title explaining what outcome is verified
  CHECK: command to execute (e.g. uv run pytest -q)
  EXPECT: decisive substring or regex that stdout/stderr must contain
  OWNS: file1.py, path/to/dir/* (declared file ownership)
  CWD: optional working directory (defaults to current dir)
  EVIDENCE: pending (updated automatically with exit_code, timestamp, and match)
```

### Passing Condition
A gate is considered **`[MET]`** if and only if:
1. The command was approved in `.approved_gates.json`.
2. The command process exited with code `0`.
3. The combined stdout/stderr matched `EXPECT:`.
4. Decisive evidence line is written: `EVIDENCE: exit_code=0 timestamp=... match='...'`.

### Abandoning a Gate Honestly
If a gate cannot be met due to a deliberate design change or impossible constraint, do not quietly delete it. Mark it with `ABANDON:`:
```markdown
- [x] G3: Optional Redis caching layer
  ABANDON: G3 Redis server dependency removed in favor of in-memory lru_cache
```

---

## CLI Reference

### `gates` (Ledger Runner & Linter)

```bash
# Check status of gates and view recorded evidence (dry-run, never executes)
uv run gates --status GATES.md

# Lint ledger for errors, tautologies, or invalid expectations
uv run gates --lint GATES.md

# Review and approve runnable checks
uv run gates --approve GATES.md

# Execute approved pending gates and record evidence
uv run gates --run GATES.md

# Re-run ALL runnable gates (including already-met gates) to prove freshness
uv run gates --reverify GATES.md
```

### `dafg run` (Task Graph Runtime)

```bash
# Run DAFG task graph with gates
uv run dafg run --gates GATES.md --state state.json

# Optional flags:
#   --state <file>            Path to state persistence JSON (default: state.json)
#   --gates <file>            Path to gate ledger markdown (default: GATES.md)
#   --approvals-file <file>   Path to approval store (default: .approved_gates.json)
#   --auto-approve            Auto-approve commands (useful in isolated CI/testing)
```

### `stop-hook` (Agent Completion Guard)

```bash
# Check if current ledger allows completion
uv run stop-hook GATES.md

# Output JSON decision for agent hooks / IDE harnesses:
uv run stop-hook GATES.md --json
```

**JSON Output Format**:
```json
{
  "allowed": true,
  "decision": "allow",
  "reason": "All acceptance gates are met with evidence or validly abandoned.",
  "pending_gates": [],
  "unapproved_gates": [],
  "unverified_gates": [],
  "abandoned_gates": [],
  "progress_guard_released": false
}
```

---

## Python API Usage

### 1. Programmatic Gate Execution

```python
from dafg import ApprovalStore, Gate, GateEngine, GateLedger

# 1. Parse or create a ledger
ledger = GateLedger.parse("""
# My Project Gates
- [ ] G1: Core module import check
  CHECK: python -c "import sys; sys.exit(0)"
  EXPECT: ""
  EVIDENCE: pending
""")

# 2. Setup approval store & engine
store = ApprovalStore(filepath=".approved_gates.json")
engine = GateEngine(approval_store=store, auto_approve=True)

# 3. Execute gate
gate = ledger.get_gate("G1")
result = engine.execute_gate(gate, ledger=ledger, reverify=True)

print(f"Gate status: {result.status}, Exit code: {result.exit_code}")
```

### 2. Dynamic Task Graph & Dependency Injection

```python
from dafg import DAFG, AgentResponse, TaskNode, NodeStatus

# Initialize graph
graph = DAFG(state_path="my_state.json")

# Add root node
node_a = TaskNode(id="T_DB", title="Setup Database Schema", owns=["src/db.py"])
graph.add_node(node_a)

# Dynamic prerequisite injection: worker returns prerequisite requests (`needs`)
def custom_executor(node, context):
    if node.id == "T_DB":
        return AgentResponse(
            output="DB completed",
            status="COMPLETED",
            # Dynamically request prerequisite tasks if missing
            needs=[TaskNode(id="T_MIGRATION", title="Run Initial Migration")]
        )
    return AgentResponse(output="Task completed", status="COMPLETED")

graph.run(executor_fn=custom_executor)
```

### 3. Typed Schemas & Robust JSON Recovery

```python
from dafg.schema import Schema, Field, ValidationError, parse_json_response

# 1. Define a strict response schema
class TaskPlanSchema(Schema):
    fields = {
        "task_name": Field(str, required=True),
        "priority": Field(int, min_value=1, max_value=5, default=3),
        "tags": Field(list, item_type=str, default=list),
    }

# 2. Extract and repair malformed LLM responses (markdown fences, trailing commas, Python literals)
raw_llm_text = """
Here is your plan:
```json
{
  "task_name": "Build Authentication",
  "priority": 1,
  "tags": ["security", "auth",],
}
```
Let me know if you need anything else!
"""

clean_data = parse_json_response(raw_llm_text)
validated = TaskPlanSchema().validate(clean_data)
print(validated)
# {'task_name': 'Build Authentication', 'priority': 1, 'tags': ['security', 'auth']}
```

---

## Integrating with AI Agents

DAFG ships with **drop-in configuration files** for four major AI coding platforms. Each platform automatically discovers and uses the gate workflow — no manual setup required.

| Platform | Instructions | Stop Hook | Discovery |
|---|---|---|---|
| **Antigravity** (`agy`) | `AGENTS.md` | Prompt-based | Auto-read at session start |
| **Claude Code** | `CLAUDE.md` | `.claude/settings.json` | Blocks completion on unmet gates |
| **OpenAI Codex** | `AGENTS.md` | `.codex/hooks.json` | Blocks completion on unmet gates |
| **Cursor** | `.cursor/rules/dafg.mdc` | Rule-based | Always-on for `*.py` and `*.md` |

### Google Antigravity (`agy` CLI)

The `AGENTS.md` file is read automatically at session start. You can also run non-interactively:

```bash
agy -p "Inspect GATES.md, approve the gates using 'uv run gates --approve GATES.md', \
  implement the requirements, and verify using 'uv run dafg run' and \
  'uv run stop-hook GATES.md'." \
  --model gemini-3.7-flash-high \
  --dangerously-skip-permissions
```

### Claude Code

Two files work together:

1. **`CLAUDE.md`** — project instructions read at session start
2. **`.claude/settings.json`** — registers the stop hook:

```json
{
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
```

When the agent attempts to finish, the hook inspects `GATES.md`. If any gate is pending or unverified, it returns `"decision": "block"` with the exact list of unmet gates, forcing the agent to stay in the build-test-debug loop until work is objectively proven.

### OpenAI Codex

The `.codex/hooks.json` file registers the same stop hook pattern. Enable hooks in your Codex config (`~/.codex/config.toml`):

```toml
[features]
codex_hooks = true
```

The `AGENTS.md` file provides project instructions that Codex reads automatically.

### Cursor

The `.cursor/rules/dafg.mdc` file is an always-on rule that provides the DAFG workflow instructions to Cursor. It activates automatically for all Python files and markdown files in the project.

---

## Testing & Quality Assurance

Run the comprehensive offline test suite with `pytest`:

```bash
uv run pytest -v
```

- **117/117 tests passing in ~1s**
- 100% offline (no external APIs or network calls required)
- Covers:
  - Markdown gate parsing, formatting preservation, and error recovery
  - Cryptographic approval hashing and tamper detection
  - Dynamic graph scheduling, cycle prevention, and prerequisite injection (`needs`)
  - Stop hook decision trees, progress guards, and abandonment rules
  - Typed schema validation, regex constraints, and JSON repair routines

---

## Architecture & File Structure

```text
dafg/
├── AGENTS.md                    # Agent instructions (Antigravity, Codex)
├── CLAUDE.md                    # Agent instructions (Claude Code)
├── GATES.md                     # Active acceptance gate ledger
├── pyproject.toml               # Packaging & script definitions (Hatchling + uv)
├── state.json                   # DAFG graph execution state (atomic checkpoint)
├── .approved_gates.json         # Cryptographic approval store for gate checks
├── dfag.py                      # Compatibility shim & quick runner
│
├── .claude/
│   └── settings.json            # Claude Code stop hook registration
│
├── .codex/
│   └── hooks.json               # OpenAI Codex stop hook registration
│
├── .cursor/rules/
│   └── dafg.mdc                 # Cursor always-on project rules
│
├── src/dafg/
│   ├── __init__.py              # Public API exports
│   ├── cli.py                   # Unified CLI dispatcher (dafg, gates, stop-hook)
│   ├── gates.py                 # GateLedger, ApprovalStore, GateEngine, GateLinter
│   ├── hook.py                  # CompletionGuard & stop hook evaluation logic
│   ├── persona.py               # PersonaCompiler, AgentRouter, PolicyEngine
│   ├── runtime.py               # DAFG task graph, TaskNode, Budget, rolling waves
│   └── schema.py                # Typed Schema, Field validators, robust JSON repair
│
└── tests/
    ├── test_dafg_budgets.py     # Budget caps and deadline tests
    ├── test_dafg_persistence.py # State persistence and resume tests
    ├── test_dafg_runtime.py     # Dynamic graph scheduling and execution tests
    ├── test_depth_tree_waves.py # Depth tree and wave scheduling tests
    ├── test_gates_execution.py  # Gate execution and reverification tests
    ├── test_gates_linter.py     # Ledger linter tests
    ├── test_gates_parser.py     # Markdown ledger parser tests
    ├── test_gates_security.py   # Approval store and security boundary tests
    ├── test_persona.py          # Persona compilation and routing tests
    ├── test_schema.py           # Typed schemas and JSON repair tests
    └── test_stop_hook.py        # Stop hook completion guard tests
```

---

## License

MIT License. Designed for deterministic agent coordination and rigorous completion discipline.
