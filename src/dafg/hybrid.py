"""DeLM x DAFG hybrid: early-publish provisional artifacts, verify-at-gate on finals.

A producer stage publishes twice, reusing AECP machinery from dafg.artifacts:

  PROVISIONAL  a KnowledgeArtifact (status=PROVISIONAL) + a ContractArtifact v1
               carrying the already-stable interface (e.g. types/signatures).
  FINAL        a KnowledgeArtifact (status=FINAL). If the interface changed
               since the provisional, the contract is revise()d, which marks
               all registered consumers stale (AECP's existing rule). If the
               interface is unchanged, no revision happens and consumers stay
               fresh.

Rules (see docs/HYBRID_DESIGN.md):
  - speculative start: a consumer may start on PROVISIONAL and registers on
    the producer's contract;
  - stale re-sync: a changed FINAL marks the consumer stale; it must re-sync
    (re-run gate-relevant work, cost R) then acknowledge the new revision;
  - HARD INVARIANT: a provisional artifact can NEVER satisfy a gate.
    evaluate_gate() asserts artifact.status == FINAL. This is an assertion,
    not a comment: the hybrid cannot weaken verification by construction.

Only stdlib is used. All imports inside DAFG must be absolute
(``from dafg.hybrid import ...``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from dafg.artifacts import (
    ContractArtifact,
    ContractSymbol,
    KnowledgeArtifact,
    ScopeKind,
)


class ArtifactStatus(str, Enum):
    """Hybrid lifecycle status layered on a KnowledgeArtifact."""
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# Experiment cost model (virtual time units).
STAGE_DURATION = 100      # D: full stage work
PROVISIONAL_OFFSET = 50   # P: provisional emitted at local t=50
GATE_COST = 10            # G: gate evaluation cost
REWORK_COST = 40          # R: stale re-sync cost


@dataclass
class VersionedArtifact:
    """A KnowledgeArtifact plus its hybrid lifecycle status and interface."""
    artifact: KnowledgeArtifact
    status: ArtifactStatus
    interface: Tuple[str, ...] = ()

    @property
    def is_final(self) -> bool:
        return self.status == ArtifactStatus.FINAL


class HybridStore:
    """Harness-side provisional/final lifecycle built on AECP contracts.

    The contract carries the interface; a changed FINAL triggers revise(),
    which marks consumers stale. Re-sync = acknowledge() after paying the
    rework cost (accounted by the caller).
    """

    def __init__(self) -> None:
        # producer_id -> {"provisional": VersionedArtifact,
        #                 "final": Optional[VersionedArtifact],
        #                 "contract": ContractArtifact}
        self._producers: Dict[str, Dict[str, Any]] = {}
        self.rework_events: List[Tuple[str, str]] = []  # (producer, consumer)

    def publish_provisional(
        self,
        producer_id: str,
        claim: str,
        interface: Tuple[str, ...],
        scope: str = "",
    ) -> VersionedArtifact:
        """Publish the provisional artifact + v1 interface contract."""
        artifact = KnowledgeArtifact(
            claim=claim,
            scope_kind=ScopeKind.FILE,
            scope=scope or f"{producer_id}/output",
            producer=producer_id,
        )
        contract = ContractArtifact(
            module=producer_id,
            symbols=[ContractSymbol(name=s, kind="function") for s in interface],
            purpose=f"provisional interface of {producer_id}",
        )
        va = VersionedArtifact(artifact=artifact, status=ArtifactStatus.PROVISIONAL,
                               interface=tuple(interface))
        self._producers[producer_id] = {
            "provisional": va, "final": None, "contract": contract,
        }
        return va

    def register_consumer(self, producer_id: str, consumer_id: str) -> None:
        """A consumer starting speculatively on the provisional registers."""
        self._producers[producer_id]["contract"].register_consumer(consumer_id)

    def publish_final(
        self,
        producer_id: str,
        claim: str,
        interface: Tuple[str, ...],
        scope: str = "",
    ) -> Tuple[VersionedArtifact, Set[str]]:
        """Publish the final artifact.

        Returns (final_artifact, stale_consumers). Staleness is computed
        against the *last published* interface (the provisional on first
        publish): a changed interface bumps the contract revision and marks
        consumers stale; an unchanged interface — including a defect-redo
        final — leaves them fresh (no rework).
        """
        entry = self._producers[producer_id]
        artifact = KnowledgeArtifact(
            claim=claim,
            scope_kind=ScopeKind.FILE,
            scope=scope or f"{producer_id}/output",
            producer=producer_id,
        )
        va = VersionedArtifact(artifact=artifact, status=ArtifactStatus.FINAL,
                               interface=tuple(interface))
        prev_interface = entry.get("last_interface", entry["provisional"].interface)
        entry["final"] = va
        entry["last_interface"] = tuple(interface)
        stale: Set[str] = set()
        if tuple(interface) != prev_interface:
            stale = entry["contract"].revise(
                symbols=[ContractSymbol(name=s, kind="function") for s in interface],
                reason="final interface differs from last published interface",
            )
            for consumer_id in sorted(stale):
                self.rework_events.append((producer_id, consumer_id))
        return va, stale

    def resync(self, producer_id: str, consumer_id: str) -> None:
        """Consumer re-syncs to the revised contract (after paying rework)."""
        self._producers[producer_id]["contract"].acknowledge(consumer_id)

    def is_stale(self, producer_id: str, consumer_id: str) -> bool:
        return self._producers[producer_id]["contract"].is_stale(consumer_id)

    def rework_count(self) -> int:
        """Each (producer, consumer) stale marking counted exactly once."""
        return len(self.rework_events)


def evaluate_gate(artifact: VersionedArtifact,
                  checks: List[Callable[[], bool]]) -> bool:
    """Evaluate gate checks against an artifact.

    HARD INVARIANT: only FINAL artifacts may be gate-evaluated. A provisional
    artifact can never satisfy a gate — enforced by assertion, not convention.
    """
    assert artifact.is_final, (
        "HARD INVARIANT VIOLATION: provisional artifacts can never satisfy "
        f"a gate (got status={artifact.status.value})"
    )
    return all(check() for check in checks)


# ------------------------------------------------------- chain simulator ---

@dataclass
class StageSpec:
    """One chain stage: interface-change flag and defect flag (deterministic)."""
    changed: bool = False    # final interface differs from provisional
    defective: bool = False  # final carries a defect the gates must catch


@dataclass
class ChainOutcome:
    mode: str
    wall: float               # virtual time units to delivery
    rework_events: int
    false_completion: bool
    verified: bool            # all gates passed on finals
    gate_runs: int
    redos: int
    total_cost: float         # compute cost (work + rework + gates + redos)
    detail: Dict[str, Any] = field(default_factory=dict)


def _iface(tag: str, changed: bool) -> Tuple[str, ...]:
    return (f"{tag}_v2",) if changed else (f"{tag}_v1",)


def simulate_h1(stages: List[StageSpec]) -> ChainOutcome:
    """Barrier mode (today's DAFG): dependent starts after producer's gate pass."""
    store = HybridStore()
    t = 0.0
    gate_runs = 0
    redos = 0
    for i, spec in enumerate(stages):
        pid = f"stage{i}"
        store.publish_provisional(pid, f"provisional {pid}", _iface(pid, False))
        final_va, _ = store.publish_final(pid, f"final {pid}", _iface(pid, spec.changed))
        final_t = t + STAGE_DURATION
        gate_end = final_t + GATE_COST
        gate_runs += 1
        passed = evaluate_gate(final_va, [lambda: not spec.defective])
        if not passed:
            # Gate caught the defect: producer redoes the stage (interface
            # unchanged by a redo), gate re-runs and passes.
            redos += 1
            gate_runs += 1
            final_va2, stale2 = store.publish_final(pid, f"final-redo {pid}",
                                                    _iface(pid, spec.changed))
            assert not stale2, "redo must not change the interface"
            assert evaluate_gate(final_va2, [lambda: True])
            final_t = gate_end + STAGE_DURATION
            gate_end = final_t + GATE_COST
        t = gate_end  # barrier: next stage waits for this gate pass
    n_def = sum(1 for s in stages if s.defective)
    cost = len(stages) * STAGE_DURATION + gate_runs * GATE_COST + redos * STAGE_DURATION
    return ChainOutcome(mode="H1-barrier", wall=t, rework_events=0,
                        false_completion=False, verified=True,
                        gate_runs=gate_runs, redos=redos, total_cost=cost,
                        detail={"defects": n_def})


def _simulate_early(stages: List[StageSpec], mode: str,
                    with_gates: bool) -> ChainOutcome:
    """Shared early-publish pipeline for H2 (gates) and H3 (no gates).

    Consumers start speculatively at the producer's provisional. A changed
    FINAL marks the consumer stale -> rework (+REWORK_COST), then re-sync.
    Gates (H2 only) evaluate FINAL artifacts exclusively and run concurrently
    with downstream speculative work; a caught defect triggers a redo whose
    interface is unchanged (no new rework event).
    """
    store = HybridStore()
    n = len(stages)
    start = [0.0] * n
    shift = [0.0] * n          # accumulated rework delay per stage
    prov_t = [0.0] * n
    final_t = [0.0] * n
    finals: List[Optional[VersionedArtifact]] = [None] * n
    gate_runs = 0
    redos = 0

    for i, spec in enumerate(stages):
        pid = f"stage{i}"
        # All rework affecting stage i (from final_{i-1}) has already been
        # applied: final_{i-1} was published at the end of the previous
        # iteration, strictly before this stage's provisional emission
        # (prov_{i} - final_{i-1} = shift[i] - shift[i-1] >= 0).
        store.publish_provisional(pid, f"provisional {pid}", _iface(pid, False))
        if i < n - 1:
            # Consumer registers when it starts speculatively on this
            # provisional -- strictly BEFORE this stage's final is published.
            store.register_consumer(pid, f"stage{i+1}")
        prov_t[i] = start[i] + PROVISIONAL_OFFSET + shift[i]
        if i < n - 1:
            start[i + 1] = prov_t[i]  # speculative start
        final_t[i] = start[i] + STAGE_DURATION + shift[i]
        final_va, stale = store.publish_final(pid, f"final {pid}",
                                              _iface(pid, spec.changed))
        finals[i] = final_va
        for consumer_id in sorted(stale):
            j = int(consumer_id.replace("stage", ""))
            shift[j] += REWORK_COST
            store.resync(pid, consumer_id)

    rework_events = store.rework_count()

    if with_gates:
        gate_pass = [0.0] * n
        for i, spec in enumerate(stages):
            assert finals[i] is not None
            gate_end = final_t[i] + GATE_COST
            gate_runs += 1
            if not evaluate_gate(finals[i], [lambda: not spec.defective]):
                # Defect caught: redo with unchanged interface (no rework:
                # publish_final compares against the provisional interface,
                # which the redo keeps).
                redos += 1
                gate_runs += 1
                pid = f"stage{i}"
                final_va2, stale2 = store.publish_final(
                    pid, f"final-redo {pid}", _iface(pid, spec.changed))
                assert not stale2, "redo must not change the interface"
                assert evaluate_gate(final_va2, [lambda: True])
                gate_end = gate_end + STAGE_DURATION + GATE_COST
            gate_pass[i] = gate_end
        wall = max(gate_pass)
        verified = True
        false_completion = False
    else:
        # H3: no gates -> defects pass through unverified; no redos.
        wall = final_t[-1]
        verified = False
        false_completion = any(s.defective for s in stages)

    n_def = sum(1 for s in stages if s.defective)
    cost = (n * STAGE_DURATION + rework_events * REWORK_COST
            + gate_runs * GATE_COST + redos * STAGE_DURATION)
    return ChainOutcome(
        mode=mode, wall=wall, rework_events=rework_events,
        false_completion=false_completion, verified=verified,
        gate_runs=gate_runs, redos=redos, total_cost=cost,
        detail={"defects": n_def,
                "rework_per_stage": [shift[i] / REWORK_COST if REWORK_COST else 0
                                     for i in range(n)]},
    )


def simulate_h2(stages: List[StageSpec]) -> ChainOutcome:
    """Hybrid: early-publish + re-sync + gates on FINAL only."""
    return _simulate_early(stages, "H2-hybrid", with_gates=True)


def simulate_h3(stages: List[StageSpec]) -> ChainOutcome:
    """DeLM-pure analog: early-publish + re-sync on change, NO gate verification."""
    return _simulate_early(stages, "H3-early-no-gates", with_gates=False)


SIMULATORS = {
    "H1-barrier": simulate_h1,
    "H2-hybrid": simulate_h2,
    "H3-early-no-gates": simulate_h3,
}
MODES = ("H1-barrier", "H2-hybrid", "H3-early-no-gates")
