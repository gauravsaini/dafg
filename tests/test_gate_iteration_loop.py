"""Tests for GateIterationLoop multi-persona adversarial gate iteration."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from dafg.gates import Gate, GateEngine, GateLedger, GateResult
from dafg.organism import GateIterationLoop, PersonaVerdict, HandoffReport
from dafg.persona import PersonaCompiler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ledger(text: str) -> GateLedger:
    """Parse a GATES.md-style string into a GateLedger."""
    return GateLedger.parse(text)


def _make_loop(ledger, engine=None, compiler=None, workdir=None, **kwargs):
    """Create a GateIterationLoop with sensible defaults."""
    return GateIterationLoop(
        ledger=ledger,
        engine=engine or GateEngine(auto_approve=True),
        compiler=compiler or PersonaCompiler(),
        workdir=workdir,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestGateIterationLoopConstruction:

    def test_can_construct_with_defaults(self):
        ledger = _make_ledger("- [ ] G1: Test gate\n  CHECK: echo ok\n  EXPECT: ok\n")
        loop = _make_loop(ledger)
        assert loop.quorum_threshold == 3
        assert loop.quorum_size == 5
        assert loop.iteration_history == []

    def test_custom_quorum_threshold(self):
        ledger = _make_ledger("- [ ] G1: Test\n  CHECK: echo ok\n  EXPECT: ok\n")
        loop = _make_loop(ledger, quorum_threshold=4, quorum_size=5)
        assert loop.quorum_threshold == 4


# ---------------------------------------------------------------------------
# group_gates_by_ownership
# ---------------------------------------------------------------------------

class TestGroupGatesByOwnership:

    def test_overlapping_owns_grouped_together(self):
        text = (
            "- [ ] G1: Gate one\n"
            "  OWNS: src/core.py\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "- [ ] G2: Gate two\n"
            "  OWNS: src/core.py, src/util.py\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        ledger = _make_ledger(text)
        loop = _make_loop(ledger)
        groups = loop.group_gates_by_ownership()
        # G1 and G2 share src/core.py, so they should be in the same group
        assert len(groups) == 1
        assert sorted(groups[0]) == ["G1", "G2"]

    def test_disjoint_owns_separate_groups(self):
        text = (
            "- [ ] G1: Gate one\n"
            "  OWNS: src/core.py\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "- [ ] G2: Gate two\n"
            "  OWNS: src/util.py\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        ledger = _make_ledger(text)
        loop = _make_loop(ledger)
        groups = loop.group_gates_by_ownership()
        assert len(groups) == 2
        flat = [sorted(g) for g in groups]
        assert ["G1"] in flat
        assert ["G2"] in flat

    def test_no_owns_gets_own_group(self):
        text = (
            "- [ ] G1: Gate one\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "- [ ] G2: Gate two\n"
            "  OWNS: src/core.py\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        ledger = _make_ledger(text)
        loop = _make_loop(ledger)
        groups = loop.group_gates_by_ownership()
        assert len(groups) == 2

    def test_transitive_merge(self):
        """G1 owns A, G2 owns A,B, G3 owns B => all three in same group."""
        text = (
            "- [ ] G1: Gate one\n"
            "  OWNS: a.py\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "- [ ] G2: Gate two\n"
            "  OWNS: a.py, b.py\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "- [ ] G3: Gate three\n"
            "  OWNS: b.py\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        ledger = _make_ledger(text)
        loop = _make_loop(ledger)
        groups = loop.group_gates_by_ownership()
        assert len(groups) == 1
        assert sorted(groups[0]) == ["G1", "G2", "G3"]


# ---------------------------------------------------------------------------
# iterate_milestone
# ---------------------------------------------------------------------------

class TestIterateMilestone:

    def test_all_passing_gates_returns_true(self, tmp_path):
        """When all gates pass, iterate_milestone should return (True, verdicts)."""
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        loop = _make_loop(ledger, engine=engine, workdir=tmp_path)
        passed, verdicts = loop.iterate_milestone(["G1"])
        assert passed is True
        assert len(verdicts) == 5  # 5 phases
        archetypes = [v.archetype for v in verdicts]
        assert archetypes == ["explorer", "worker", "reviewer", "challenger", "auditor"]

    def test_failing_gates_returns_false(self, tmp_path):
        """When a gate fails, quorum should not be met => False."""
        text = (
            "- [ ] G1: Failing check\n"
            "  CHECK: echo wrong\n"
            "  EXPECT: right\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        loop = _make_loop(ledger, engine=engine, workdir=tmp_path)
        passed, verdicts = loop.iterate_milestone(["G1"])
        # explorer=APPROVE, worker=APPROVE, reviewer=REJECT, challenger=REJECT, auditor=DIRTY
        # Only 2 APPROVE => below threshold of 3
        assert passed is False

    def test_quorum_threshold_3_of_5_with_all_passing(self, tmp_path):
        """With all passing gates, we get 5 positive verdicts >= 3 threshold."""
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        loop = _make_loop(ledger, engine=engine, workdir=tmp_path, quorum_threshold=3)
        passed, verdicts = loop.iterate_milestone(["G1"])
        positive = sum(1 for v in verdicts if v.verdict in ("APPROVE", "CLEAN"))
        assert positive >= 3
        assert passed is True

    def test_quorum_threshold_blocks_when_insufficient(self, tmp_path):
        """Failing gate: only explorer + worker approve (2) < threshold 3."""
        text = (
            "- [ ] G1: Fail check\n"
            "  CHECK: echo nope\n"
            "  EXPECT: yes\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        loop = _make_loop(ledger, engine=engine, workdir=tmp_path, quorum_threshold=3)
        passed, verdicts = loop.iterate_milestone(["G1"])
        positive = sum(1 for v in verdicts if v.verdict in ("APPROVE", "CLEAN"))
        assert positive < 3
        assert passed is False

    def test_handoff_files_written_to_workdir(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        loop = _make_loop(ledger, engine=engine, workdir=tmp_path)
        loop.iterate_milestone(["G1"], generation=1)

        iter_dir = tmp_path / "iterations" / "gen_1"
        assert iter_dir.exists()
        expected_files = [
            "explorer_handoff.md",
            "worker_handoff.md",
            "reviewer_handoff.md",
            "challenger_handoff.md",
            "auditor_handoff.md",
        ]
        for fname in expected_files:
            fpath = iter_dir / fname
            assert fpath.exists(), f"Missing handoff file: {fname}"
            content = fpath.read_text(encoding="utf-8")
            assert "# Handoff Report" in content

    def test_iteration_history_recorded(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        loop = _make_loop(ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        loop.iterate_milestone(["G1"], generation=42)
        assert len(loop.iteration_history) == 1
        record = loop.iteration_history[0]
        assert record["generation"] == 42
        assert record["gate_ids"] == ["G1"]
        assert "passed" in record
        assert "positive_count" in record


# ---------------------------------------------------------------------------
# iterate_all
# ---------------------------------------------------------------------------

class TestIterateAll:

    def test_processes_all_gate_groups(self, tmp_path):
        text = (
            "- [ ] G1: Gate one\n"
            "  OWNS: src/core.py\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
            "- [ ] G2: Gate two\n"
            "  OWNS: src/util.py\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        loop = _make_loop(ledger, engine=engine, workdir=tmp_path)
        passed, verdicts = loop.iterate_all(generation=1)
        assert passed is True
        # 2 groups * 5 phases = 10 verdicts
        assert len(verdicts) == 10

    def test_fails_if_any_group_fails(self, tmp_path):
        text = (
            "- [ ] G1: Passing gate\n"
            "  OWNS: src/core.py\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
            "- [ ] G2: Failing gate\n"
            "  OWNS: src/util.py\n"
            "  CHECK: echo wrong\n"
            "  EXPECT: right\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        loop = _make_loop(ledger, engine=engine, workdir=tmp_path)
        passed, verdicts = loop.iterate_all(generation=1)
        assert passed is False
