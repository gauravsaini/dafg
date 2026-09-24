# DAFG Canonical Product Goal

> **Product Thesis**: Autonomous coding agents must not self-certify success. Completion requires objective, reproducible, and independent verification.

## 1. Product Identity

**DAFG (Dynamic Autonomous Flow Graph)** is a **verification and completion-control runtime for autonomous coding agents**.

Rather than relying on model self-assessment (*"Looks good to me!"*), DAFG sits between the agent and the target workspace to enforce execution boundaries, run acceptance gates against independent ground truth, and prevent process termination until all requirements are empirically verified.

---

## 2. Target Audience & Problem Statement

### Target User
- **Platform Engineers & Tooling Authors**: Teams building and deploying coding agents, automated PR bots, and self-hosted developer tools.
- **Autonomous Coding Agents**: LLM agents operating across multi-file repositories under CI/CD and repository workflows.

### Target Buyer
- **Engineering Leadership & DevSecOps Teams**: Organizations seeking to adopt autonomous code generation without sacrificing verification standards, security compliance, or code quality.

### Core Problems Solved
1. **False Completion Claims**: Agents claiming victory based on internal optimistic evaluation without executing or passing comprehensive acceptance checks.
2. **Unverified Code Merges**: PRs and patches merged without reproducible proof of functional correctness and regression testing.
3. **Runaway Loops on Impossible Tasks**: Agents burning token budgets repeatedly on flawed or impossible prompts instead of failing fast and executing honest refusal.
4. **Workspace Write Contention**: Parallel subagents corrupting overlapping files without declared boundaries.
5. **Absence of Replay Evidence**: Lack of cryptographic, audit-ready event trails explaining why an automated change was accepted.

---

## 3. Product Scope & System Boundaries

### What DAFG Owns (In Scope)
- **Task & Dependency Execution Control**: Dynamic DAG resolution (`needs`) and parallel wave scheduling bounded by disjoint file ownership (`OWNS:`).
- **Acceptance Gate Ledger & Verification**: Parsing, linting, and executing deterministic checks in [`GATES.md`](file:///Users/ektasaini/dafg/GATES.md).
- **Cryptographic Command Approval**: Strict SHA-256 command signing (`.approved_gates.json`) preventing arbitrary agent tool injection.
- **Completion Control & Stop Hooks**: Interlocking agent lifecycle termination (`stop-hook`) so agents cannot stop while gates are pending or failing.
- **Bounded Repair & Audit Trails**: Atomic state snapshots ([`state.json`](file:///Users/ektasaini/dafg/state.json)) and deterministic FSM replay.

### What DAFG Does Not Own (Out of Scope)
- **Model Serving & Hosting**: DAFG delegates inference to existing model backends and CLI tools.
- **Universal Agent Chat Meshes**: DAFG is not an unconstrained peer-to-peer social agent chatroom.
- **Unverified Self-Evolution**: Autonomous code generation quality is only as trustworthy as the independent verification oracle.
- **3D Simulations / Toy Benchmarks**: External demo artifacts (such as the legacy Boeing 747 Three.js simulation) are deprecated and out of scope.

---

## 4. Position on Performance Accelerators (Streaming)

Streaming token inspection, duplex early abort, and challenger barge-in are **optional gated performance accelerators**, not the core product thesis.

The primary control plane is built on batch gate execution, empirical proof collection, and stop-hook interlocks. Streaming mechanisms will only be promoted to active workflows if empirical benchmarks demonstrate ≥20% token or latency savings without degrading verified delivery rates.
