"""Tests for the graph-only (B2) trial path: real DAFG scheduling, zero gate evaluation.

The critical property under test: ``run_graph_only_trial`` must NEVER invoke
gate machinery — no GateLedger parsing, no GateEngine construction, no
contract registration, no adapter refusal checks — even on tasks that carry
expected_gates and contradiction contracts. If a future change adds any gate
call to the B2 path, ``test_b2_bypasses_all_gate_evaluation`` fails.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dafg import gates as gates_mod  # noqa: E402
from dafg.adapters import IterativeCLIAdapter  # noqa: E402
from dafg.eval import BenchmarkTask  # noqa: E402
from dafg.graph_only import run_graph_only_trial  # noqa: E402
from dafg.runtime import DAFG, TaskNode  # noqa: E402


def _stub_runner_fn(status="COMPLETED", tokens=100):
    def fn(prompt, node):
        return {
            "output": f"```path:out/{node.id}.txt\ndone\n```",
            "status": status,
            "files_modified": [f"out/{node.id}.txt"],
            "metadata": {},
            "usage": {"prompt_tokens": 10, "completion_tokens": 90, "total_tokens": tokens},
        }

    return fn


def _task(nodes, expected_gates="", contracts=(), feasible=True, fixture="print('EVAL_PASSED')"):
    return BenchmarkTask(
        task_id="gates_ab_unit",
        title="unit",
        is_feasible=feasible,
        initial_nodes=nodes,
        expected_gates=expected_gates,
        test_fixture=fixture,
        contracts=list(contracts),
    )


def _node(nid, owns=None, needs=()):
    return TaskNode(id=nid, title=nid, owns=list(owns or [f"{nid}.txt"]), needs=list(needs))


def test_b2_bypasses_all_gate_evaluation(monkeypatch, tmp_path):
    """B2 must not touch gate machinery even when the task carries gates+contracts."""
    calls = {"parse": 0, "engine": 0, "contract": 0, "refusal": 0}

    orig_parse = gates_mod.GateLedger.parse

    def counting_parse(*a, **k):
        calls["parse"] += 1
        return orig_parse(*a, **k)

    orig_engine_init = gates_mod.GateEngine.__init__

    def counting_engine_init(self, *a, **k):
        calls["engine"] += 1
        return orig_engine_init(self, *a, **k)

    orig_register = DAFG.register_contract

    def counting_register(self, contract):
        calls["contract"] += 1
        return orig_register(self, contract)

    orig_refusal = IterativeCLIAdapter.check_refusal

    def counting_refusal(self, node, context=None):
        calls["refusal"] += 1
        return orig_refusal(node, context)

    monkeypatch.setattr(gates_mod.GateLedger, "parse", counting_parse)
    monkeypatch.setattr(gates_mod.GateEngine, "__init__", counting_engine_init)
    monkeypatch.setattr(DAFG, "register_contract", counting_register)
    monkeypatch.setattr(IterativeCLIAdapter, "check_refusal", counting_refusal)

    task = _task(
        [_node("n1")],
        expected_gates='- [ ] G1: x\n  CHECK: python3 -c "print(1)"\n  EXPECT: 1\n',
        contracts=[{"contract_id": "c1", "invariants": ["assert False"]}],
    )
    result = run_graph_only_trial(task, _stub_runner_fn(), 42, tmp_path)
    assert result.system_accepted is True
    assert calls == {"parse": 0, "engine": 0, "contract": 0, "refusal": 0}, (
        f"B2 invoked gate machinery: {calls}"
    )


def test_b2_accepts_when_stub_claims_complete(tmp_path):
    task = _task([_node("a"), _node("b", needs=["a"])])
    result = run_graph_only_trial(task, _stub_runner_fn(), 42, tmp_path)
    assert result.system_accepted is True
    assert result.deadlocked is False
    assert result.waves_used >= 1
    assert result.judge_outcome in ("VERIFIED_SUCCESS", "VERIFIED_FAILURE", "CORRECT_BLOCK",
                                   "EVALUATION_ERROR", "EXECUTION_ERROR")


def test_b2_deadlocks_cleanly_on_circular_needs(tmp_path):
    task = _task(
        [_node("c1", needs=["c2"]), _node("c2", needs=["c1"])],
        feasible=False,
    )
    result = run_graph_only_trial(task, _stub_runner_fn(), 42, tmp_path)
    assert result.deadlocked is True
    assert result.system_accepted is False
    # Same verdict the full DAFG scheduler produces on cycles.
    assert result.judge_outcome == "CORRECT_BLOCK"


def test_b2_uses_real_wave_scheduling(tmp_path):
    # Two nodes sharing one file must be serialized into separate waves
    # by the real compute_waves OWNS: partitioning.
    task = _task([_node("w1", owns=["shared.txt"]), _node("w2", owns=["shared.txt"])])
    result = run_graph_only_trial(task, _stub_runner_fn(), 42, tmp_path)
    assert result.system_accepted is True
    assert result.waves_used >= 2, f"expected OWNS: serialization, waves_used={result.waves_used}"


def test_b2_records_stub_failure_without_accepting(tmp_path):
    task = _task([_node("n1")])
    result = run_graph_only_trial(task, _stub_runner_fn(status="FAILED"), 42, tmp_path)
    assert result.system_accepted is False
    assert result.deadlocked is False
