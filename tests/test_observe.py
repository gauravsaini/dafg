"""Tests for Distributed Observability Fabric (DOF)."""

import io
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from dafg.gates import ApprovalStore, Gate, GateEngine, GateLedger
from dafg.hook import CompletionGuard
from dafg.observe import (
    InMemoryProbe,
    JsonlProbe,
    NullProbe,
    ObservabilityFabric,
    Probe,
    Span,
    SpanStatus,
    StdoutProbe,
    parse_observe_flag,
)
from dafg.repair import RepairBudget, RepairLoop, RepairStatus
from dafg.runtime import DAFG, AgentResponse, Budget, NodeStatus, TaskNode


def test_span_lifecycle_and_status():
    span = Span(
        trace_id="run_123",
        span_id="node_a:1:1",
        name="test.span",
        attributes={"key": "val"},
    )
    assert span.status == SpanStatus.OK
    assert span.duration_ms >= 0.0
    assert span.end_time is None

    time.sleep(0.01)
    span.finish(SpanStatus.ERROR)

    assert span.status == SpanStatus.ERROR
    assert span.end_time is not None
    assert span.duration_ms > 0.0

    d = span.to_dict()
    assert d["trace_id"] == "run_123"
    assert d["span_id"] == "node_a:1:1"
    assert d["name"] == "test.span"
    assert d["status"] == "error"
    assert d["attributes"] == {"key": "val"}
    assert d["duration_ms"] > 0.0


def test_null_probe_is_default(tmp_path):
    # DAFG with no probes works normally
    n1 = TaskNode(id="t1", title="Task 1", owns=["a.py"])
    graph = DAFG(nodes={"t1": n1}, state_path=tmp_path / "state.json")

    def mock_exec(node, ctx):
        return AgentResponse(output="Done")

    res = graph.step(executor_fn=mock_exec)
    assert len(res) == 1
    assert res[0].id == "t1"
    assert res[0].status == NodeStatus.ACCEPTED


def test_in_memory_probe_captures_events_and_spans(tmp_path):
    probe = InMemoryProbe()
    n1 = TaskNode(id="n1", title="First", owns=["x.txt"])
    n2 = TaskNode(id="n2", title="Second", needs=["n1"], owns=["y.txt"])

    graph = DAFG(
        nodes={"n1": n1, "n2": n2},
        state_path=tmp_path / "state.json",
        probes=[probe],
    )

    def mock_exec(node, ctx):
        return AgentResponse(output="Executed")

    # Step 1: n1 ready
    executed1 = graph.step(executor_fn=mock_exec)
    assert len(executed1) == 1

    # Check that events and spans were recorded
    span_names = [s["name"] for s in probe.spans]
    assert "wave.dispatch" in span_names

    event_names = [e["name"] for e in probe.events]
    assert "graph.ready_nodes" in event_names
    ready_events = [e for e in probe.events if e["name"] == "graph.ready_nodes"]
    assert ready_events[0]["attributes"]["count"] == 1
    assert ready_events[0]["attributes"]["node_ids"] == ["n1"]

    metric_names = [m["name"] for m in probe.metrics]
    assert "wave.concurrency_ratio" in metric_names
    assert "state.persisted" in metric_names


def test_jsonl_probe_writes_and_rotates(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    probe = JsonlProbe(filepath=trace_file, max_bytes=1000)

    fabric = ObservabilityFabric([probe])
    span = fabric.start_span("job.work", trace_id="trace_1", attributes={"x": 1})
    fabric.end_span(span, SpanStatus.OK)
    fabric.emit_event("system.boot", {"os": "mac"})
    fabric.emit_metric("cpu.pct", 45.2)

    assert trace_file.exists()
    lines = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").strip().split("\n")]
    assert len(lines) == 3
    assert lines[0]["type"] == "span"
    assert lines[0]["name"] == "job.work"
    assert lines[1]["type"] == "event"
    assert lines[1]["name"] == "system.boot"
    assert lines[2]["type"] == "metric"
    assert lines[2]["name"] == "cpu.pct"

    # Write enough to exceed 1000 bytes and verify rotation creates .bak
    for i in range(25):
        fabric.emit_event(f"event.{i}", {"data": "A" * 60})

    bak_file = trace_file.with_suffix(".jsonl.bak")
    assert bak_file.exists()
    assert trace_file.exists()


def test_stdout_probe_smoke():
    probe = StdoutProbe(color=False)
    fabric = ObservabilityFabric([probe])

    stderr_buf = io.StringIO()
    with patch("sys.stderr", stderr_buf):
        span = fabric.start_span("stdout.test", trace_id="run_stdout")
        fabric.end_span(span, SpanStatus.OK)
        fabric.emit_event("test.alert", {"severity": "low"})
        fabric.emit_metric("test.count", 1.0)

    output = stderr_buf.getvalue()
    assert "stdout.test" in output
    assert "test.alert" in output
    assert "test.count=1.0" in output


def test_probe_exception_is_silenced(tmp_path):
    class CrashingProbe:
        def on_span_start(self, span):
            raise RuntimeError("Boom start")

        def on_span_end(self, span):
            raise RuntimeError("Boom end")

        def on_event(self, name, attributes):
            raise RuntimeError("Boom event")

        def on_metric(self, name, value, tags=None):
            raise RuntimeError("Boom metric")

    crashing_probe = CrashingProbe()
    memory_probe = InMemoryProbe()

    node = TaskNode(id="safe_task", title="Safe", owns=["safe.py"])
    graph = DAFG(
        nodes={"safe_task": node},
        state_path=tmp_path / "state.json",
        probes=[crashing_probe, memory_probe],
    )

    def mock_exec(n, ctx):
        return AgentResponse(output="OK")

    # Even with CrashingProbe throwing errors on every call, the step must complete!
    executed = graph.step(executor_fn=mock_exec)
    assert len(executed) == 1
    assert executed[0].status == NodeStatus.ACCEPTED

    # memory_probe should still have recorded events
    assert len(memory_probe.spans) > 0
    assert len(memory_probe.events) > 0


def test_observability_never_blocks_runtime(tmp_path):
    # Stress test: verify high emission volume does not prevent runtime from executing
    probe = InMemoryProbe()
    node = TaskNode(id="perf_node", title="Perf", owns=["p.py"])
    graph = DAFG(
        nodes={"perf_node": node},
        state_path=tmp_path / "state.json",
        probes=[probe],
    )

    t0 = time.perf_counter()
    for i in range(100):
        graph._fabric.emit_event(f"rapid_event_{i}", {"seq": i})
        graph._fabric.emit_metric(f"rapid_metric_{i}", float(i))

    def mock_exec(n, ctx):
        return AgentResponse(output="OK")

    executed = graph.step(executor_fn=mock_exec)
    t1 = time.perf_counter()

    assert len(executed) == 1
    # 100 events + 100 metrics + step should execute in well under 1 second
    assert (t1 - t0) < 1.0


def test_async_fan_out():
    events_received = []

    class AsyncCaptureProbe:
        def on_span_start(self, span):
            pass

        def on_span_end(self, span):
            pass

        def on_event(self, name, attributes):
            events_received.append(name)

        def on_metric(self, name, value, tags=None):
            pass

    probe = AsyncCaptureProbe()
    fabric = ObservabilityFabric([probe], async_mode=True)
    fabric.emit_event("async.ping", {"time": time.time()})

    # Small delay to let thread pool process
    time.sleep(0.05)
    assert "async.ping" in events_received


def test_parse_observe_flag():
    probes = parse_observe_flag(["none", "stdout", "memory", "jsonl:my_trace.jsonl"])
    assert len(probes) == 3
    assert any(isinstance(p, StdoutProbe) for p in probes)
    assert any(isinstance(p, InMemoryProbe) for p in probes)
    assert any(isinstance(p, JsonlProbe) for p in probes)

    all_probes = parse_observe_flag(["all"])
    assert len(all_probes) == 3
    assert any(isinstance(p, StdoutProbe) for p in all_probes)
    assert any(isinstance(p, JsonlProbe) for p in all_probes)
    assert any(isinstance(p, InMemoryProbe) for p in all_probes)


def test_gate_engine_with_fabric(tmp_path):
    probe = InMemoryProbe()
    fabric = ObservabilityFabric([probe])

    ledger_text = """
- [ ] G_OBS: Check python version
  CHECK: python3 -c "print('HELLO_DOF')"
  EXPECT: HELLO_DOF
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(ledger_text, encoding="utf-8")
    ledger = GateLedger.load(fp)

    engine = GateEngine(auto_approve=True, fabric=fabric)
    result = engine.execute_gate(ledger.gates["G_OBS"], ledger=ledger)

    assert result.status == "MET"
    gate_spans = [s for s in probe.spans if s["name"] == "gate.check"]
    assert len(gate_spans) == 1
    assert gate_spans[0]["status"] == "ok"
    assert gate_spans[0]["attributes"]["gate_id"] == "G_OBS"
    assert gate_spans[0]["attributes"]["exit_code"] == 0


def test_stop_hook_with_fabric(tmp_path):
    probe = InMemoryProbe()
    fabric = ObservabilityFabric([probe])

    ledger_text = """
- [x] G1: Sample Gate
  CHECK: echo OK
  EXPECT: OK
  EVIDENCE: exit_code=0 timestamp=2026-01-01 match='OK'
"""
    fp = tmp_path / "GATES.md"
    fp.write_text(ledger_text, encoding="utf-8")
    ledger = GateLedger.load(fp)
    guard = CompletionGuard(ledger=ledger, fabric=fabric)

    decision = guard.evaluate()
    assert decision.allowed is True

    hook_events = [e for e in probe.events if e["name"] == "stop_hook.evaluated"]
    assert len(hook_events) == 1
    assert hook_events[0]["attributes"]["decision"] == "allow"
    assert hook_events[0]["attributes"]["allowed"] is True


def test_repair_loop_with_fabric(tmp_path):
    probe = InMemoryProbe()
    fabric = ObservabilityFabric([probe])

    text = """
- [ ] G1: title
  CHECK: cat out.txt
  EXPECT: fixed
"""
    ledger = GateLedger.parse(text)
    engine = GateEngine(auto_approve=True)

    (tmp_path / "out.txt").write_text("broken")
    for g in ledger.gates.values():
        g.cwd = str(tmp_path)

    def my_repair(gid, diag, check):
        (tmp_path / "out.txt").write_text("fixed")
        return "wrote fixed"

    loop = RepairLoop(
        ledger=ledger,
        engine=engine,
        repair_fn=my_repair,
        budget=RepairBudget(max_repair_attempts=2),
        fabric=fabric,
    )

    res = loop.repair_gate("G1")

    assert res.final_status == RepairStatus.REPAIRED
    repair_spans = [s for s in probe.spans if s["name"] == "repair.attempt"]
    assert len(repair_spans) >= 1
    assert repair_spans[-1]["status"] == "ok"


def test_budget_observability_with_fabric():
    probe = InMemoryProbe()
    fabric = ObservabilityFabric([probe])

    budget = Budget(max_calls=2, fabric=fabric)
    budget.check_call()
    budget.check_call()

    metric_names = [m["name"] for m in probe.metrics]
    assert "budget.calls_consumed" in metric_names

    with pytest.raises(Exception):
        budget.check_call()

    exceeded_events = [e for e in probe.events if e["name"] == "budget.exceeded"]
    assert len(exceeded_events) == 1
    assert exceeded_events[0]["attributes"]["type"] == "call"
