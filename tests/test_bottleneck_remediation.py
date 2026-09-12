"""Tests for bottleneck remediation: thread safety, wave observability, critical path."""
import threading

from dafg.runtime import (
    AgentResponse,
    Budget,
    BudgetExceededError,
    DAFG,
    NodeStatus,
    StateStore,
    TaskNode,
    WaveDiagnostics,
    nodes_conflict,
)
from dafg.gates import GateLedger
from dafg.cli import main as cli_main


# --- Phase 1: Thread Safety ---


class TestBudgetThreadSafety:
    """Budget counters must be correct under concurrent access."""

    def test_concurrent_check_call(self):
        """10 threads each calling check_call() — total must equal thread count."""
        budget = Budget(max_calls=100)
        errors = []

        def worker():
            try:
                for _ in range(10):
                    budget.check_call()
            except BudgetExceededError as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert budget.calls_consumed == 100

    def test_concurrent_check_call_exceeds_budget(self):
        """Budget limit is respected even under concurrent access."""
        budget = Budget(max_calls=5)
        successes = []
        failures = []

        def worker():
            try:
                budget.check_call()
                successes.append(1)
            except BudgetExceededError:
                failures.append(1)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 5
        assert len(failures) == 5
        assert budget.calls_consumed == 5

    def test_concurrent_check_node(self):
        budget = Budget(max_nodes=50)
        threads = [threading.Thread(target=budget.check_node) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert budget.nodes_created == 50


class TestStateStoreLock:
    """StateStore.save() must not corrupt under concurrent writes."""

    def test_concurrent_saves(self, tmp_path):
        fp = tmp_path / "state.json"
        errors = []

        def writer(i):
            try:
                StateStore.save({"step": i}, fp)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # File must be valid JSON (last writer wins, but no corruption)
        loaded = StateStore.load(fp)
        assert "step" in loaded


# --- Phase 3: Wave Observability ---


class TestWaveReport:
    """get_wave_report() returns correct aggregated diagnostics."""

    def test_empty_report(self):
        dafg = DAFG()
        report = dafg.get_wave_report()
        assert report["steps"] == 0
        assert report["avg_concurrency_ratio"] == 0.0
        assert report["wave_width_histogram"] == {}

    def test_report_structure(self):
        dafg = DAFG()
        dafg.wave_diagnostics.append(WaveDiagnostics(
            step_index=1,
            total_ready=4,
            wave_widths=[2, 2],
            wave_0_width=2,
            concurrency_ratio=0.5,
            speedup_ratio=1.8,
            conflict_reasons=[{
                "deferred_node": "B",
                "conflicting_node": "A",
                "deferred_owns": ["src/x.py"],
                "conflicting_owns": ["src/x.py"],
            }],
        ))
        report = dafg.get_wave_report()
        assert report["steps"] == 1
        assert report["avg_concurrency_ratio"] == 0.5
        assert report["wave_width_histogram"] == {2: 2}
        assert report["total_conflict_deferrals"] == 1
        assert report["avg_speedup_ratio"] == 1.8
        assert len(report["top_conflict_paths"]) > 0


class TestCriticalPath:
    """critical_path() returns the longest dependency chain."""

    def test_linear_chain(self):
        """A→B→C returns ["A", "B", "C"]."""
        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        b = TaskNode(id="B", title="b", status=NodeStatus.ACCEPTED, needs=["A"])
        c = TaskNode(id="C", title="c", status=NodeStatus.ACCEPTED, needs=["B"])

        # Simulate timing: each node took 1s
        import time
        now = time.time()
        for node in [a, b, c]:
            node.wait_metrics.time_dispatched = now
            node.wait_metrics.time_finished = now + 1.0

        dafg = DAFG(nodes={"A": a, "B": b, "C": c}, budget=Budget(max_nodes=10))
        path = dafg.critical_path()
        assert path == ["A", "B", "C"]

    def test_diamond_graph(self):
        """A→(B,C)→D — longer branch wins."""
        import time
        now = time.time()

        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        a.wait_metrics.time_dispatched = now
        a.wait_metrics.time_finished = now + 1.0

        b = TaskNode(id="B", title="b", status=NodeStatus.ACCEPTED, needs=["A"])
        b.wait_metrics.time_dispatched = now
        b.wait_metrics.time_finished = now + 5.0  # B is slow

        c = TaskNode(id="C", title="c", status=NodeStatus.ACCEPTED, needs=["A"])
        c.wait_metrics.time_dispatched = now
        c.wait_metrics.time_finished = now + 1.0  # C is fast

        d = TaskNode(id="D", title="d", status=NodeStatus.ACCEPTED, needs=["B", "C"])
        d.wait_metrics.time_dispatched = now
        d.wait_metrics.time_finished = now + 1.0

        dafg = DAFG(nodes={"A": a, "B": b, "C": c, "D": d}, budget=Budget(max_nodes=10))
        path = dafg.critical_path()
        # Critical path goes through B (5s) not C (1s)
        assert path == ["A", "B", "D"]

    def test_empty_graph(self):
        dafg = DAFG()
        assert dafg.critical_path() == []

    def test_single_node(self):
        import time
        now = time.time()
        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        a.wait_metrics.time_dispatched = now
        a.wait_metrics.time_finished = now + 1.0
        dafg = DAFG(nodes={"A": a}, budget=Budget(max_nodes=5))
        assert dafg.critical_path() == ["A"]


# --- Phase 2: Reader-Writer Ownership ---


class TestReaderWriterOwnership:
    """Read-only ownership (OWNS_READ:) allows concurrent readers."""

    def test_read_read_no_conflict(self):
        """Two nodes reading the same file do NOT conflict."""
        n1 = TaskNode(id="N1", title="read1", owns_read=["src/dafg/runtime.py"])
        n2 = TaskNode(id="N2", title="read2", owns_read=["src/dafg/runtime.py"])
        assert not nodes_conflict(n1, n2)

    def test_write_read_conflict(self):
        """A writer and a reader on the same file DO conflict."""
        writer = TaskNode(id="W", title="write", owns=["src/dafg/runtime.py"])
        reader = TaskNode(id="R", title="read", owns_read=["src/dafg/runtime.py"])
        assert nodes_conflict(writer, reader)
        assert nodes_conflict(reader, writer)

    def test_write_write_conflict(self):
        """Two writers on overlapping paths DO conflict."""
        w1 = TaskNode(id="W1", title="write1", owns=["src/dafg/runtime.py"])
        w2 = TaskNode(id="W2", title="write2", owns=["src/dafg/"])
        assert nodes_conflict(w1, w2)

    def test_read_different_paths_no_conflict(self):
        n1 = TaskNode(id="N1", title="read1", owns_read=["src/dafg/gates.py"])
        n2 = TaskNode(id="N2", title="read2", owns_read=["src/dafg/runtime.py"])
        assert not nodes_conflict(n1, n2)

    def test_gate_ledger_owns_read_parsed(self):
        """GateLedger properly parses OWNS_READ: directive."""
        text = """
- [ ] G1: Check something
  CHECK: echo ok
  EXPECT: ok
  OWNS_READ: src/dafg/runtime.py
"""
        ledger = GateLedger.parse(text)
        gate = ledger.get_gate("G1")
        assert gate is not None
        assert gate.owns_read == "src/dafg/runtime.py"

    def test_compute_waves_with_read_parallelism(self):
        """Multiple read-only nodes can execute in wave 0 simultaneously."""
        r1 = TaskNode(id="R1", title="r1", status=NodeStatus.READY, owns_read=["src/dafg/runtime.py"])
        r2 = TaskNode(id="R2", title="r2", status=NodeStatus.READY, owns_read=["src/dafg/runtime.py"])
        w1 = TaskNode(id="W1", title="w1", status=NodeStatus.READY, owns=["src/dafg/runtime.py"])

        dafg = DAFG(nodes={"R1": r1, "R2": r2, "W1": w1}, budget=Budget(max_nodes=10))
        waves = dafg.compute_waves([r1, r2, w1])

        # r1 and r2 are placed in wave 0; w1 conflicts and is placed in wave 1
        wave0_ids = {n.id for n in waves[0]}
        assert "R1" in wave0_ids
        assert "R2" in wave0_ids
        assert "W1" not in wave0_ids
        assert any("W1" in [n.id for n in w] for w in waves[1:])


# --- Phase 4: Triad Latency Telemetry ---


class TestTriadTimingTelemetry:
    """Triad stage latencies are captured in node metadata."""

    def test_triad_timings_recorded_on_acceptance(self):
        node = TaskNode(id="N1", title="test", status=NodeStatus.READY)
        dafg = DAFG(nodes={"N1": node}, budget=Budget(max_nodes=10))

        def mock_executor(n, ctx):
            import time
            time.sleep(0.01)
            return AgentResponse(output="hello", status="COMPLETED")

        dafg.step(executor_fn=mock_executor)

        assert node.status == NodeStatus.ACCEPTED
        assert "_triad_timings" in node.metadata
        timings = node.metadata["_triad_timings"]
        assert "prover_ms" in timings
        assert timings["prover_ms"] >= 5.0
        assert "verifier_ms" in timings
        assert "total_ms" in timings
        assert "_revision_triggers" in node.metadata


# --- Run Analytics & Funnel Reporting ---


class TestRunAnalytics:
    """DAFG run analytics and funnel reports."""

    def test_analytics_structure(self):
        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        dafg = DAFG(nodes={"A": a}, budget=Budget(max_nodes=5))
        dafg.is_sealed = True

        analytics = dafg.get_run_analytics()
        assert "funnel" in analytics
        assert analytics["funnel"]["total_nodes"] == 1
        assert analytics["funnel"]["accepted_nodes"] == 1
        assert analytics["funnel"]["convergence_rate"] == 1.0
        assert analytics["funnel"]["is_sealed"] is True

        assert "concurrency" in analytics
        assert "triad" in analytics
        assert "critical_path" in analytics
        assert "budget" in analytics
        assert "gates" in analytics

    def test_format_analytics_report(self):
        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        dafg = DAFG(nodes={"A": a}, budget=Budget(max_nodes=5))
        dafg.is_sealed = True

        report = dafg.format_analytics_report()
        assert "DAFG RUN ANALYTICS & FUNNEL" in report
        assert "FUNNEL CONVERGENCE" in report
        assert "CONCURRENCY & THROUGHPUT" in report
        assert "BUDGET UTILIZATION" in report

    def test_state_persistence_includes_analytics(self, tmp_path):
        fp = tmp_path / "state.json"
        a = TaskNode(id="A", title="a", status=NodeStatus.ACCEPTED)
        dafg = DAFG(nodes={"A": a}, budget=Budget(max_nodes=5), state_path=fp)
        dafg.save_state()

        loaded = StateStore.load(fp)
        assert "analytics" in loaded
        assert loaded["analytics"]["funnel"]["total_nodes"] == 1
        assert "wave_diagnostics" in loaded

    def test_load_state_restores_wave_diagnostics(self, tmp_path):
        fp = tmp_path / "state.json"
        dafg = DAFG(state_path=fp)
        dafg.wave_diagnostics.append(WaveDiagnostics(step_index=1, total_ready=2, wave_0_width=2))
        dafg.save_state()

        resumed = DAFG.load_state(fp)
        assert len(resumed.wave_diagnostics) == 1
        assert resumed.wave_diagnostics[0].step_index == 1
        assert resumed.wave_diagnostics[0].wave_0_width == 2

    def test_cli_dafg_run_json_analytics(self, tmp_path, capsys):
        state_fp = tmp_path / "state.json"
        gates_fp = tmp_path / "gates.md"
        # Run dafg run with isolated state and gates
        ret = cli_main(["run", "--state", str(state_fp), "--gates", str(gates_fp), "--json-analytics"])
        assert ret == 1  # No ready nodes / empty graph
        captured = capsys.readouterr()
        assert '"funnel":' in captured.out
        assert '"concurrency":' in captured.out

