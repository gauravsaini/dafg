"""Independent black-box tests for bottleneck remediation.

These tests treat DAFG as a sealed library — only public API, no internal state
inspection beyond what the public methods return.  They are intentionally
different from the tests shipped with the implementation.
"""
import json
import threading
import time

import pytest

from dafg.runtime import (
    AgentResponse,
    Budget,
    BudgetExceededError,
    DAFG,
    NodeStatus,
    StateStore,
    TaskNode,
    nodes_conflict,
)
from dafg.gates import GateLedger


# ── Phase 1: Thread Safety ──────────────────────────────────────────────


class TestBudgetAtomicityBlackBox:
    """Budget must never allow more than max_calls even under contention."""

    @pytest.mark.parametrize("threads,calls_each,limit", [
        (20, 1, 10),    # more threads than budget
        (5, 20, 100),   # exactly exhausting
        (50, 1, 25),    # heavy contention, half overflow
    ])
    def test_budget_never_overflows(self, threads, calls_each, limit):
        budget = Budget(max_calls=limit)
        successes = []
        failures = []

        def worker():
            for _ in range(calls_each):
                try:
                    budget.check_call()
                    successes.append(1)
                except BudgetExceededError:
                    failures.append(1)

        pool = [threading.Thread(target=worker) for _ in range(threads)]
        for t in pool:
            t.start()
        for t in pool:
            t.join()

        # The invariant: successes ≤ limit, and total = successes + failures
        assert len(successes) <= limit
        assert len(successes) + len(failures) == threads * calls_each
        assert budget.calls_consumed == len(successes)

    def test_budget_revision_and_adaptation_locks(self):
        """All counter methods are protected, not just check_call."""
        budget = Budget(max_revisions=10, max_adaptations=10)
        barrier = threading.Barrier(20)

        def rev_worker():
            barrier.wait()
            try:
                budget.check_revision()
            except BudgetExceededError:
                pass

        def adapt_worker():
            barrier.wait()
            try:
                budget.check_adaptation()
            except BudgetExceededError:
                pass

        threads = (
            [threading.Thread(target=rev_worker) for _ in range(10)]
            + [threading.Thread(target=adapt_worker) for _ in range(10)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert budget.revisions_consumed <= 10
        assert budget.adaptations_consumed <= 10


class TestStateStoreBlackBox:
    """Concurrent saves must not corrupt the JSON file."""

    def test_no_corruption_under_parallel_writes(self, tmp_path):
        fp = tmp_path / "state.json"

        def writer(i):
            StateStore.save({"writer": i, "data": list(range(100))}, fp)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # File must be valid JSON — no partial writes
        loaded = StateStore.load(fp)
        assert "writer" in loaded
        assert len(loaded["data"]) == 100


class TestParallelStepBlackBox:
    """step() with executor_fn dispatches nodes concurrently without races."""

    def test_three_independent_nodes_all_accepted(self):
        a = TaskNode(id="A", title="a", status=NodeStatus.READY, owns=["file_a.py"])
        b = TaskNode(id="B", title="b", status=NodeStatus.READY, owns=["file_b.py"])
        c = TaskNode(id="C", title="c", status=NodeStatus.READY, owns=["file_c.py"])

        dafg = DAFG(nodes={"A": a, "B": b, "C": c}, budget=Budget(max_nodes=10))
        dafg.max_parallel_workers = 3

        call_log = []

        def executor(node, ctx):
            call_log.append(node.id)
            time.sleep(0.02)
            return AgentResponse(output=f"done-{node.id}", status="COMPLETED")

        executed = dafg.step(executor_fn=executor)

        assert len(executed) == 3
        for n in [a, b, c]:
            assert n.status == NodeStatus.ACCEPTED

    def test_conflicting_nodes_serialized_across_waves(self):
        """Two nodes owning the same file must NOT run in the same wave."""
        a = TaskNode(id="A", title="a", status=NodeStatus.READY, owns=["shared.py"])
        b = TaskNode(id="B", title="b", status=NodeStatus.READY, owns=["shared.py"])

        dafg = DAFG(nodes={"A": a, "B": b}, budget=Budget(max_nodes=10))
        dafg.max_parallel_workers = 2

        def executor(node, ctx):
            return AgentResponse(output="ok", status="COMPLETED")

        # First step: only one should execute
        wave1 = dafg.step(executor_fn=executor)
        assert len(wave1) == 1

        # Second step: the other
        wave2 = dafg.step(executor_fn=executor)
        assert len(wave2) == 1

        # Both accepted
        assert a.status == NodeStatus.ACCEPTED
        assert b.status == NodeStatus.ACCEPTED


# ── Phase 2: Reader-Writer Ownership ────────────────────────────────────


class TestReaderWriterBlackBox:
    """Test read/write ownership through compute_waves — the scheduling surface."""

    def test_two_readers_same_file_wave_zero(self):
        r1 = TaskNode(id="R1", title="r1", status=NodeStatus.READY, owns_read=["src/x.py"])
        r2 = TaskNode(id="R2", title="r2", status=NodeStatus.READY, owns_read=["src/x.py"])

        dafg = DAFG(nodes={"R1": r1, "R2": r2}, budget=Budget(max_nodes=10))
        waves = dafg.compute_waves([r1, r2])

        # Both should land in wave 0 — no conflict
        assert len(waves[0]) == 2

    def test_writer_blocks_reader(self):
        w = TaskNode(id="W", title="w", status=NodeStatus.READY, owns=["src/x.py"])
        r = TaskNode(id="R", title="r", status=NodeStatus.READY, owns_read=["src/x.py"])

        dafg = DAFG(nodes={"W": w, "R": r}, budget=Budget(max_nodes=10))
        waves = dafg.compute_waves([w, r])

        # One in wave 0, one in wave 1
        assert len(waves) >= 2
        assert len(waves[0]) == 1

    def test_reader_writer_through_full_run(self):
        """End-to-end: readers run in parallel, writer waits."""
        r1 = TaskNode(id="R1", title="r1", status=NodeStatus.READY, owns_read=["shared.py"])
        r2 = TaskNode(id="R2", title="r2", status=NodeStatus.READY, owns_read=["shared.py"])
        w1 = TaskNode(id="W1", title="w1", status=NodeStatus.READY, owns=["shared.py"])

        dafg = DAFG(nodes={"R1": r1, "R2": r2, "W1": w1}, budget=Budget(max_nodes=10))
        dafg.max_parallel_workers = 3

        execution_order = []

        def executor(node, ctx):
            execution_order.append(node.id)
            return AgentResponse(output="ok", status="COMPLETED")

        # Wave 1: both readers
        wave1 = dafg.step(executor_fn=executor)
        wave1_ids = {n.id for n in wave1}
        assert "R1" in wave1_ids
        assert "R2" in wave1_ids
        assert "W1" not in wave1_ids

        # Wave 2: writer
        wave2 = dafg.step(executor_fn=executor)
        assert len(wave2) == 1
        assert wave2[0].id == "W1"

    def test_nodes_conflict_api_symmetry(self):
        """nodes_conflict(a,b) == nodes_conflict(b,a) for write-read."""
        w = TaskNode(id="W", title="w", owns=["f.py"])
        r = TaskNode(id="R", title="r", owns_read=["f.py"])
        assert nodes_conflict(w, r) == nodes_conflict(r, w)

    def test_owns_read_gate_parsing(self):
        text = """
- [ ] G1: Read something
  CHECK: echo ok
  EXPECT: ok
  OWNS_READ: src/foo.py, src/bar.py
"""
        ledger = GateLedger.parse(text)
        gate = ledger.get_gate("G1")
        assert gate is not None
        assert "src/foo.py" in gate.owns_read
        assert "src/bar.py" in gate.owns_read


# ── Phase 3: Wave Report & Critical Path ────────────────────────────────


class TestWaveReportBlackBox:
    """get_wave_report() returns correct aggregate data after real execution."""

    def test_report_after_real_step(self):
        a = TaskNode(id="A", title="a", status=NodeStatus.READY, owns=["a.py"])
        b = TaskNode(id="B", title="b", status=NodeStatus.READY, owns=["b.py"])

        dafg = DAFG(nodes={"A": a, "B": b}, budget=Budget(max_nodes=10))
        dafg.max_parallel_workers = 2

        def executor(node, ctx):
            time.sleep(0.01)
            return AgentResponse(output="ok", status="COMPLETED")

        dafg.step(executor_fn=executor)

        report = dafg.get_wave_report()
        assert report["steps"] == 1
        assert report["avg_concurrency_ratio"] > 0
        assert isinstance(report["wave_width_histogram"], dict)
        assert report["avg_speedup_ratio"] > 0


class TestCriticalPathBlackBox:
    """critical_path() returns the longest-latency chain."""

    def test_fan_out_fan_in(self):
        """
        A → B (slow, 5s)
        A → C (fast, 1s)
        B → D
        C → D
        Critical path should go through B.
        """
        now = time.time()

        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        a.wait_metrics.time_dispatched = now
        a.wait_metrics.time_finished = now + 1.0

        b = TaskNode(id="B", title="b", status=NodeStatus.ACCEPTED, needs=["A"])
        b.wait_metrics.time_dispatched = now + 1
        b.wait_metrics.time_finished = now + 6.0  # 5s

        c = TaskNode(id="C", title="c", status=NodeStatus.ACCEPTED, needs=["A"])
        c.wait_metrics.time_dispatched = now + 1
        c.wait_metrics.time_finished = now + 2.0  # 1s

        d = TaskNode(id="D", title="d", status=NodeStatus.ACCEPTED, needs=["B", "C"])
        d.wait_metrics.time_dispatched = now + 6
        d.wait_metrics.time_finished = now + 7.0

        dafg = DAFG(nodes={"A": a, "B": b, "C": c, "D": d}, budget=Budget(max_nodes=10))
        path = dafg.critical_path()

        assert "A" in path
        assert "B" in path
        assert "D" in path
        assert "C" not in path

    def test_critical_path_with_unfinished_nodes(self):
        """Nodes without timing data get cost 0 — should still appear in chain."""
        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        b = TaskNode(id="B", title="b", status=NodeStatus.ACCEPTED, needs=["A"])
        # No timing data set

        dafg = DAFG(nodes={"A": a, "B": b}, budget=Budget(max_nodes=10))
        path = dafg.critical_path()
        # Should still return a path (both have cost 0, but B depends on A)
        assert path == ["A", "B"]


# ── Phase 4: Triad Telemetry ───────────────────────────────────────────


class TestTriadTelemetryBlackBox:
    """Triad timings must appear in node.metadata after successful execution."""

    def test_timings_present_after_step(self):
        n = TaskNode(id="N", title="n", status=NodeStatus.READY)
        dafg = DAFG(nodes={"N": n}, budget=Budget(max_nodes=10))

        def executor(node, ctx):
            time.sleep(0.015)
            return AgentResponse(output="ok", status="COMPLETED")

        dafg.step(executor_fn=executor)

        assert n.status == NodeStatus.ACCEPTED
        assert "_triad_timings" in n.metadata
        t = n.metadata["_triad_timings"]
        assert t["prover_ms"] >= 10  # at least 10ms from the sleep
        assert "verifier_ms" in t
        assert "total_ms" in t
        assert t["total_ms"] >= t["prover_ms"]

    def test_revision_triggers_recorded(self):
        n = TaskNode(id="N", title="n", status=NodeStatus.READY)
        dafg = DAFG(nodes={"N": n}, budget=Budget(max_nodes=10))

        def executor(node, ctx):
            return AgentResponse(output="ok", status="COMPLETED")

        dafg.step(executor_fn=executor)
        assert "_revision_triggers" in n.metadata
        assert n.metadata["_revision_triggers"] == 0  # no revisions on first pass


# ── Analytics & Persistence ─────────────────────────────────────────────


class TestAnalyticsBlackBox:
    """get_run_analytics() and format_analytics_report() are coherent."""

    def test_analytics_round_trip_through_state(self, tmp_path):
        """Save state → load state → analytics match."""
        fp = tmp_path / "state.json"

        a = TaskNode(id="A", title="a", status=NodeStatus.READY, owns=["a.py"])
        b = TaskNode(id="B", title="b", status=NodeStatus.READY, owns=["b.py"])

        dafg = DAFG(
            nodes={"A": a, "B": b},
            budget=Budget(max_nodes=10),
            state_path=fp,
        )
        dafg.max_parallel_workers = 2

        def executor(node, ctx):
            time.sleep(0.01)
            return AgentResponse(output="ok", status="COMPLETED")

        dafg.step(executor_fn=executor)
        dafg.save_state()

        # Load raw JSON — black-box check
        raw = json.loads(fp.read_text())
        assert "wave_diagnostics" in raw
        assert len(raw["wave_diagnostics"]) == 1
        assert "analytics" in raw
        assert raw["analytics"]["funnel"]["total_nodes"] == 2

        # Load via public API
        restored = DAFG.load_state(fp)
        assert len(restored.wave_diagnostics) == 1
        report = restored.get_wave_report()
        assert report["steps"] == 1

    def test_format_report_contains_sections(self):
        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        dafg = DAFG(nodes={"A": a}, budget=Budget(max_nodes=5))
        dafg.is_sealed = True

        report = dafg.format_analytics_report()
        assert "DAFG RUN ANALYTICS & FUNNEL" in report
        assert "FUNNEL CONVERGENCE" in report
        assert "BUDGET UTILIZATION" in report


# ── Lock Ordering Safety ────────────────────────────────────────────────


class TestLockOrderingBlackBox:
    """Verify no deadlock under concurrent commit_transition + save_state."""

    def test_concurrent_transitions_no_deadlock(self):
        """Multiple threads committing transitions simultaneously must not deadlock."""
        nodes = {
            f"N{i}": TaskNode(id=f"N{i}", title=f"n{i}", status=NodeStatus.READY, owns=[f"file{i}.py"])
            for i in range(5)
        }
        dafg = DAFG(nodes=nodes, budget=Budget(max_nodes=20))
        dafg.max_parallel_workers = 5

        def executor(node, ctx):
            return AgentResponse(output="ok", status="COMPLETED")

        # If locks deadlock, this will hang and pytest will time out
        executed = dafg.step(executor_fn=executor)
        assert len(executed) == 5
        for n in nodes.values():
            assert n.status == NodeStatus.ACCEPTED
