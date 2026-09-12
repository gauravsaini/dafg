import pytest
from pathlib import Path
from dafg.trends import TrendStore, TrendAnalyzer, RunSummary, GateRunRecord

def test_run_summary_serialization():
    rec1 = GateRunRecord(gate_id="g1", status="MET", duration_ms=10.0)
    rec2 = GateRunRecord(gate_id="g2", status="FAILED", duration_ms=20.0, error="boom")
    summary = RunSummary(
        run_id="run-1",
        timestamp="2024-01-01T00:00:00Z",
        gate_results={"g1": rec1, "g2": rec2},
        total_wall_time_ms=35.0,
        outcome="PARTIAL",
        gates_met=1,
        gates_failed=1,
        gates_total=2,
    )
    d = summary.to_dict()
    assert d['run_id'] == "run-1"
    assert d['gate_results']['g1']['status'] == "MET"
    
    summary2 = RunSummary.from_dict(d)
    assert summary2.run_id == "run-1"
    assert summary2.gates_met == 1
    assert summary2.gate_results["g1"].status == "MET"
    assert summary2.gate_results["g2"].error == "boom"


def test_trend_store_append_and_load(tmp_path):
    store = TrendStore(filepath=tmp_path / "trends.jsonl")
    assert store.load_runs() == []
    
    summary = RunSummary(
        run_id="run-1",
        timestamp="2024-01-01T00:00:00Z",
        gate_results={"g1": GateRunRecord("g1", "MET")},
    )
    store.append_run(summary)
    
    runs = store.load_runs()
    assert len(runs) == 1
    assert runs[0].run_id == "run-1"
    
    summary2 = RunSummary(
        run_id="run-2",
        timestamp="2024-01-01T00:01:00Z",
        gate_results={"g1": GateRunRecord("g1", "FAILED")},
    )
    store.append_run(summary2)
    
    runs = store.load_runs()
    assert len(runs) == 2
    
    # Load with limit
    runs = store.load_runs(limit=1)
    assert len(runs) == 1
    assert runs[0].run_id == "run-2"


def test_trend_store_clear(tmp_path):
    store = TrendStore(filepath=tmp_path / "trends.jsonl")
    store.append_run(RunSummary("r", "ts", {}))
    assert len(store.load_runs()) == 1
    store.clear()
    assert len(store.load_runs()) == 0
    assert not store.filepath.exists()


def test_trend_store_malformed(tmp_path):
    store = TrendStore(filepath=tmp_path / "trends.jsonl")
    store.filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(store.filepath, 'w') as f:
        f.write("{bad json\n")
        f.write('{"run_id": "r2", "timestamp": "t", "gate_results": {}}\n')
        f.write("[]\n")
    
    runs = store.load_runs()
    assert len(runs) == 1
    assert runs[0].run_id == "r2"


def _make_run(run_id, ts, results, wall_time=0.0):
    met = sum(1 for status in results.values() if status == "MET")
    failed = len(results) - met
    gate_results = {gid: GateRunRecord(gid, status, duration_ms=wall_time/len(results) if results else 0) for gid, status in results.items()}
    return RunSummary(
        run_id=run_id,
        timestamp=ts,
        gate_results=gate_results,
        total_wall_time_ms=wall_time,
        gates_met=met,
        gates_failed=failed,
        gates_total=len(results)
    )

def test_analyzer_flaky_gates(tmp_path):
    store = TrendStore(filepath=tmp_path / "trends.jsonl")
    analyzer = TrendAnalyzer(store)
    
    # No runs
    assert analyzer.get_flaky_gates() == []
    
    # Single run
    store.append_run(_make_run("r1", "t1", {"g1": "MET", "g2": "MET"}))
    assert analyzer.get_flaky_gates() == []
    
    # Stable runs
    store.append_run(_make_run("r2", "t2", {"g1": "MET", "g2": "MET"}))
    assert analyzer.get_flaky_gates() == []
    
    # Flaky run
    store.append_run(_make_run("r3", "t3", {"g1": "FAILED", "g2": "MET"}))
    store.append_run(_make_run("r4", "t4", {"g1": "MET", "g2": "MET"}))
    store.append_run(_make_run("r5", "t5", {"g1": "FAILED", "g2": "MET"}))
    
    flaky = analyzer.get_flaky_gates()
    assert len(flaky) == 1
    assert flaky[0].gate_id == "g1"
    assert flaky[0].flip_count == 3
    assert flaky[0].last_n_results == ["MET", "MET", "FAILED", "MET", "FAILED"]


def test_analyzer_regressions(tmp_path):
    store = TrendStore(filepath=tmp_path / "trends.jsonl")
    analyzer = TrendAnalyzer(store)
    
    # Insufficient data
    assert analyzer.get_regression_signals() == []
    store.append_run(_make_run("r1", "t", {"g1": "MET", "g2": "MET"}, 100))
    assert analyzer.get_regression_signals() == []
    
    # No regression
    store.append_run(_make_run("r2", "t", {"g1": "MET", "g2": "MET"}, 105))
    store.append_run(_make_run("r3", "t", {"g1": "MET", "g2": "MET"}, 95))
    assert analyzer.get_regression_signals() == []
    
    # Wall time regression
    store.append_run(_make_run("r4", "t", {"g1": "MET", "g2": "MET"}, 150))
    regs = analyzer.get_regression_signals()
    assert len(regs) == 1
    assert regs[0].metric_name == "total_wall_time_ms"
    assert regs[0].current_value == 150
    assert regs[0].delta_pct == 50.0 # (150 - 100) / 100 * 100 (mean of 100, 105, 95 is 100)
    
    # Pass rate regression
    store.append_run(_make_run("r5", "t", {"g1": "FAILED", "g2": "FAILED"}, 100))
    regs = analyzer.get_regression_signals(window=5)
    # Pass rates were 1, 1, 1, 1 -> 0
    assert len(regs) >= 1
    pass_rate_regs = [r for r in regs if r.metric_name == "pass_rate"]
    assert len(pass_rate_regs) == 1
    assert pass_rate_regs[0].previous_mean == 1.0
    assert pass_rate_regs[0].current_value == 0.0


def test_analyzer_bottlenecks(tmp_path):
    store = TrendStore(filepath=tmp_path / "trends.jsonl")
    analyzer = TrendAnalyzer(store)
    
    summary = RunSummary(
        run_id="r", timestamp="t",
        gate_results={
            "g1": GateRunRecord("g1", "MET", duration_ms=10.0),
            "g2": GateRunRecord("g2", "MET", duration_ms=80.0),
            "g3": GateRunRecord("g3", "MET", duration_ms=10.0),
        },
        total_wall_time_ms=100.0,
    )
    store.append_run(summary)
    
    bottlenecks = analyzer.get_bottleneck_gates(threshold_pct=30.0)
    assert len(bottlenecks) == 1
    assert bottlenecks[0][0] == "g2"
    assert bottlenecks[0][1] == 80.0


def test_analyzer_generate_briefing(tmp_path):
    store = TrendStore(filepath=tmp_path / "trends.jsonl")
    analyzer = TrendAnalyzer(store)
    
    assert analyzer.generate_briefing() == "No previous runs recorded."
    
    store.append_run(_make_run("r1", "t", {"g1": "MET"}))
    briefing = analyzer.generate_briefing()
    assert "Last run" in briefing
    assert "No flaky gates" in briefing
    
    store.append_run(_make_run("r2", "t", {"g1": "FAILED"}, wall_time=200))
    briefing = analyzer.generate_briefing()
    assert "Flaky gates" in briefing
    assert "Regressions" in briefing
