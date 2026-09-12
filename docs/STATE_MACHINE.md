# DAFG Formal State Transition Architecture Specification

> **Location**: `docs/STATE_MACHINE.md`  
> **Applicable Version**: DAFG v0.3+  
> **Source Modules**: `src/dafg/protocol.py`, `src/dafg/runtime.py`, `src/dafg/adapters.py`, `src/dafg/gates.py`

---

## 1. System Overview: Dual-State Architecture

DAFG decouples task coordination into two orthogonal, synchronized state spaces:

1. **Authoritative Epistemic & Evidence FSM (`ProtocolState`)**:
   - Manages reasoning stages, artifact proposals, adversarial challenges, gate verification evidence, epoch versioning, transitive invalidation, and cryptographic sealing.
   - Evaluated by the pure decision engine `ProtocolEngine.decide(graph, cmd)` and applied deterministically by `ProtocolReducer.apply(graph, event)`.
2. **Scheduler Execution Projection (`ExecutionStatus` / `NodeStatus`)**:
   - Manages scheduler dispatch queues, worker thread claims, asynchronous I/O waiting, and wave scheduling.
   - Synchronized deterministically via `state_projection(protocol_state)`.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          TWO-DIMENSIONAL STATE SEPARATION                              │
│                                                                                        │
│   Authoritative Protocol Lifecycle (ProtocolState)                                     │
│   IDLE ──► CONTEXT_LOADED ──► PROVING ◄───► CHALLENGING ──► VERIFYING ──► ACCEPTED     │
│     ▲           │                │                              │             │        │
│     │           ▼                ▼                              ▼             ▼        │
│     └─────── REJECTED ◄──────────┴──────────────────────────────┴──────► STALE (epoch++)│
│                                                                                        │
│   Scheduler / Dispatch Projection (ExecutionStatus)                                    │
│   READY ───────────► RUNNING ───────────► WAITING_IO ───────────► SETTLED              │
│     ▲                   │                                                              │
│     └──── BLOCKED ◄─────┘                                                              │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. The Complete Authoritative Node FSM (`ProtocolState`)

The authoritative protocol state machine implements the formal 9-pillar execution discipline:

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
    PROVING --> PROVING : DISPATCH_PROVE / FASTPATH [retry]
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
    STALE --> STALE : INVALIDATE [repeated cascade]

    ACCEPTED --> STALE : INVALIDATE [upstream REVISE_SUPERSEDES / schema drift / epoch++]
    ACCEPTED --> REJECTED : REJECT [post-acceptance audit defect]
    ACCEPTED --> REVISING : REVISE [post-acceptance repair]
    ACCEPTED --> IDLE : BLOCK [re-verification needed]
    DEGRADED --> STALE : INVALIDATE [upstream invalidation]

    REJECTED --> IDLE : REOPEN [repair wave initiated]
    REJECTED --> CONTEXT_LOADED : LOAD_CONTEXT [re-contextualized repair]
    REJECTED --> PROVING : DISPATCH_PROVE / FASTPATH [direct retry]
    REJECTED --> REVISING : REVISE [repair directive applied]
    REJECTED --> REJECTED : FAIL [terminal rejection]

    ACCEPTED --> [*] : SEAL_RUN [G_seal: completion integrity verified]
```

---

## 3. Two-Dimensional State Mapping & Scheduler Projection

DAFG maintains strict deterministic synchronization between the authoritative protocol FSM and scheduler state:

```
+------------------------------------+--------------------------------------------------+------------------------------------+
| ProtocolState (Authoritative)      | ExecutionStatus (Scheduler Projection)           | Legacy NodeStatus                  |
+------------------------------------+--------------------------------------------------+------------------------------------+
| IDLE                               | READY       (Eligible for wave dispatch)         | PENDING                            |
| CONTEXT_LOADED                     | READY       (Eligible for execution)             | READY                              |
| PROVING                            | RUNNING     (Worker actively executing)          | RUNNING                            |
| CHALLENGING                        | RUNNING     (Adversarial review in progress)     | RUNNING                            |
| VERIFYING                          | WAITING_IO  (Running gate oracles / checks)      | RUNNING                            |
| REVISING                           | BLOCKED     (Awaiting revision plan / budget)    | REJECTED                           |
| STALE                              | BLOCKED     (Awaiting re-dispatch after drift)   | READY                              |
| ACCEPTED                           | SETTLED     (Terminal success for this epoch)    | ACCEPTED                           |
| DEGRADED                           | SETTLED     (Authorized partial outcome)         | ACCEPTED                           |
| REJECTED                           | SETTLED     (Terminal rejection / repair candidate)| REJECTED                        |
+------------------------------------+--------------------------------------------------+------------------------------------+
```

### Scheduler Lifecycle Projection (`ExecutionStatus`)

```mermaid
stateDiagram-v2
    state "Scheduler Projection (ExecutionStatus)" as Scheduler {
        [*] --> READY : Dependencies Met (needs satisfied)
        READY --> RUNNING : Wave Dispatch / Worker Claim
        RUNNING --> WAITING_IO : Submit Proposal / Gate Execution
        WAITING_IO --> RUNNING : Counter-Evidence / Retry
        WAITING_IO --> SETTLED : Verdict Accepted (ACCEPTED / DEGRADED)
        RUNNING --> BLOCKED : Revision Directive / Pre-Dispatch Block / Invalidation
        BLOCKED --> READY : Dependencies Re-Satisfied / Epoch Bumped
        RUNNING --> SETTLED : Terminal Refusal (REJECTED / FAILED)
        SETTLED --> BLOCKED : Upstream Invalidation (T10 STALE Cascade)
    }
```

---

## 4. Pre-Dispatch Gates & Manifest Validation

Before a task transitions from `IDLE` / `READY` into `RUNNING` (`DISPATCHED`), it must pass through deterministic pre-dispatch gates:

```mermaid
flowchart TD
    SelectNode["TaskNode Ready in Queue"] --> ManifestCheck{"Input Manifest Valid?\n(files exist, contracts match)"}
    
    ManifestCheck -- No --> InjectDep["Create specialist node to supply input\nAdd to node.needs"]
    InjectDep --> BlockPreDispatch["commit_transition(BLOCKED)\naction=PRE_DISPATCH_BLOCKED"]

    ManifestCheck -- Yes --> AuthCheck{"requires_permissions and\nnot metadata.authorized?"}
    AuthCheck -- Yes --> BlockAuth["RefusalClass.MISSING_AUTHORIZATION\ncommit_transition(BLOCKED)\naction=PRE_DISPATCH_BLOCKED_UNAUTHORIZED"]

    AuthCheck -- No --> ContraCheck{"Contract Contradictions or\nmetadata.has_contradiction?"}
    ContraCheck -- Yes --> BlockContra["RefusalClass.CONTRADICTORY_REQUIREMENTS\ncommit_transition(BLOCKED)\naction=PRE_DISPATCH_BLOCKED_CONTRADICTORY"]

    ContraCheck -- No --> CapCheck{"Required Capabilities\nUnsupported or is_impossible?"}
    CapCheck -- Yes --> BlockCap["RefusalClass.UNAVAILABLE_CAPABILITY\ncommit_transition(BLOCKED)\naction=PRE_DISPATCH_BLOCKED_IMPOSSIBLE"]

    CapCheck -- No --> StampDispatch["Stamp Immutable DispatchIdentity:\n(run_id, node_id, epoch, attempt_id,\ncontext_snapshot_id, contract_version)"]
    StampDispatch --> DispatchCommit["commit_transition(RUNNING)\naction=DISPATCHED\nactive_dispatch = DispatchIdentity"]
```

---

## 5. Stress Vector 1: Cross-Paradigm Schema Coercion

In heterogeneous pipelines, output artifacts cross architectural boundaries via `BaseRuntimeAdapter.coerce_response`:

```mermaid
flowchart TD
    subgraph CLI ["1. Iterative CLI Adapter"]
        CLI_Out["Raw Text Stdout Envelope\n(commands_run, exit_code)"]
        CLI_Vuln["Vulnerability:\nHostile Shell Flakiness (Exit Code 1)"]
    end

    subgraph TD ["2. Tool Dispatch Adapter"]
        TD_Out["Structured Tool Calls\n(tool_calls_count, arguments dict)"]
        TD_Vuln["Vulnerability:\nSchema Mutation (SchemaValidationError)"]
    end

    subgraph ReAct ["3. ReAct State Machine Adapter"]
        ReAct_Out["Thought-Action-Observation Trace\n(state_trace list)"]
        ReAct_Vuln["Vulnerability:\nHorizon Turn Budget Exhaustion"]
    end

    CLI_Out -- "parse_stdout → tool_calls_count" --> TD_Out
    TD_Out -- "wrap into trace observation" --> ReAct_Out
    CLI_Out -- "raw text → trace observation" --> ReAct_Out
    ReAct_Out -- "extract action calls" --> TD_Out
    ReAct_Out -- "flatten trace to text" --> CLI_Out
    TD_Out -- "flatten calls to text" --> CLI_Out
```

### Transitive Invalidation across Heterogeneous Boundaries
When an upstream node undergoes invalidation (`T10: ACCEPTED → STALE`), the invalidation wave cascades across downstream consumers regardless of their adapter paradigm:

$$\text{upstream (CLI)} \xrightarrow{\text{INVALIDATE}} \text{mid (ToolDispatch)} \xrightarrow{\text{STALE}} \text{leaf (ReAct)} \xrightarrow{\text{STALE}}$$

---

## 6. Stress Vector 2: KillSwitch Loop Pruning

Inside `ReActStateAdapter.invoke`, before the reasoning horizon exhausts the node's token budget:

```mermaid
flowchart TD
    TurnStart["Turn Execution"] --> ObsCheck["Evaluate Observation\n(obs == 'Step passed')"]
    ObsCheck -- "Progress" --> Reset["Reset consecutive_no_progress = 0"] --> Continue["Next Turn"]
    ObsCheck -- "No Progress" --> Inc["consecutive_no_progress++\nspeculative_turns++"]

    Inc --> CheckKillN{"kill_n > 0 and\nconsecutive >= kill_n?"}
    CheckKillN -- Yes --> AbortKillN["Abort: status=FAILED\nerror=KILLSWITCH_KILL_N"]
    CheckKillN -- No --> CheckTheta{"spec_gap_θ > 0.0 and\nspeculative / turns > θ?"}
    CheckTheta -- Yes --> AbortTheta["Abort: status=FAILED\nerror=KILLSWITCH_SPEC_GAP"]
    CheckTheta -- No --> Continue
```

- **`kill_n`**: Aborts when $N$ consecutive turns yield zero progress (e.g., repeating the same failed command).
- **`spec_gap_theta` ($\theta$)**: Aborts when the ratio of speculative turns to total turns exceeds $\theta \in (0.0, 1.0]$.
- **Token Savings**: Prunes dead-end loops early, reducing token consumption on unrecoverable tasks.

---

## 7. Stress Vector 3: Adversarial Invalidation Injection & Mid-Flight Preemption

When an upstream revision emits `REVISE_SUPERSEDES`, active execution frames running against obsolete context are rejected by `DispatchIdentity` epoch fencing:

```mermaid
sequenceDiagram
    autonumber
    participant Upstream as Upstream Producer
    participant Engine as ProtocolEngine
    participant Reducer as ProtocolReducer
    participant Worker as Downstream Worker (In-Flight)

    Note over Upstream,Worker: Both nodes ACCEPTED at epoch=1
    Upstream->>Engine: submit_command(INVALIDATE, epoch_bump=True)
    Engine->>Reducer: DomainEvent(NODE_INVALIDATED, to_state=STALE, epoch=2)
    Reducer->>Upstream: protocol_state = STALE, epoch = 2
    Reducer->>Worker: Cascade: protocol_state = STALE, epoch = 2

    Note over Worker: Worker was computing under epoch=1; submits result
    Worker->>Engine: submit_command(ACCEPT_VERDICT, epoch=1)
    Note over Engine: G_fence check: proposal.epoch (1) != active.epoch (2)
    Engine-->>Worker: AuditRecord(REJECTED, reason='Stale epoch / Dispatch mismatch')
    Note over Worker: Obsolete execution frame dropped; no state corruption
```

---

## 8. Runnable Acceptance Gate Ledger FSM (`GATES.md`)

Gates in `GATES.md` provide deterministic, verifiable proof of node outcomes:

```mermaid
stateDiagram-v2
    [*] --> PENDING : Gate Defined in GATES.md

    PENDING --> UNAPPROVED : Command Not in .approved_gates.json
    UNAPPROVED --> PENDING : uv run gates --approve GATES.md

    PENDING --> MET : uv run gates --run / --reverify [exit=0, match=EXPECT]
    PENDING --> UNVERIFIED : Check Failed (non-zero exit / mismatch)

    MET --> UNVERIFIED : Upstream Invalidation (REVISE_SUPERSEDES)
    UNVERIFIED --> MET : Re-run & Passing Evidence

    PENDING --> ABANDONED : Explicit Non-Empty Reason (Terminal Handoff)
    UNVERIFIED --> ABANDONED : Explicit Non-Empty Reason (Terminal Handoff)

    MET --> [*] : Stop Hook Allows (All Gates MET or ABANDONED)
```
