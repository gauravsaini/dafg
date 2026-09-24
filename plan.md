# DAFG Product Direction Plan

## 0. Plan Intent

DAFG ka current validated wedge **completion-integrity control plane for autonomous coding agents** hai.

Primary promise:

> Agent autonomous tareeke se kaam kar sakta hai, lekin objective, independent evidence ke bina success claim nahi kar sakta.

This plan deliberately separates:

1. **DO FIRST**: Jo capabilities existing evidence se justified hain.
2. **DECISION GATES**: Har phase ke measurable exit criteria.
3. **PICKUP LATER**: Jo items abhi avoid karne hain, lekin validation ke baad selectively promote kiye ja sakte hain.

Streaming, organism evolution, aur broader distributed-agent claims ko product thesis nahi maana jayega jab tak unke liye workload-level evidence nahi milta.

---

## 1. Canonical Product Direction

### 1.1 Product identity

DAFG ko is form mein treat karo:

> **A verification and completion-control runtime for autonomous coding agents.**

Initial target user:

- Engineering-platform teams running coding agents in CI, pull-request automation, or internal developer tooling.

Initial buyer pain:

- False completion claims.
- Unverified code changes.
- Impossible work being retried instead of refused.
- Multi-agent work producing unclear ownership and weak audit trails.
- No durable evidence explaining why an autonomous run was accepted.

### 1.2 Scope decision

- `GOAL.md` must stop describing the Boeing 747 simulator as the active project goal.
- DAFG framework documentation, benchmark goals, and roadmap must share one product direction.
- Boeing/Three.js material is out of scope for this product plan unless explicitly reintroduced as a separate project.

### 1.3 Product boundary

DAFG owns:

- Task/dependency execution control.
- Gate definition and execution.
- Evidence attribution and replay.
- Completion blocking and honest refusal.
- Bounded repair and run-level auditability.

DAFG does not initially own:

- Model serving.
- Universal token transport.
- General-purpose agent communication.
- Autonomous software generation quality without an independent oracle.

---

## 2. Phase 0: Lock Product Identity

### Objective

Remove strategic ambiguity before more feature work is started.

### Work items

- Replace the active project goal with the completion-integrity product thesis.
- Update README positioning, CLI description, and roadmap language to match.
- Define one canonical ICP and one initial workflow: autonomous coding agents operating on repository tasks and CI/PR verification.
- Document the product boundary between DAFG, agent adapters, model backends, and external ground-truth oracles.
- Mark streaming as an optional performance experiment, not a core product pillar.
- Add a short decision record explaining why the current product is verification-first.

### Exit criteria

- No active top-level document describes a conflicting product goal.
- One sentence explains the product, user, buyer, and failure mode.
- Every roadmap item maps to either completion integrity, execution control, evidence, or a measurable accelerator experiment.

### Decision

- **PASS**: Continue to Phase 1.
- **FAIL**: Stop feature development and resolve product scope.

---

## 3. Phase 1: Prove the Core Control-Plane Wedge

### Objective

Show that DAFG creates value even without streaming or self-evolution.

### Comparison modes

Run the same representative coding tasks through:

1. Baseline agent without DAFG.
2. Agent with DAFG batch execution and gate verification.
3. Agent with DAFG plus an independent external oracle.

Use fixed task inputs, model/backend versions, seeds where possible, and reproducible run manifests.

### Work items

- Select 50-100 realistic repository tasks.
- Include multi-file changes, integration behavior, dependency changes, concurrency, malformed inputs, and impossible requirements.
- Include both happy-path and deliberately defective agent attempts.
- Keep the external oracle independent from `GATES.md`, internal judge scoring, and agent-generated tests.
- Record run ID, commit, benchmark version, model/backend, seed, command, oracle version, and environment digest.
- Report outcomes per task, not only aggregate score.

### Required metrics

- External verified-delivery rate.
- False-completion rate.
- Correct-block rate for impossible or unauthorized work.
- Internal score versus external oracle discrepancy.
- Human intervention rate.
- Repair success rate.
- Cost per accepted delivery.
- Wall-clock time to trustworthy result.
- Evidence coverage and evidence strength.

### Minimum decision threshold

DAFG batch mode must demonstrate a clear improvement over baseline in at least two of these areas without materially degrading external verified delivery:

- False completion.
- Correct blocking.
- External verified delivery.
- Human intervention.
- Cost per accepted delivery.

### Exit criteria

- Independent oracle exists for every benchmark family.
- Baseline and DAFG results are paired on the same tasks.
- Results include confidence intervals or repeated-run variance where applicable.
- Any discrepancy above 10 percentage points is explained or treated as a failure.

### Decision

- **PASS**: DAFG verification/control plane is a validated product wedge; continue to Phase 2.
- **PARTIAL**: Keep the product narrow and improve the weakest control-plane mechanism.
- **FAIL**: Revisit the problem statement before adding orchestration or streaming complexity.

---

## 4. Phase 2: Make Evidence Trustworthy

### Objective

The product cannot sell completion integrity while its own benchmark and telemetry artifacts are ambiguous.

### Work items

- Create a single benchmark run manifest format.
- Bind every result to source commit, benchmark revision, command, model/backend, environment, and oracle revision.
- Separate historical artifacts, negative-test artifacts, and current authoritative results.
- Reconcile README numbers with stored ground-truth artifacts.
- Prevent `COMPLETE` or `VERIFIED_DELIVERY` labels when evidence strength is `NONE`.
- Treat missing traces, zero-duration telemetry, and stale artifacts as explicit evaluation errors.
- Add independent discrepancy reporting to every evaluation summary.
- Track false accepts and false rejects for the verifier.
- Report sample size, variance, and confidence intervals instead of only point estimates.

### Evidence rules

- Internal gate pass is not equivalent to external delivery success.
- A model judgment cannot be reported as executable proof.
- A generated test is not independent ground truth.
- A missing artifact is not a passing result.
- Historical data must not silently mix with current benchmark data.

### Exit criteria

- Every published benchmark result is reproducible from its manifest.
- No authoritative report contains `COMPLETE` with `evidence_strength: NONE`.
- Internal score and external pass rate are shown together.
- Verifier false-accept and false-reject rates are measurable.

### Decision

- **PASS**: Use this evidence pipeline for all later product decisions.
- **FAIL**: Freeze roadmap claims; fix evaluation integrity first.

---

## 5. Phase 3: Improve Control-Plane Economics Before Streaming

### Objective

Address the measured bottlenecks that streaming does not directly solve.

### Priority order

#### 5.1 Context and decomposition

- Measure wrong decomposition and insufficient-context incidents.
- Add pre-dispatch context completeness checks.
- Compare expert-authored graph, generated graph, and repaired graph.
- Measure wasted tokens and repair yield by failure class.

#### 5.2 Interface and contract flow

- Measure interface mismatches before and after contract validation.
- Define which contracts are stable enough for downstream execution.
- Reject stale or incomplete inputs before model execution.
- Track invalidation fan-out and repair success.

#### 5.3 Shared-file coordination

- Measure ownership contention as a first-class product cost.
- Distinguish true write conflicts from test/integration artifacts that can be shared read-only.
- Compare serial ownership, interface seams, patch queues, and post-merge integration tasks.
- Do not claim concurrency improvement merely because more worker threads exist.

#### 5.4 Repair economics

- Measure marginal success probability for each retry/revision attempt.
- Stop retries when expected repair yield is lower than its cost.
- Separate local defects, missing prerequisites, stale dependencies, interface mismatches, and verifier failures.

### Required metrics

- Queue wait versus service time.
- Dependency, queue, and conflict wait separately.
- Concurrency ratio and actual wall-clock speedup.
- Wasted tokens by failure class.
- Repair yield by attempt number.
- Contract mismatch rate.
- Context-block rate.
- External delivery rate after repair.

### Exit criteria

- Top three control-plane bottlenecks are ranked with measured impact.
- At least one non-streaming intervention improves cost or latency on realistic tasks.
- No intervention increases false completion or decreases external verified delivery.
- Shared-file contention has a chosen operating model instead of automatic serial fallback everywhere.

### Decision

- **PASS**: Proceed to selected accelerator experiments.
- **FAIL**: Keep investment in control-plane fundamentals; do not promote streaming.

---

## 6. Phase 4: Selective Pickup From Deferred Items

This phase contains the items previously marked **DO NOT DO YET**. They are not permanently rejected. Each must earn promotion through evidence.

### 6.1 Streaming early-abort experiment

**Pickup only if:** Phase 1 confirms generation waste or recovery latency is a material customer problem and Phase 3 shows control-plane bottlenecks are not the dominant cause.

Use the existing transport, duplex adapter, and token inspector as an experiment surface.

Compare batch verification with streaming interception on:

- Early ownership violations.
- Forbidden imports or APIs.
- Syntax failures.
- Invalid tool calls.
- Stale dependency invalidation.
- Interface mismatches.
- Late-stage test failures.

Measure:

- Tokens generated after earliest detectable defect.
- Tokens actually avoided by abort.
- Abort latency p50/p95/p99.
- Model cancellation latency.
- False-abort rate.
- Recovery success rate.
- Net wall-clock change.
- Streaming CPU, memory, serialization, and scheduler overhead.
- Behavior under dropped, duplicated, reordered, and stale frames.

#### Streaming promotion gate

Promote streaming beyond experiment status only if all are true:

- At least 20% net token or wall-clock improvement on realistic tasks.
- External verified-delivery rate does not regress materially.
- False-abort rate is acceptably low and explicitly reported.
- Cancellation is reliable on at least one real backend.
- Improvement survives repeated runs and is not limited to synthetic token streams.
- At least one target customer/workflow requires the latency or cost benefit.

If any condition fails, keep streaming behind a flag and stop expanding the transport surface.

### 6.2 Streaming challenger and barge-in

Pickup only after early-abort economics are proven.

Start with one invariant class and one backend. Do not begin with universal AST, tool-call, and gate interception.

Required safeguards:

- Conservative detection with explicit false-positive tests.
- Epoch fencing and stale-result rejection.
- Backpressure behavior.
- Duplicate and out-of-order control signal handling.
- Deterministic replay of the abort decision.

### 6.3 Speculative execution and prefill

Do not assume byte-level token compatibility means semantic or KV-cache compatibility.

Pickup only for a specific model/backend pair with measurable support.

Required evidence:

- Prefill hit rate.
- Rollback rate.
- Wasted prefill compute.
- Net TTFT improvement.
- Compatibility and failure behavior.

No cross-provider KV-cache claim without provider-specific proof.

### 6.4 Organism and self-evolution claims

Keep organism/evolution as an internal research mode until goal-to-delivery behavior is independently validated.

Promotion requires:

- Reliable decomposition across diverse real tasks.
- Independent external oracle coverage.
- No generic stub or self-referential test escape.
- Measurable improvement over a fixed DAFG configuration.
- Bounded cost and predictable failure behavior.

Until then, market the verified execution runtime, not an autonomous software organism.

### 6.5 Broader multi-agent mesh

Do not generalize to a universal distributed-agent mesh unless a specific workflow requires it.

First prove the single-repository coding-agent workflow. Expand only when:

- A real integration requires cross-process coordination.
- The protocol reduces a measured cost.
- The additional operational complexity has a clear owner and rollback path.

---

## 7. Explicit Non-Goals For This Cycle

- No universal model-serving abstraction.
- No claim of portable KV-cache prefill across providers.
- No full-duplex mesh as the product headline.
- No autonomous evolution claim based only on internal judge score.
- No benchmark claim without independent oracle and provenance.
- No optimization based only on synthetic in-process timing.
- No expansion of persona machinery unless it improves external delivery or cost.

---

## 8. Decision Log Template

Every phase decision must record:

- Decision date.
- Phase and experiment version.
- Hypothesis.
- Workload set and sample size.
- Baseline and treatment definitions.
- Metrics and thresholds.
- Observed result.
- Decision: `PROMOTE`, `HOLD`, `NARROW`, or `DROP`.
- Follow-up owner and next validation.

---

## 9. Immediate Next Steps

1. Resolve the canonical product goal and documentation conflict.
2. Define the initial ICP and repository-task workflow.
3. Create the paired baseline/DAFG benchmark plan with an independent oracle.
4. Define the benchmark manifest and provenance format.
5. Run Phase 1 before adding more streaming capabilities.
6. Rank Phase 3 bottlenecks from measured data.
7. Revisit streaming only through the Phase 4 promotion gate.

## Final Direction

**DO first:** prove and harden verified completion control.

**DO later if earned:** streaming early abort, targeted barge-in, backend-specific prefill, organism evolution, or broader mesh.

**Do not do now:** make any deferred capability the product thesis before its customer value and operational economics are demonstrated.
