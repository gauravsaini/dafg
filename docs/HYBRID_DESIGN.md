# DeLM × DAFG Hybrid: Early-Publish + Verify-at-Gate

## Problem

DAFG today is barrier-style: a dependent node starts only after its
dependency's gates pass on the final artifact. DeLM's insight (Yuzhen Mao et
al., alphaxiv 2606.10662): publish *usable intermediates early* so dependents
start before the subtask completes, killing "bubbles" (wait time).

The hybrid takes DeLM's speed without giving up DAFG's trust.

## Lifecycle

Each producer stage publishes twice, reusing AECP machinery:

1. **PROVISIONAL** — a `KnowledgeArtifact` (status=PROVISIONAL) plus a
   `ContractArtifact` v1 carrying the interface (the part of the output that
   is already stable, e.g. types/signatures at ~50% of the work).
2. **FINAL** — a `KnowledgeArtifact` (status=FINAL). If the interface changed
   since the provisional, the contract is `revise()`d (v2), which marks all
   registered consumers stale — exactly AECP's existing stale-consumer rule.
   If the interface is unchanged, no revision happens and consumers stay fresh.

## Rules

- **Speculative-start rule.** A consumer may start when the producer's
  PROVISIONAL is published. On start it `register_consumer()`s on the
  producer's contract.
- **Stale-re-sync rule.** When the producer publishes FINAL with a changed
  interface, the consumer is marked stale and must re-sync: re-run its
  gate-relevant work against the final artifact (cost R in the experiment).
  It then `acknowledge()`s the new revision. Unchanged interface → no
  re-sync, no cost.
- **Gates-require-final invariant (HARD, non-negotiable).** A provisional
  artifact can NEVER satisfy a gate. `evaluate_gate()` asserts
  `artifact.status == FINAL` — encoded as an assertion, not a comment.
  The hybrid cannot weaken verification by construction: every delivery
  still requires gates passing on final artifacts, exactly as in barrier DAFG.

## Rework accounting

A **rework event** = one consumer marked stale by one changed FINAL publish.
Counted exactly once per (changed provisional, consumer) pair. Interface-
unchanged finals and defect-redo finals (interface identical) generate no
rework event.

## Cost model (experiment)

Virtual time units. Per stage: duration D=100, provisional emitted at local
t=50, gate cost G=10 (concurrent with downstream work in early-publish
modes), rework cost R=40, defect redo +D (interface unchanged by redo).

- **H1 barrier** (today's DAFG, control): dependent starts at producer's gate
  pass. No rework. Wall = N·(D+G) + redo costs.
- **H2 hybrid**: speculative start at provisional; re-sync on changed final;
  gates on final only (asserted). Wall < H1 when changes are rare; rework
  erodes the gain as the change-rate rises.
- **H3 early-no-gates** (DeLM-pure analog): speculative start + re-sync on
  change (corrections are visible, as in DeLM's shared context), but NO gate
  verification. Isolates the gates' contribution: H2−H3 = what gates add
  when early-publish is held constant.

## What the experiment measures

The tradeoff curve: provisional-change-rate (0 / 0.25 / 0.5) on the x-axis;
H2 speedup vs H1 and rework-rate on the y-axis. Expected: H2 FCR == H1 FCR
(trust kept), H2 wall < H1 wall (DeLM speed), H3 FCR > 0 (what no-gates costs).
Break-even analysis: at R=40 < P=50 (provisional offset), rework can erode
but not eliminate the pipeline gain within 0–100% change; R* = 60/change
would zero it.
