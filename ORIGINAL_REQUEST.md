# Original User Request

## 2026-09-10T13:59:04Z

This is a single self-contained build; keep it small and focused.
Build a Python-native agent coordination and completion-discipline framework combining the DAFG dynamic task graph runtime with runnable acceptance gate ledgers (`GATES.md`), evidence verification, depth tree orchestration, and stop hook enforcement.

Working directory: .
Integrity mode: development

## Requirements

### R1. Runnable Gate Ledger Engine (`gates`)
Implement a deterministic gate engine that parses, lints, and executes markdown gate ledgers (`GATES.md`).
- Support gate syntax with `- [ ] G<id>: <title>`, `CHECK: <command>`, `EXPECT: <pattern>`, optional `CWD:`, and `EVIDENCE:`.
- Enforce an approval security boundary where check commands must be inspected/approved before execution.
- Implement ledger linting (detecting tautological/unfalsifiable checks, duplicate IDs, missing tokens) and reverification (`--reverify`).
- Record decisive evidence (exit code, timestamp, output match) directly back into the ledger markdown upon successful execution.

### R2. DAFG Dynamic Task Graph & Depth Tree Runtime
Evolve the DAFG runtime (`dfag.py` / module) to execute autonomous agent workflows backed by objective gate evidence:
- Support dynamic planning, specialist role assignments, and dependency expansion (`needs`).
- Replace/augment subjective LLM-only review with objective gate checks: a node is only `ACCEPTED` when its assigned gates in `GATES.md` are verified with passing evidence.
- Maintain atomic state persistence (`state.json`), budget caps (calls, nodes, revisions, deadlines), and clean resumption of interrupted runs.
- Support depth tree decomposition: assign disjoint file ownership (`OWNS:`), stage rolling execution waves, and require child gate reverification before parent completion.

### R3. Agent Stop Hook & Completion Guard
Implement an agent stop hook mechanism:
- Intercept agent completion attempts and evaluate the active ledger state.
- Block premature completion if any runnable gate remains unmet, unverified, or unapproved.
- Only allow termination when all gates are met with recorded evidence or explicitly marked with `ABANDON: <id> <reason>`.

### R4. Project Tooling & Offline Test Suite
- Set up the project cleanly using `uv` with `pyproject.toml` and minimal standard dependencies.
- Provide a comprehensive, 100% passing offline test suite (`pytest`) with mocked LLM completions and simulated shell check commands, thoroughly verifying parser, linter, gate execution, security approvals, DAG state transitions, and stop hook blocking.

## Acceptance Criteria

### Gate Engine & Security
- [ ] Ledger parser correctly parses and updates `GATES.md`, preserving markdown format and recording evidence lines.
- [ ] Unapproved command checks are safely refused unless explicitly approved.
- [ ] Linter catches duplicate IDs, empty gates, and invalid expectations.

### DAFG & Orchestration
- [ ] DAFG runtime executes nodes, dynamically adds prerequisite tasks on `needs` requests, and enforces model call / node budgets.
- [ ] Node acceptance requires passing runnable gate verification rather than mere model self-certification.
- [ ] Resuming from `state.json` preserves previously consumed budgets, execution history, and gate states.

### Tooling & Verification
- [ ] Project initializes and runs via `uv run`.
- [ ] `uv run pytest` passes 100% offline with no network or API keys required.
- [ ] Stop hook correctly returns a blocking signal when pending gates exist.
