"""Tests for the real-model eval apparatus: baseline trial, fail-loud agent_cli, true token accounting.

Coverage:
- run_baseline_trial plumbing (mock runner, no network): dependency order,
  file materialization, workdir isolation, real token totals.
- Model-level REFUSE on impossible tasks -> CORRECT_BLOCK.
- agent_cli --mode real fails loud (no silent Gen-4 fallback).
- IterativeCLIAdapter uses true usage when runner_fn provides it, legacy
  formula otherwise.
- materialize_files rejects path traversal.

All tests are offline; the HTTP layer is never touched (mock runner_fn).
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from dafg.adapters import IterativeCLIAdapter
from dafg.baseline import (
    build_agent_prompt,
    materialize_files,
    run_baseline_trial,
    topo_order,
)
from dafg.eval import BenchmarkTask, StandardOutcome
from dafg.runtime import TaskNode

AGENT_CLI = Path(__file__).resolve().parents[1] / "experiments" / "real_world_agent_eval" / "agent_worker" / "agent_cli.py"


def load_agent_cli():
    spec = importlib.util.spec_from_file_location("agent_cli_under_test", AGENT_CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_task(task_id="t1", feasible=True, nodes=None):
    if nodes is None:
        nodes = [
            TaskNode(id="n1", title="First", owns=["a.py"]),
            TaskNode(id="n2", title="Second", needs=["n1"], owns=["b.py"]),
        ]
    return BenchmarkTask(
        task_id=task_id,
        title="Test task",
        is_feasible=feasible,
        initial_nodes=nodes,
        test_fixture="assert True",
    )


def mock_runner_factory(calls, usage_total=1500, refuse=False):
    def fn(prompt, node):
        calls.append(node.id)
        usage = {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": usage_total}
        if refuse:
            return {"output": "REFUSE: contradictory spec", "status": "COMPLETED",
                    "files_modified": [], "metadata": {}, "usage": usage}
        blocks = "".join(f"```path:{p}\nX = 1\n```\n" for p in node.owns)
        return {"output": blocks, "status": "COMPLETED", "files_modified": list(node.owns),
                "metadata": {}, "usage": usage}

    return fn


def test_topo_order_respects_needs():
    n1 = TaskNode(id="n1", title="a")
    n2 = TaskNode(id="n2", title="b", needs=["n1"])
    n3 = TaskNode(id="n3", title="c", needs=["n2"])
    ordered = [n.id for n in topo_order([n3, n1, n2])]
    assert ordered == ["n1", "n2", "n3"]


def test_build_agent_prompt_mentions_owns_and_refuse():
    task = make_task()
    prompt = build_agent_prompt(task)
    assert "a.py" in prompt and "b.py" in prompt
    assert "REFUSE:" in prompt
    assert "```path:" in prompt


def test_materialize_rejects_traversal(tmp_path):
    out = materialize_files("```path:../../evil.py\nX=1\n```\n```path:ok.py\nY=2\n```", tmp_path)
    assert out == ["ok.py"]
    assert (tmp_path / "ok.py").exists()
    assert not (tmp_path.parent / "evil.py").exists()


def test_baseline_trial_plumbing(tmp_path):
    calls = []
    task = make_task()
    workdir = tmp_path / "w1"
    result = run_baseline_trial(task, mock_runner_factory(calls), seed=42, workdir=workdir)
    trial = result.trial
    # Dependency order honored
    assert calls == ["n1", "n2"]
    # Files materialized into the isolated workdir
    assert (workdir / "a.py").exists() and (workdir / "b.py").exists()
    assert set(result.files_materialized) == {"a.py", "b.py"}
    # Real token accounting: 2 calls x 1500, not the len(title)*4+180 formula
    assert trial.tokens_consumed == 3000
    assert trial.condition == "A-baseline"
    assert trial.standard_outcome == StandardOutcome.VERIFIED_SUCCESS
    assert result.judge_outcome == "VERIFIED_SUCCESS"
    assert result.judge_passed is True


def test_baseline_refusal_impossible_task(tmp_path):
    calls = []
    task = make_task(task_id="imp1", feasible=False,
                     nodes=[TaskNode(id="n1", title="Impossible", owns=["x.py"])])
    workdir = tmp_path / "w2"
    result = run_baseline_trial(task, mock_runner_factory(calls, refuse=True), seed=42, workdir=workdir)
    assert result.trial.standard_outcome == StandardOutcome.CORRECT_BLOCK
    assert result.judge_outcome == "CORRECT_BLOCK"


def test_baseline_false_success_when_model_claims_impossible(tmp_path):
    calls = []
    task = make_task(task_id="imp2", feasible=False,
                     nodes=[TaskNode(id="n1", title="Impossible", owns=["x.py"])])
    workdir = tmp_path / "w3"
    result = run_baseline_trial(task, mock_runner_factory(calls, refuse=False), seed=42, workdir=workdir)
    # Model claimed completion on an impossible task -> judge flags false success
    assert result.judge_false_success is True
    assert result.trial.standard_outcome == StandardOutcome.VERIFIED_FAILURE


def test_token_accounting_uses_real_usage():
    adapter = IterativeCLIAdapter(runner_fn=lambda p, n: {
        "output": "done", "status": "COMPLETED", "files_modified": [],
        "metadata": {}, "usage": {"prompt_tokens": 100, "completion_tokens": 34, "total_tokens": 134},
    })
    node = TaskNode(id="n1", title="Some reasonably long task title here")
    adapter.invoke(node, {})
    assert adapter.total_tokens_consumed == 134


def test_token_accounting_legacy_without_usage():
    adapter = IterativeCLIAdapter(runner_fn=lambda p, n: {"output": "done", "status": "COMPLETED"})
    node = TaskNode(id="n1", title="Some reasonably long task title here")
    adapter.invoke(node, {})
    # Legacy stub formula preserved exactly when no usage is provided
    assert adapter.total_tokens_consumed == len(node.title) * 4 + 180 + 60


def test_agent_cli_real_mode_fails_loud_no_binary(tmp_path, monkeypatch):
    mod = load_agent_cli()
    monkeypatch.setattr(mod.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["agent_cli.py", "--mode", "real",
                                     "--workdir", str(tmp_path), "--goal", "test"])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    # Error record written, staged Gen-4 code NEVER substituted
    record = json.loads((tmp_path / "real_agent_error.json").read_text())
    assert record["ok"] is False and record["mode"] == "real"
    assert list((tmp_path / "src").glob("*.py")) == [] if (tmp_path / "src").exists() else True


def test_agent_cli_real_mode_fails_loud_nonzero_exit(tmp_path, monkeypatch):
    mod = load_agent_cli()
    fake_bin = tmp_path / "fake-agent"
    fake_bin.write_text("#!/bin/sh\nexit 3\n")
    fake_bin.chmod(0o755)
    monkeypatch.setattr(mod.shutil, "which", lambda name: str(fake_bin) if name == "codex" else None)
    monkeypatch.setattr(sys, "argv", ["agent_cli.py", "--mode", "real",
                                     "--workdir", str(tmp_path), "--goal", "test"])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
    assert "code 3" in (tmp_path / "real_agent_error.json").read_text()


def test_agent_cli_staged_mode_untouched(tmp_path, monkeypatch):
    mod = load_agent_cli()
    monkeypatch.setattr(sys, "argv", ["agent_cli.py", "--mode", "staged", "--generation", "1",
                                     "--workdir", str(tmp_path)])
    mod.main()  # must not raise
    assert (tmp_path / "src" / "server.py").exists()
