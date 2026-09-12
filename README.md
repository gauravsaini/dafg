# DAFG: Directed Acyclic Funnel Graph
### *An Autonomous Computational Organism for Grounded Multi-Agent Convergence*

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/badge/package%20manager-uv-blueviolet)](https://github.com/astral-sh/uv)
[![Tests](https://img.shields.io/badge/tests-348%20passed-brightgreen.svg)]()
[![Runtime Dependencies](https://img.shields.io/badge/dependencies-0%20runtime%20deps-success.svg)]()
[![Protocol Audit](https://img.shields.io/badge/protocol%20audit-7%2F7%20passed-success.svg)]()

---

## 1. The Core Philosophy: An Autonomous Organism

Most multi-agent systems resemble chaotic chatrooms: agents banter, hallucinate progress, and self-certify completion (*"Looks good to me!"*). When left alone, they either diverge into infinite loops or exit prematurely on false confidence.

**DAFG** is fundamentally different. It is an **autonomous computational organism** designed to operate without human intervention. The organism lives or dies strictly by its own internal rules:

> **A self-governing, self-correcting, bounded-adversarial system that converges to mathematically verifiable delivery—or cleanly collapses under resource exhaustion.**

```text
               ┌─────────────────────────────────────────────────────────┐
               │              GOAL / HIGH-ENTROPY INTENT                 │
               └────────────────────────────┬────────────────────────────┘
                                            │
                                            ▼
                       [ Directed Acyclic Funnel Graph (DAFG) ]
                            Prerequisite Expansion (`needs`)
                            Disjoint File Ownership (`OWNS:`)
                                            │
                                            ▼
               ┌─────────────────────────────────────────────────────────┐
               │                     PER-NODE TRIAD                      │
               │                                                         │
               │   ┌──────────────┐   Adversarial    ┌──────────────┐    │
               │   │    PROVER    │◄────────────────►│  CHALLENGER  │    │
               │   │  (Synthesizer│      Vectors     │ (Stress/Mut) │    │
               │   └──────┬───────┘                  └──────────────┘    │
               │          │ Submits Evidence                             │
               │          ▼                                              │
               │   ┌──────────────┐   Cryptographic  ┌──────────────┐    │
               │   │   VERIFIER   │◄────────────────►│ APPROVALS    │    │
               │   │ (Shell Proof)│     SHA-256      │ (GATES.md)   │    │
               │   └──────────────┘                  └──────────────┘    │
               └────────────────────────────┬────────────────────────────┘
                                            │
                        Stigmergic Signals (Pheromone Decay)
                        Deterministic FSM (Pure Reducer Replay)
                                            │
                                            ▼
                        ┌───────────────────────────────────────┐
                        │      VERIFIED CONVERGENCE             │
                        │   (Stop Hook `allow` upon Proof)      │
                        └───────────────────────────────────────┘
```

---

## 2. The Core Biological Pillars

The organism is composed of six mutually-reinforcing architectural subsystems:

### Pillar 1: Directed Acyclic Funnel Graph (DAFG)
**Module**: [`src/dafg/runtime.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/runtime.py) (`DAFG`, `TaskNode`, `WaveScheduler`)  
Open-ended agent intentions are funneled through a strict DAG. 
- **Prerequisite Expansion**: Nodes dynamically sprout dependencies at runtime (`needs`) when prerequisites are uncovered during execution.
- **Wave Scheduling**: Tasks declare precise file boundaries (`OWNS:`). Non-interfering nodes execute in parallel waves, preventing workspace race conditions.
- **Budgets & Invariants**: Total wall-clock time, tool calls, and node revisions are capped via `Budget`. Runaway loops result in explicit node starvation, never infinite token burns.

### Pillar 2: The Per-Node Triad (Prover / Challenger / Verifier)
**Modules**: [`src/dafg/protocol.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/protocol.py), [`src/dafg/adversarial.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/adversarial.py), [`src/dafg/mutation.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/mutation.py)  
No task node is trusted to evaluate its own output. Work within every node is mediated by a dialectical triad:
1. **The Prover**: Executes the creative or functional task, producing code and verifiable artifact proposals.
2. **The Challenger**: An adversarial critic that subjects the proposal to parameter sweeps, boundary conditions, and gate mutation attacks (`GateMutator`) to discover where assumptions break.
3. **The Verifier**: The empirical authority. It refuses subjective prose and requires deterministic execution evidence (`exit_code=0` with `EXPECT:` pattern matches) before clearing a node.

### Pillar 3: Formal Finite State Machine & Pure Reducer
**Modules**: [`src/dafg/protocol.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/protocol.py), [`docs/STATE_MACHINE.md`](file:///Users/ektasaini/Desktop/framework/docs/STATE_MACHINE.md)  
Node lifecycles are governed by a formal 8-state transition machine:
```text
IDLE ──► CONTEXT_LOADED ──► PROVING ◄───► CHALLENGING ──► VERIFYING ──► ACCEPTED
  ▲           │                │                              │             │
  │           ▼                ▼                              ▼             ▼
  └─────── REJECTED ◄──────────┴──────────────────────────────┴──────► STALE (epoch++)
```
- **Fenced Execution**: Actions are bound by cryptographic `DispatchIdentity`. Workers cannot impersonate roles or skip verification states.
- **Pure Reducer**: State transitions are pure and idempotent (`ProtocolReducer.apply`). Every execution trajectory can be replayed, audited, or resumed from `state.json`.

### Pillar 4: Dynamic Persona Compilation & Adaptation
**Module**: [`src/dafg/persona.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/persona.py) (`PersonaCompiler`, `PersonaProfile`, `PersonaSwitcher`)  
Agent personas are not static prompts. The `PersonaCompiler` synthesizes lightweight, role-specific behavioral profiles based on:
- Declared node capabilities (toolsets, reasoning depth, policy constraints).
- Historical defect patterns: When a node hits repeated challenge failures, the `PersonaSwitcher` automatically mutates the agent’s operating posture (e.g., from optimistic code-generation to conservative test-first synthesis).

### Pillar 5: Stigmergic Timeline & Pheromone Decay
**Module**: [`src/dafg/trends.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/trends.py) (`TrendStore`, `TrendAnalyzer`)  
Agents in DAFG do not rely on expensive peer-to-peer chat. Instead, they coordinate **stigmergically**—leaving marks and evidence trails directly in the environment:
- Every execution appends structured event records to an append-only timeline (`trends.jsonl`).
- **Decaying Confidence Signals**: Flaky gates and volatile submodules generate warning pheromones (`FlakyGate`). Subsequent nodes read these environmental signals at initialization, allocating more adversarial challenge cycles to historically unstable areas.

### Pillar 6: Strict Autonomy & The Stop Hook Membrane
**Modules**: [`src/dafg/gates.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/gates.py), [`src/dafg/hook.py`](file:///Users/ektasaini/Desktop/framework/src/dafg/hook.py) (`CompletionGuard`)  
DAFG treats the outer operating system boundary as a biological membrane:
- Check commands in `GATES.md` are cryptographically signed in `.approved_gates.json` (SHA-256) to eliminate arbitrary code injection.
- The `stop-hook` acts as a termination barrier. If any agent attempts to stop or declare victory while gates are pending, unverified, or unapproved, the hook returns `{"decision": "block"}`. Completion is allowed only when empirical proofs exist for every invariant.

---

## 3. Quick Start (60 Seconds)

### Installation
DAFG uses standard library Python 3.10+ with zero external runtime dependencies. Manage it with [`uv`](https://github.com/astral-sh/uv):

```bash
# Clone the repository
git clone https://github.com/gauravsaini/dafg.git
cd dafg

# Sync dev dependencies (pytest)
uv sync
```

### 1. Scaffold Agent Interlocks
Initialize the acceptance ledger and stop-hook interlocks for your agent of choice (Claude Code, OpenAI Codex, Antigravity, Cursor, Copilot):

```bash
uv run dafg init --agents all
```

### 2. Define Acceptance Criteria (`GATES.md`)
Declare verifiable outcomes in the gate ledger:

```markdown
# Acceptance Gates: User Authentication Service

- [ ] G1: Module imports cleanly
  CHECK: uv run python -c "import auth; print('OK')"
  EXPECT: OK
  OWNS: src/auth.py
  EVIDENCE: pending

- [ ] G2: Unit test suite passes
  CHECK: uv run pytest tests/test_auth.py -q
  EXPECT: 12 passed
  OWNS: src/auth.py, tests/test_auth.py
  EVIDENCE: pending
```

### 3. Approve, Run & Verify Stop Readiness

```bash
# 1. Cryptographically sign the gate checks
uv run gates --approve GATES.md

# 2. Run the DAFG autonomous runtime
uv run dafg run --gates GATES.md --state state.json

# 3. Interrogate the stop-hook guard (blocks if work is incomplete)
uv run stop-hook GATES.md --json
```

---

## 4. CLI Reference

| Command | Subsystem | Description |
|---|---|---|
| `uv run dafg run` | **Runtime** | Executes dynamic task graph with wave scheduling and atomic state checkpoints |
| `uv run dafg audit` | **Protocol** | Runs the formal 7-pillar protocol state machine conformance audit |
| `uv run dafg init` | **Scaffolder** | Generates platform-specific stop-hook interlocks and initial `GATES.md` |
| `uv run dafg eval` | **Benchmarks** | Runs decoupled execution adapters (CLI, Tool-Dispatch, ReAct) against test suites |
| `uv run gates --lint` | **Verifier** | Validates gate syntax, duplicate IDs, tautologies, and regex patterns |
| `uv run gates --approve` | **Security** | Computes SHA-256 signatures for runnable gate checks into `.approved_gates.json` |
| `uv run gates --run` | **Verifier** | Executes pending approved gates and writes decisive empirical evidence |
| `uv run gates --reverify`| **Verifier** | Re-executes previously passed gates to detect regressions across waves |
| `uv run stop-hook` | **Membrane** | Evaluates completion readiness: returns `{"decision": "block"}` or `{"decision": "allow"}` |

---

## 5. Grounded Code Map

Every concept in this document is mapped directly to zero-dependency Python modules:

```text
src/dafg/
├── runtime.py       # Funnel Graph (DAFG), TaskNode, WaveScheduler, Atomic StateStore
├── protocol.py      # Triad Roles, 8-State FSM, DispatchIdentity, ProtocolReducer
├── adversarial.py   # Challenger Engine: Parameter search spaces, worst-case inspection
├── mutation.py      # Gate Mutator: Kill-rate adequacy tests, adversarial mutants
├── persona.py       # Dynamic Persona Compiler, PersonaProfile, Capability PolicyEngine
├── trends.py        # Stigmergic Timeline: Telemetry store, flakiness detection, signal decay
├── gates.py         # Empirical Verifier: GateLedger, ApprovalStore (SHA-256), GateLinter
├── hook.py          # Strict Autonomy Membrane: CompletionGuard stop-hook interlock
├── repair.py        # Closed-Loop Self-Healing: RevisionDirective, failure taxonomy
├── adapters.py      # Execution Adapters: Iterative CLI, Tool Dispatch, ReAct State Machine
├── schema.py        # Typed Schemas & Robust JSON Recovery
└── init.py          # Platform Interlock Scaffolder (Claude, Codex, Antigravity, Cursor)
```

---

## 6. Formal Protocol Conformance & Verification

DAFG includes a built-in self-test suite and formal conformance auditor to verify that the organism's state machine invariants never break:

```bash
# Run formal protocol audit (7/7 formal checks)
uv run dafg audit

# Run full offline test suite (348 passed in ~5s)
uv run pytest -q
```

---

## License

MIT License. Built for deterministic agent coordination, bounded adversarial self-correction, and absolute completion discipline.
