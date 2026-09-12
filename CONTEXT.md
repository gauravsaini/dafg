# Project Domain Context & Glossary

This document serves as the canonical domain glossary for DAFG. It defines the core domain terms and their precise meanings.

## Domain Terms

### Acceptance Gate
An atomic, verifiable contract declaring a concrete outcome required for task completion. Defined by a runnable command (`CHECK`), an expected matching pattern (`EXPECT`), and explicit file ownership boundaries (`OWNS`).

### Gate Ledger (`GATES.md`)
The machine-executable ledger storing all active, met, and abandoned Acceptance Gates. Serves as the single source of truth for repository completion readiness.

### StopHook Interlock
A process-level security and discipline boundary that intercepts agent exit or termination requests. Prevents agents from completing a session while any Acceptance Gate is pending, unmet, or unverified.

### Completion Guard
The runtime engine that evaluates Gate Ledgers against the StopHook Interlock policy. Returns deterministic binary decisions (`allow` or `block`) accompanied by structured diagnostics.

### Evidence Strength
A qualitative tier classifying the proof strength of recorded gate evidence:
- `NONE`: No evidence recorded.
- `PENDING`: Gate execution has not yet been confirmed.
- `MODEL_JUDGMENT`: Gate outcome verified subjectively without an executable check.
- `STRING_MATCH`: Executable check produced exit code 0 and matched expected output patterns.
- `EXECUTABLE_PROOF`: Executable check passed mutation testing adequacy, proving that broken implementations strictly fail.

### Gate Adequacy (Mutation Testing)
The property wherein an Acceptance Gate is proven capable of detecting faults. Demonstrated by systematically injecting mutations (e.g. negating exit codes or corrupting expect patterns) and confirming that the gate does not remain green.

### Integration Gap (Silent Failure)
The vulnerability where an unconstrained AI agent declares completion (`status="COMPLETED"`) despite unverified assumptions, broken assets, or failing integration tests.

### Agent Interlock Scaffold
The unified configuration protocol that binds external AI agent harnesses (including Claude Code, OpenAI Codex, Google Antigravity, Cursor, and GitHub Copilot) to the DAFG StopHook Interlock.
