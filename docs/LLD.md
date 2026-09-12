# Low-Level Design (LLD): DAFG Framework

> **Location**: `docs/LLD.md`  
> **Applicable Version**: DAFG v0.3+  
> **Source Modules**: `src/dafg/runtime.py`, `src/dafg/protocol.py`, `src/dafg/gates.py`, `src/dafg/adapters.py`, `src/dafg/persona.py`

This document details the Low-Level Design (LLD), object models, subsystem interactions, security boundaries, and execution flows of **DAFG (Dynamic Autonomous Flow Graph)**.

---

## 1. System Overview & Core Invariants

**DAFG** coordinates autonomous LLM worker collectives while enforcing deterministic completion discipline. Unlike systems that rely on model self-certification, DAFG grounds completion in:

1. **Deterministic Acceptance Ledgers**: Outcomes are defined as executable shell commands (`CHECK:`) matched against decisive outputs (`EXPECT:`).
2. **Cryptographic Approval Boundary**: Arbitrary commands authored by LLMs cannot execute without explicit cryptographic approval.
3. **Capability-Aware Routing**: Tasks are compiled into structured persona profiles and routed only to backends that satisfy their required capabilities.
4. **Bounded Failure Adaptation**: Failed attempts trigger failure classification and bounded persona/method adaptation rather than unbounded retry loops.
5. **Agent Stop Hook Discipline**: Agent termination is intercepted and blocked until all assigned gates are objectively met.

---

## 2. Architecture & Operational Planes

DAFG coordinates execution across two unified operational planes:
- **Execution & Coordination Plane**: Dynamic DAG planning, runtime worker dispatch, prerequisite discovery (`needs`), capability-aware routing, persona compilation, and atomic state checkpoints.
- **Verification & Discipline Plane**: Acceptance gate ledgers (`GATES.md`), cryptographic check approvals, objective shell execution evidence, and agent stop hooks.

```
┌────────────────────────────────────────────────────────────────────────┐
│                     INTEGRATED DAFG (Current)                          │
│                                                                        │
│   • Dynamic DAG Planning (TaskNode)       • Persona Compiler           │
│   • Prerequisite Expansion (needs)        • Capability Router          │
│   • Wave Scheduler (Disjoint OWNS)        • Budget Engine              │
│   • Bounded Adaptation (PersonaSwitcher)  • Atomic State Persistence   │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │               Verification & Discipline Plane                  │   │
│   │                                                                │   │
│   │   • Acceptance Gate Ledger (GATES.md)                          │   │
│   │   • Cryptographic Approval Boundary (.approved_gates.json)     │   │
│   │   • Deterministic Shell Check Execution & Evidence Recording   │   │
│   │   • Ledger Linter & Reverification (--reverify)                │   │
│   │   • Agent Stop Hook Completion Guard (decision: block)         │   │
│   └────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

### Architectural Evolution Matrix

| Dimension | Ad-Hoc Agent Execution | DAFG v0.2 (Legacy) | DAFG (Current v0.3+) |
|---|---|---|---|
| **Autonomous Agent Loop** | ❌ Unstructured prompt loop | ⚠️ Basic loop (`dfag.ask()`) | ✅ Deterministic runtime (`DAFG.run()`) |
| **Dynamic DAG & Prerequisite Spawning** | ❌ None (monolithic prompt) | ⚠️ Linear `needs` expansion | ✅ Dynamic DAG + multi-wave disjoint execution |
| **Model Selection & Routing** | ❌ Single hardcoded model | ❌ Static default model | ✅ Capability-aware `AgentRouter` |
| **Persona Compilation** | ❌ Static system prompt | ❌ Static string label | ✅ `PersonaProfile` + `PolicyEngine` |
| **Node Acceptance Mechanism** | ❌ Subjective LLM self-assessment | ❌ Subjective LLM review | ✅ **Objective gate evidence** (`GATES.md`) |
| **Security Approval Boundary** | ❌ None (unbounded tool calls) | ❌ None | ✅ `ApprovalStore` SHA-256 cryptographic boundary |
| **Interruption Resumption** | ❌ Lost context on crash | ⚠️ Basic `state.json` | ✅ Atomic `StateStore` + budget caps |
| **Agent Termination Discipline** | ❌ Prompt-based ("stop when done") | ❌ None | ✅ `CompletionGuard` stop hook (`block` until verified) |

---

## 3. Component & Data Flow Architecture

The following diagram illustrates how tasks flow through planning, compilation, routing, execution, gate verification, state persistence, and stop hook enforcement.

```mermaid
flowchart TD
    subgraph Planning ["1. Planning & Dependency Phase"]
        UserGoal["User Task / Goal"] --> DAFG_Init["DAFG Graph Initialization"]
        LedgerParse["GateLedger.parse('GATES.md')"] --> DAFG_Init
        DAFG_Init --> ReadyQueue["Task Ready Queue (Wave Scheduler)"]
    end

    subgraph PersonaAndRouting ["2. Persona Compilation & Routing"]
        ReadyQueue --> NodeReady["TaskNode Selected"]
        NodeReady --> Compiler["PersonaCompiler.compile(task)"]
        Compiler --> Profile["PersonaProfile (role, mission, capabilities, requested tools)"]
        Profile --> Policy["PolicyEngine.authorize(requested_tools) & allows(backend)"]
        Policy --> Router["AgentRouter.dispatch(task, profile)"]
        Router --> Plan["DispatchPlan (backend, persona, authorized_tools, scoped_context)"]
    end

    subgraph Execution ["3. Worker Execution"]
        Plan --> WorkerExec["Worker / LLM Invocation (executor_fn)"]
        WorkerExec --> AgentResp["AgentResponse (output, needs, spawn_children, files)"]
    end

    subgraph Verification ["4. Objective Gate Verification"]
        AgentResp --> CheckGates{"Assigned Gates?"}
        CheckGates -- Yes --> ApprovalCheck{"Approved in .approved_gates.json?"}
        ApprovalCheck -- Yes --> GateExec["GateEngine.execute_gate(reverify=True)"]
        ApprovalCheck -- No --> SecFail["SECURITY: UNAPPROVED"]
        GateExec --> GateVerdict{"Exit 0 & EXPECT matched?"}
        GateVerdict -- Yes --> RecordEvidence["Record EVIDENCE into GATES.md"]
        GateVerdict -- No --> GateFailed["Gate Check Failed"]
    end

    subgraph Adaptation ["5. Failure Classification & Bounded Adaptation"]
        SecFail --> Classifier["FailureClassifier.classify()"]
        GateFailed --> Classifier
        Classifier --> FailureKind["FailureKind (INCOMPLETE, WRONG_APPROACH, CAPABILITY_MISMATCH, etc.)"]
        FailureKind --> Switcher["PersonaSwitcher.adapt(task, profile, kind)"]
        Switcher --> Switched{"Within Switch Budget?"}
        Switched -- Yes --> UpdatePersona["Update Persona & Re-queue"]
        Switched -- No --> TaskFail["Task Node: FAILED"]
    end

    subgraph Finalization ["6. Completion & Persistence"]
        RecordEvidence --> AcceptNode["Task Node: ACCEPTED"]
        AcceptNode --> StatePersist["StateStore.save('state.json') via Atomic Rename"]
        StatePersist --> StopHookCheck["CompletionGuard.evaluate('GATES.md')"]
        StopHookCheck --> FinalDecision{"All Gates Met?"}
        FinalDecision -- Yes --> AllowStop["STOP ALLOWED"]
        FinalDecision -- No --> BlockStop["STOP BLOCKED"]
    end
```

---

## 4. Core Class Diagram

The following class diagram illustrates the primary abstractions, their attributes, and relationships across the framework.

```mermaid
classDiagram
    class DAFG {
        +dict nodes
        +Budget budget
        +GateLedger ledger
        +GateEngine engine
        +AgentRouter router
        +PersonaCompiler compiler
        +PersonaSwitcher switcher
        +FailureClassifier classifier
        +Path state_path
        +add_node(node) TaskNode
        +schedule_waves() List
        +execute_node(node, executor_fn) bool
        +step(executor_fn) dict
        +run(executor_fn, max_steps) str
        +save_state() void
    }

    class TaskNode {
        +str id
        +str title
        +str role
        +NodeStatus status
        +list needs
        +list assigned_gates
        +list owns
        +str parent_id
        +list children
        +int depth
        +int revisions
        +int max_revisions
        +dict persona
        +list persona_history
        +str backend_name
        +int persona_switches
        +int max_persona_switches
        +to_dict() dict
        +from_dict(data) TaskNode
    }

    class PersonaProfile {
        +str persona_id
        +str role
        +str mission
        +list expertise
        +list method
        +list required_capabilities
        +list requested_tools
        +str output_schema
        +list review_focus
        +int version
        +to_dict() dict
        +from_dict(data) PersonaProfile
    }

    class PersonaCompiler {
        +compile(task, context, previous_feedback, attempt) PersonaProfile
    }

    class Backend {
        +str name
        +set capabilities
        +float cost_per_call
        +str risk_tier
        +int max_context
        +int priority
        +supports(required_capabilities) bool
    }

    class BackendRegistry {
        -dict _backends
        +register(backend) void
        +get(name) Backend
        +list_backends() List
        +default_registry() BackendRegistry
    }

    class PolicyEngine {
        +set allowed_tools
        +str max_risk_tier
        +set allowed_backends
        +set denied_backends
        +allows(backend, persona, task) bool
        +authorize(requested_tools, task) List
    }

    class AgentRouter {
        +BackendRegistry registry
        +PolicyEngine policy
        +find_eligible(persona, task, budget) List
        +select_backend(eligible, task_risk, prior_failures) Backend
        +dispatch(task, persona, context, budget) DispatchPlan
    }

    class GateLedger {
        +dict gates
        +list raw_lines
        +Path filepath
        +parse(text, filepath) GateLedger
        +load(filepath) GateLedger
        +get_gate(id) Gate
        +update_gate_evidence(id, evidence, status) bool
        +save(filepath) void
    }

    class Gate {
        +str id
        +str title
        +str check
        +str expect
        +str owns
        +str cwd
        +str status
        +str evidence
        +str abandon_reason
        +is_runnable() bool
    }

    class ApprovalStore {
        +Path filepath
        +compute_hash(check, expect, cwd, env_keys) str
        +approve(gate) str
        +is_approved(gate) bool
        +save() void
    }

    class GateEngine {
        +ApprovalStore approval_store
        +bool auto_approve
        +execute_gate(gate, ledger, reverify) GateResult
    }

    class CompletionGuard {
        +GateLedger ledger
        +ApprovalStore approval_store
        +Path state_file
        +int max_stagnant_blocks
        +evaluate() StopDecision
    }

    class Schema {
        +dict fields
        +validate(data) dict
    }

    DAFG --> TaskNode : manages
    DAFG --> GateLedger : references
    DAFG --> GateEngine : executes gates via
    DAFG --> AgentRouter : dispatches via
    DAFG --> PersonaCompiler : compiles profiles with
    DAFG --> PersonaSwitcher : adapts failures with
    AgentRouter --> BackendRegistry : queries
    AgentRouter --> PolicyEngine : validates against
    GateEngine --> ApprovalStore : checks approvals
    GateLedger --> Gate : contains
    CompletionGuard --> GateLedger : inspects
    TaskNode --> PersonaProfile : stores
```

---

## 5. Execution & Dispatch Sequence

The interaction between the core subsystems during a single execution wave is captured below:

```mermaid
sequenceDiagram
    autonumber
    participant DAFG as DAFG Engine
    participant Compiler as PersonaCompiler
    participant Policy as PolicyEngine
    participant Router as AgentRouter
    participant Worker as Worker / LLM
    participant Engine as GateEngine
    participant Store as ApprovalStore
    participant Ledger as GateLedger (GATES.md)
    participant State as StateStore (state.json)

    DAFG->>DAFG: schedule_waves() (filters dependencies & disjoint OWNS)
    DAFG->>Compiler: compile(task, context)
    Compiler-->>DAFG: PersonaProfile(role, mission, capabilities, requested_tools)

    DAFG->>Router: dispatch(task, profile, context)
    Router->>Policy: allows(backend, profile, task)
    Policy-->>Router: true
    Router->>Policy: authorize(profile.requested_tools, task)
    Policy-->>Router: authorized_tools (strictly filtered)
    Router-->>DAFG: DispatchPlan(backend, authorized_tools, scoped_context)

    DAFG->>Worker: executor_fn(task, scoped_context)
    Worker-->>DAFG: AgentResponse(output, needs, files_modified)

    opt If task has assigned gates
        loop For each gate in task.assigned_gates
            DAFG->>Engine: execute_gate(gate, reverify=True)
            Engine->>Store: is_approved(gate)
            Store-->>Engine: true (hash matched)
            Engine->>Engine: run process (subprocess.run)
            Engine->>Engine: match stdout/stderr against EXPECT
            Engine-->>DAFG: GateResult(status='MET', exit_code=0)
            DAFG->>Ledger: update_gate_evidence(gate_id, evidence)
            Ledger->>Ledger: write inline evidence to GATES.md
        end
    end

    DAFG->>DAFG: node.status = ACCEPTED
    DAFG->>State: save(state_dict, 'state.json')
    State->>State: write to temp file & atomic replace
```

---

## 6. TaskNode State Machine & Dual-Dimensional Protocol Architecture

> For the comprehensive specification and interactive diagrams, see [`docs/STATE_MACHINE.md`](docs/STATE_MACHINE.md).

DAFG separates node lifecycle management into two orthogonal, synchronized planes:
1. **Authoritative Protocol FSM (`ProtocolState`)**: pure decision logic (`ProtocolEngine.decide`) and deterministic reducer replay (`ProtocolReducer.apply`).
2. **Scheduler Execution Projection (`ExecutionStatus` / `NodeStatus`)**: derived via `state_projection(node.protocol_state)`.

### 6.1 Authoritative Node FSM (`ProtocolState`)

```mermaid
stateDiagram-v2
    [*] --> IDLE

    IDLE --> CONTEXT_LOADED : LOAD_CONTEXT [G_manifest, G_auth]
    IDLE --> PROVING : DISPATCH_PROVE / DISPATCH_FASTPATH [G_auth, stamps DispatchIdentity]
    IDLE --> IDLE : BLOCK [dependency unfulfilled]
    IDLE --> STALE : INVALIDATE [upstream cascade]

    CONTEXT_LOADED --> PROVING : DISPATCH_PROVE / DISPATCH_FASTPATH [stamps DispatchIdentity]
    CONTEXT_LOADED --> REJECTED : REFUSE [G_auth failure / contradictory requirements]
    CONTEXT_LOADED --> DEGRADED : DEGRADE [partial capability fallback]
    CONTEXT_LOADED --> IDLE : BLOCK [prerequisite wait]
    CONTEXT_LOADED --> STALE : INVALIDATE [upstream cascade]

    PROVING --> VERIFYING : SUBMIT_PROPOSAL [artifact produced]
    PROVING --> CHALLENGING : CHALLENGE [adversarial review requested]
    PROVING --> REJECTED : REJECT / FAIL [local defect / killswitch activation]
    PROVING --> REVISING : REVISE [targeted revision directive]
    PROVING --> IDLE : BLOCK / HALT [resource cap / budget halt]
    PROVING --> STALE : INVALIDATE [in-flight preemption]

    CHALLENGING --> VERIFYING : SUBMIT_EVIDENCE [evidence submitted]
    CHALLENGING --> REVISING : REVISE [challenge defect exposed]
    CHALLENGING --> IDLE : BLOCK
    CHALLENGING --> STALE : INVALIDATE [in-flight preemption]

    VERIFYING --> ACCEPTED : ACCEPT_VERDICT [G_fence match, G_gate MET, exit_code=0]
    VERIFYING --> REVISING : REVISE [verification defect found]
    VERIFYING --> REJECTED : REJECT / FAIL [unrecoverable failure]
    VERIFYING --> IDLE : BLOCK
    VERIFYING --> STALE : INVALIDATE [in-flight preemption]

    REVISING --> CONTEXT_LOADED : LOAD_CONTEXT [reload updated context]
    REVISING --> PROVING : DISPATCH_PROVE [re-dispatch revision]
    REVISING --> REJECTED : REJECT [max_revisions budget exhausted]
    REVISING --> STALE : INVALIDATE [upstream cascade]

    STALE --> CONTEXT_LOADED : LOAD_CONTEXT [re-sync updated contracts]
    STALE --> PROVING : DISPATCH_PROVE [re-dispatch with bumped epoch]

    ACCEPTED --> STALE : INVALIDATE [upstream REVISE_SUPERSEDES / schema drift / epoch++]
    ACCEPTED --> REJECTED : REJECT [post-acceptance audit defect]
    ACCEPTED --> REVISING : REVISE [post-acceptance repair]
    DEGRADED --> STALE : INVALIDATE [upstream invalidation]

    REJECTED --> IDLE : REOPEN [repair wave initiated]
    REJECTED --> CONTEXT_LOADED : LOAD_CONTEXT [re-contextualized repair]
    REJECTED --> PROVING : DISPATCH_PROVE / FASTPATH [direct retry]
    REJECTED --> REVISING : REVISE [repair directive applied]

    ACCEPTED --> [*] : SEAL_RUN [G_seal: completion integrity verified]
```

### 6.2 Two-Dimensional Mapping Matrix

| `ProtocolState` (Authoritative) | `ExecutionStatus` (Scheduler) | Legacy `NodeStatus` | Operational Semantics |
|---|---|---|---|
| `IDLE` | `READY` | `PENDING` | Initial state; inputs and dependencies pending |
| `CONTEXT_LOADED` | `READY` | `READY` | Manifest verified; ready for wave dispatch |
| `PROVING` | `RUNNING` | `RUNNING` | Active worker execution; `DispatchIdentity` stamped |
| `CHALLENGING` | `RUNNING` | `RUNNING` | Adversarial reviewer testing counter-examples |
| `VERIFYING` | `WAITING_IO` | `RUNNING` | Evaluating runnable gates in `GATES.md` |
| `REVISING` | `BLOCKED` | `REJECTED` | Diagnostic repair directive applied; waiting re-dispatch |
| `STALE` | `BLOCKED` | `READY` | Upstream dependency invalidated; epoch bumped |
| `ACCEPTED` | `SETTLED` | `ACCEPTED` | Decisive gate evidence recorded (`exit_code=0`) |
| `DEGRADED` | `SETTLED` | `ACCEPTED` | Authorized partial capability fallback |
| `REJECTED` | `SETTLED` | `REJECTED` | Terminal refusal or repair candidate |

### 6.3 Diagnostic Bounded Adaptation Flow

```mermaid
stateDiagram-v2
    state REJECTED {
        [*] --> Classify
        Classify --> IncompleteWork: INCOMPLETE_WORK (syntax/timeout)
        Classify --> WrongApproach: WRONG_APPROACH (flawed design/race)
        Classify --> CapabilityMismatch: CAPABILITY_MISMATCH (reasoning deficit)
        Classify --> MissingDep: MISSING_DEPENDENCY (missing prereq)
        Classify --> MissingPerm: MISSING_PERMISSION (unapproved tool)

        IncompleteWork --> RetainPersona: Provide concrete feedback
        WrongApproach --> AdaptMethod: Increment version & adjust method
        CapabilityMismatch --> EscalateBackend: Upgrade capability tier
        MissingDep --> InjectPrereq: Add to task.needs
        MissingPerm --> ApprovalRequest: Flag policy blocker
    }

    REJECTED --> IDLE: revisions < max_revisions & REOPEN action
    REJECTED --> [*]: revisions >= max_revisions (TERMINAL)
```

---

## 7. Security Approval Boundary & Verification Flow

To prevent untrusted agent-generated code from executing arbitrary shell commands, DAFG employs a cryptographic approval boundary:

```mermaid
flowchart TD
    GateDecl["Gate in GATES.md:
CHECK: uv run pytest -q
EXPECT: 117 passed
CWD: ."] --> HashFunc["ApprovalStore.compute_hash(check, expect, cwd, env_keys)"]
    HashFunc --> SHA256["SHA-256 Digest (64 chars)"]

    subgraph ApprovalStoreFile [".approved_gates.json"]
        StoredHash["Stored Hash Entry:
{
  'G1': 'a3f9e...c71b'
}"]
    end

    SHA256 --> CompareHash{"Matches Stored Hash?"}
    StoredHash --> CompareHash

    CompareHash -- Yes --> ExecApproved["Subprocess Execution Allowed"]
    CompareHash -- No --> RefuseExec["Return GateResult(status='UNAPPROVED')"]

    subgraph ManualApproval ["Approval Step (uv run gates --approve)"]
        HumanOrAudit["User / Security Audit Review"] --> ApproveCmd["ApprovalStore.approve(gate)"]
        ApproveCmd --> StoredHash
    end
```

---

## 8. Agent Stop Hook Completion Guard

The stop hook acts as the final quality gate before an agent or harness can terminate a session:

```mermaid
flowchart TD
    AgentStopRequest["Agent Attempting to Exit / Terminate"] --> GuardEval["CompletionGuard.evaluate()"]
    GuardEval --> ParseLedger["Parse active GATES.md"]

    ParseLedger --> CheckPending{"Any gates pending?"}
    CheckPending -- Yes --> ReasonPending["Record pending gate IDs"]

    ParseLedger --> CheckApprovals{"Any checks unapproved?"}
    CheckApprovals -- Yes --> ReasonUnapproved["Record unapproved gate IDs"]

    ParseLedger --> CheckEvidence{"Any checks unverified?"}
    CheckEvidence -- Yes --> ReasonUnverified["Record unverified gate IDs"]

    ReasonPending --> ComputeDecision{"Any issues found?"}
    ReasonUnapproved --> ComputeDecision
    ReasonUnverified --> ComputeDecision
    CheckPending -- No --> CheckApprovals
    CheckApprovals -- No --> CheckEvidence
    CheckEvidence -- No --> ComputeDecision

    ComputeDecision -- Yes --> CheckStagnant{"Progress Guard:
consecutive stagnant blocks >= 6?"}
    CheckStagnant -- Yes --> ReleaseGuard["Release Progress Guard (break deadlock)"]
    CheckStagnant -- No --> EmitBlock["Emit: { 'decision': 'block', 'allowed': false }"]

    ComputeDecision -- No --> EmitAllow["Emit: { 'decision': 'allow', 'allowed': true }"]
    ReleaseGuard --> EmitAllow
```

---

## 9. Subsystem Deep-Dive & Invariants

### 9.1 Disjoint File Ownership (`OWNS:`) & Rolling Wave Dispatch
- Each task or gate declares its file ownership patterns (`OWNS: src/foo.py, tests/test_foo.py`).
- Function `paths_overlap(p1, p2)` detects exact matches, directory prefix containment (e.g. `src/db` vs `src/db/models.py`), and glob intersections (`src/*.py` vs `src/main.py`).
- Function `schedule_waves()` groups runnable nodes into parallel execution waves where **no two nodes in the same wave touch overlapping paths**, preventing write collisions and dirty workspace reads.

### 9.2 The Persona vs Policy Boundary
- A `PersonaProfile` can specify `requested_tools: ["repository_read", "test_runner", "arbitrary_exec"]`.
- The `PolicyEngine` evaluates these against its configured `allowed_tools` and task-specific constraints.
- **Invariant**: The executing worker receives only `authorized_tools = policy.authorize(...)`. A persona prompt cannot grant permissions beyond the policy.

### 9.3 Strict Capability Routing vs Phantom Capabilities
- `BackendRegistry` registers models with concrete capability sets (`"technical_reasoning"`, `"code_analysis"`, `"system_design"`, `"formal_verification"`).
- `AgentRouter` requires `backend.supports(persona.required_capabilities)`.
- If no backend satisfies the requirement, the router raises `RoutingBlockedError`. It **never** silently dispatches to an under-capable model while pretending the persona prompt will compensate.

### 9.4 Failure Classification & Bounded Adaptation Matrix

| Failure Kind | Typical Signal | Persona Action | Backend Action | Switch Budget Impact |
|---|---|---|---|:---:|
| `INCOMPLETE_WORK` | Syntax errors, timeouts, unmet assertions | Retain persona; feed back decisive error snippet | Retain current backend | No switch consumed |
| `WRONG_APPROACH` | Flawed design, race condition, invariant violation | Increment version (`P-v2`); adapt methodology steps | Retain or upgrade backend | 1 switch consumed |
| `CAPABILITY_MISMATCH` | Reasoning exhaustion, unsupported complexity | Escalate required capabilities (`+system_design`) | Route to higher-tier backend | 1 switch consumed |
| `MISSING_DEPENDENCY` | Unresolved import, missing prerequisite node | Retain persona; expand task graph (`node.needs`) | Retain current backend | No switch consumed |
| `MISSING_PERMISSION` | Tool refused, unapproved command check | Retain persona; surface authorization blocker | Retain current backend | No switch consumed |

When `task.persona_switches >= max_persona_switches` (default: 2), adaptation freezes and the task fails cleanly rather than looping.

### 9.5 Atomic State Persistence (`StateStore`)
- State file writes in `StateStore.save(state, filepath)` write to a process-unique temporary file:
  `f"{filepath}.tmp.{pid}"`
- The file is closed and flushed before an atomic OS-level replacement (`os.replace(tmp, filepath)`).
- This guarantees that an abrupt process crash, power loss, or external kill signal never leaves a corrupt or half-written `state.json`.

### 9.6 Pre-Dispatch Manifest Gating (`InputManifest`)
- Before dispatching a task node to an executor, `DAFG.check_input_manifest(node)` validates all required input artifacts and interface contracts.
- If any required artifact is missing or stale (version < required), the dispatch is gated:
  - Worker execution is bypassed, preventing wasted tokens.
  - Missing prerequisite tasks are synthesized and added to `node.needs`.
  - Node is transitioned to `BLOCKED`.

### 9.7 Failure-Directed Repair & Targeted Transitive Invalidation (`RevisionDirective`)
- Replaces blind DAG restarts with diagnostic failure classification (`FailureClass`):
  - `LOCAL_DEFECT`: Revises only the local node.
  - `MISSING_PREREQUISITE`: Injects prerequisite node and links `needs`.
  - `STALE_DEPENDENCY`: Executes targeted transitive invalidation on affected descendants, incrementing node epochs.
  - `INTERFACE_MISMATCH`: Invalidates contract consumers and triggers contract repair.
  - `INSUFFICIENT_EVIDENCE`: Demotes gate evidence for escalated verification.

### 9.8 Versioned Shared Interface Contracts (`InterfaceContract`)
- Modules publish versioned contracts (`contract_id`, `version`, `input_schema`, `output_schema`, `invariants`).
- When a contract is updated:
  - If `compatibility_mode == "backward_compatible"`: existing consumers remain `ACCEPTED`.
  - If breaking: triggers targeted invalidation of consumers registered in `consumed_contracts`.

### 9.9 Layered Verification & Typed Evidence (`CriterionEvidence`, `EvidenceType`)
- Enforces multi-tier verification:
  1. Structural Checks: Manifest references resolve and versions are current.
  2. Executable Checks: Shell check commands with exit code 0 and decisive output match.
  3. Schema Validation: Structured payload validation against typed `Schema`.
  4. Escalated Invariant Checks: Contract invariants verified for contract owners.
- Criterion evidence is strictly typed (`TEST_RESULT`, `SCHEMA_VALIDATION`, `INVARIANT_CHECK`, `MODEL_JUDGMENT`). Model judgments cannot masquerade as executable tests.

### 9.10 Priority-Scored Wave Scheduling & Separated Wait Telemetry (`WaitMetrics`)
- Ready nodes are scored:
  `score = (depth * 1.5) + (downstream_count * 2.5) + (5.0 if is_contract_owner else 0.0) + (3.0 if has_revisions else 0.0)`
- Critical path nodes and contract owners execute in Wave 0, clearing bottlenecks for downstream workers.
- Wait telemetry isolates `dependency_wait_seconds`, `queue_wait_seconds`, and `conflict_wait_seconds`.

### 9.11 Adaptive Protocol Bypass & Conservative Safety Guards (`BypassPolicy`, `BypassTelemetry`)
- Trivial, single-file bugfixes bypass heavy multi-agent wave scheduling if and only if all 4 conservative guards pass:
  1. `files_touched <= 1` (no wildcards)
  2. `touches_shared_contract == False`
  3. `requires_permissions == False`
  4. `ambiguity_score <= 0.15`
- **Staged Isolation Inspection**: Post-execution diff inspects actual files modified. If more than 1 file is touched or contract invariants are violated, the fast path aborts, rolls back staging, and escalates to the full multi-agent protocol.
- **Shadow Audit Telemetry**: Audits a 10% sample of bypassed runs through full verification, measuring `bypass_rate`, `bypass_misroute_rate`, and `shadow_delta`.

### 9.12 Decoupled Execution Adapters & 5-Outcome Benchmark Architecture
- **Decoupled Agent Loops**: `IterativeCLIAdapter`, `ToolDispatchAdapter` (function-calling), and `ReActStateAdapter` (state-machine) verify true runtime transferability across decoupled agent architectures.
- **Independent Completion Claim**: Separates `completion_claim` (`SUCCESS`, `PARTIAL`, `BLOCKED`, `FAILED`) from external evaluation to prevent mischaracterizing acknowledged failures as hallucinations.
- **Standardized 5-Outcome Taxonomy**:
  1. `VERIFIED_SUCCESS`: Feasible task verified by external judge.
  2. `CORRECT_BLOCK`: Impossible task correctly refuted/blocked.
  3. `VERIFIED_FAILURE`: False claims or objective failures.
  4. `EVALUATION_ERROR`: Pre-flight ast-checked test fixture defect.
  5. `EXECUTION_ERROR`: Environment or harness crash.

---

## 10. Directory Structure & File Map

```text
dafg/
├── AGENTS.md                    # Agent instructions (Antigravity, Codex)
├── CLAUDE.md                    # Agent instructions (Claude Code)
├── CONTEXT.md                   # Project domain glossary & canonical terminology
├── GATES.md                     # Active acceptance gate ledger
├── pyproject.toml               # Packaging & script definitions (Hatchling + uv)
├── README.md                    # Installation & usage guide
├── dfag.py                      # Root compatibility shim & quick runner
├── state.json                   # DAFG graph execution state (atomic checkpoint)
├── .approved_gates.json         # Cryptographic approval store for gate checks
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
├── .github/
│   └── copilot-instructions.md  # GitHub Copilot workspace instructions
│
├── benchmarks/
│   ├── v02_regression/          # Frozen 40-task regression gate
│   └── v03/                     # v0.3 Difficulty Benchmark
│       ├── dev_set/             # Development tier (horizons, schema shifts)
│       ├── calibration_set/     # Calibration tier (hostile/flaky tools)
│       └── held_out_set/        # Frozen held-out tier (adversarial injections)
│
├── docs/
│   ├── LLD.md                   # This Low-Level Design document
│   └── STATE_MACHINE.md         # Formal state transition architecture spec
│
├── src/dafg/
│   ├── __init__.py              # Public API exports
│   ├── adapters.py              # Decoupled agent execution adapters (CLI, Dispatch, ReAct)
│   ├── adversarial.py           # Adversarial stress vectors and refusal dispatch
│   ├── cli.py                   # Unified CLI dispatcher (dafg, gates, stop-hook, eval, init)
│   ├── eval.py                  # Evaluation engine, metrics, and benchmark runner
│   ├── gates.py                 # GateLedger, ApprovalStore, GateEngine, GateLinter
│   ├── hook.py                  # CompletionGuard & stop hook evaluation logic
│   ├── init.py                  # Project scaffolding & agent interlock generator
│   ├── mutation.py              # Gate mutation testing & ledger adequacy verification
│   ├── persona.py               # PersonaCompiler, AgentRouter, PolicyEngine
│   ├── protocol.py              # 7-pillar protocol conformance auditor
│   ├── repair.py                # Failure-directed repair loop & self-healing
│   ├── runtime.py               # DAFG task graph, TaskNode, Budget, rolling waves, bypass
│   ├── schema.py                # Typed Schema, Field validators, robust JSON repair
│   ├── trends.py                # Benchmark regression & trend analysis engine
│   └── visual.py                # Automated visual verification & perceptual diff gates
│
└── tests/
    ├── test_adaptive_bypass.py          # Adaptive protocol bypass & safety guard tests
    ├── test_adversarial.py              # Adversarial injection & schema shift tests
    ├── test_boeing747.py                # Boeing 747 CAD validation test suite
    ├── test_dafg_budgets.py             # Budget caps and deadline tests
    ├── test_dafg_persistence.py         # State persistence and resume tests
    ├── test_dafg_runtime.py             # Dynamic graph scheduling and execution tests
    ├── test_dependency_correctness.py   # Pre-dispatch manifest gating & targeted repair tests
    ├── test_dependency_linter.py        # Dependency graph linter tests
    ├── test_depth_tree_waves.py         # Depth tree and wave scheduling tests
    ├── test_eval_and_adapters.py        # Evaluation engine & decoupled adapter tests
    ├── test_gates_execution.py          # Gate execution and reverification tests
    ├── test_gates_linter.py             # Ledger linter tests
    ├── test_gates_parser.py             # Markdown ledger parser tests
    ├── test_gates_security.py           # Approval store and security boundary tests
    ├── test_init.py                     # Project scaffolding & CLI init tests
    ├── test_layered_verification.py     # Layered verification & typed evidence tests
    ├── test_persona.py                  # Persona compilation and routing tests
    ├── test_protocol_conformance.py     # 7-pillar protocol audit tests
    ├── test_refusal_dispatch.py         # 5-class refusal dispatch tests
    ├── test_repair_loop.py              # Failure-directed repair loop tests
    ├── test_schema.py                   # Typed schemas and JSON repair tests
    ├── test_stop_hook.py                # Stop hook completion guard tests
    ├── test_stress_vectors.py           # Multi-vector stress and adversarial injection tests
    ├── test_trends.py                   # Benchmark regression trend tests
    └── test_visual_gates.py             # Visual gates & perceptual diff tests
```

