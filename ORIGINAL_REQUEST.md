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

## 2026-09-11T15:18:02Z

This is a focused implementation task with repeated adversarial review to fix the evaluation credibility, mock saturation, adapter divergence, and telemetry grounding in the DAFG framework.

Working directory: .
Integrity mode: development

## Problem Context
The current evaluation infrastructure (`src/dafg/eval.py`, `src/dafg/adapters.py`) exhibits statistical saturation and artificial 100% scores:
- Hardcoded keyword matching (`"unsolvable"`, `"halting"`) in `BaseRuntimeAdapter.check_refusal` trivially decides impossible tasks.
- Feasible tasks immediately return `COMPLETED` without executing real workloads.
- All three adapters (Iterative CLI, Tool Dispatch, ReAct) exhibit zero behavioral variance.
- Benchmark reports previously cited nonexistent JSON files without writing real artifacts to disk.

## Requirements

### R1. Genuine Discriminating Benchmark Tasks & Real Failure Paths
Replace trivial string-matched tasks with authentic, discriminating evaluation fixtures:
- Feasible tasks must execute real computational logic, dependency graph cascades, and gate verification checks.
- Impossible/refusal tasks must fail through genuine protocol and runtime constraints (e.g., cycle detection, strict gate mismatch, budget exhaustion, unauthorized file access), never by regex/keyword checks on node titles.
- Introduce realistic failure distributions: difficult horizon tasks, hostile flaky tool environments, and recovery scenarios with non-round pass rates.

### R2. Adapter-Specific Behavioral Divergence
Differentiate the three adapter architectures to reflect their actual structural characteristics:
- **Iterative CLI**: Sequential command execution with text stdout parsing; vulnerable to shell errors and raw text ambiguities.
- **Tool Dispatch**: Structured schema-driven function calling; sensitive to argument validation, tool availability, and schema mismatches.
- **ReAct State Machine**: Thought-Action-Observation loop; subject to reasoning budget limits, step loops, and observation truncation.
- Ensure cross-adapter benchmark runs produce authentic variance in token consumption, success rates, and failure distributions.

### R3. Inspectable On-Disk Benchmark Telemetry
- All benchmark and evaluation runs (`dafg eval`, `dafg audit`) must persist verifiable, reproducible JSON telemetry to disk (e.g., `eval_results/benchmark_matrix_v03.json`).
- Records must capture per-trial granularity: trial ID, task ID, adapter, condition, completion claim, standard 5-outcome classification, token count, duration, and error trace.
- Zero phantom claims: no summary metric may be reported without an accompanying on-disk artifact.

### R4. Calibrated Adversarial Conformance & Test Suite
- Protocol conformance tests must probe real edge cases (stale dispatches, epoch fencing, run sealing, replay protection) without rubber-stamping 100% on intentionally imperfect runs.
- Maintain a 100% passing offline test suite (`uv run pytest -q`) validating the corrected behavior.
- Ensure all acceptance gates in `GATES.md` are updated, approved, and verified via `uv run gates`.

## Acceptance Criteria

### Benchmark Credibility & Variance
- [ ] Keyword-based refusal checks (`check_refusal`) removed from adapters; refusal/blocking is determined by runtime constraints, unfulfillable gates, or dependency deadlocks.
- [ ] Cross-adapter evaluation on the v0.3 benchmark produces authentic variance across CLI, ToolDispatch, and ReAct adapters (no identical 100% scores).
- [ ] Realistic outcome distributions include non-round pass rates and genuine failures under hostile/flaky conditions.

### Artifact Persistence & Telemetry
- [ ] Running `dafg eval` generates inspectable JSON files on disk under `eval_results/` with complete trial-level details.
- [ ] Audit logs reflect real event traces produced by the authoritative protocol engine.

### Tooling & Verification
- [ ] Python standard library only (zero external runtime dependencies).
- [ ] `uv run pytest -q` passes offline.
- [ ] `uv run gates --status GATES.md` and `uv run stop-hook GATES.md --json` return valid evidence and allow completion.
