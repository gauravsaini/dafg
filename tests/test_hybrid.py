"""Unit tests for the DeLM x DAFG hybrid (src/dafg/hybrid.py).

Covers the hard invariant (provisional can never satisfy a gate), the
stale/re-sync lifecycle, exact rework accounting, and the mode-level
properties the experiment relies on.
"""

import pytest

from dafg.hybrid import (
    ArtifactStatus,
    HybridStore,
    StageSpec,
    evaluate_gate,
    simulate_h1,
    simulate_h2,
    simulate_h3,
)


def _stages(changed=(False, False, False), defective=(False, False, False, False)):
    return [StageSpec(changed=changed[i] if i < 3 else False, defective=defective[i])
            for i in range(4)]


# ------------------------------------------------- the hard invariant ---

def test_provisional_never_satisfies_gate():
    store = HybridStore()
    prov = store.publish_provisional("p", "claim", ("api_v1",))
    assert prov.status == ArtifactStatus.PROVISIONAL
    with pytest.raises(AssertionError, match="provisional artifacts can never satisfy"):
        evaluate_gate(prov, [lambda: True])


def test_final_satisfies_gate_when_checks_pass():
    store = HybridStore()
    store.publish_provisional("p", "claim", ("api_v1",))
    final, _ = store.publish_final("p", "claim", ("api_v1",))
    assert evaluate_gate(final, [lambda: True]) is True
    assert evaluate_gate(final, [lambda: True, lambda: False]) is False


# ------------------------------------------------- stale / re-sync ---

def test_stale_resync_fires_on_changed_final():
    store = HybridStore()
    store.publish_provisional("p", "claim", ("api_v1",))
    store.register_consumer("p", "c")
    _, stale = store.publish_final("p", "claim", ("api_v2",))
    assert stale == {"c"}
    assert store.is_stale("p", "c")
    store.resync("p", "c")
    assert not store.is_stale("p", "c")


def test_no_resync_on_unchanged_final():
    store = HybridStore()
    store.publish_provisional("p", "claim", ("api_v1",))
    store.register_consumer("p", "c")
    _, stale = store.publish_final("p", "claim", ("api_v1",))
    assert stale == set()
    assert not store.is_stale("p", "c")
    assert store.rework_count() == 0


def test_rework_counted_exactly_once_per_changed_provisional():
    store = HybridStore()
    store.publish_provisional("p", "claim", ("api_v1",))
    store.register_consumer("p", "c1")
    store.register_consumer("p", "c2")
    store.publish_final("p", "claim", ("api_v2",))
    assert store.rework_count() == 2  # one per (producer, consumer)
    # A defect-redo final with unchanged interface adds no rework.
    _, stale2 = store.publish_final("p", "claim-redo", ("api_v2",))
    assert stale2 == set()
    assert store.rework_count() == 2


# ------------------------------------------------- mode properties ---

def test_barrier_never_starts_early():
    # H1 wall with no defects: 4 stages, each 100 work + 10 gate before the
    # next stage starts (the last gate included: delivery needs it).
    out = simulate_h1(_stages())
    assert out.wall == 4 * (100 + 10)
    assert out.rework_events == 0


def test_h2_faster_than_h1_at_zero_change_no_defect():
    h1 = simulate_h1(_stages())
    h2 = simulate_h2(_stages())
    assert h2.wall < h1.wall
    assert h2.rework_events == 0


def test_h2_keeps_trust_identical_to_h1():
    # Defective stage: both gated modes catch it (redo), zero false completion.
    stages = _stages(defective=(False, True, False, False))
    h1 = simulate_h1(stages)
    h2 = simulate_h2(stages)
    assert h1.redos == 1 and h2.redos == 1
    assert not h1.false_completion and not h2.false_completion
    assert h1.verified and h2.verified


def test_h3_false_completes_on_defect():
    stages = _stages(defective=(False, True, False, False))
    h3 = simulate_h3(stages)
    assert h3.false_completion
    assert not h3.verified
    assert h3.redos == 0  # no gates -> no redo


def test_h2_rework_erodes_but_keeps_speedup():
    # All interfaces change: 3 rework events, still faster than barrier.
    stages = _stages(changed=(True, True, True))
    h1 = simulate_h1(stages)
    h2 = simulate_h2(stages)
    assert h2.rework_events == 3
    assert h2.wall == 260 + 3 * 40  # base pipeline + one R per change
    assert h2.wall < h1.wall
    assert not h2.false_completion


def test_h3_rework_without_gates():
    stages = _stages(changed=(True, False, False))
    h3 = simulate_h3(stages)
    assert h3.rework_events == 1  # corrections still visible without gates
    assert h3.gate_runs == 0
