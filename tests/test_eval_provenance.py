"""Tests for persisted benchmark provenance."""

import json

from dafg.eval import EvaluationHarness


def test_save_results_persists_explicit_manifest(tmp_path):
    harness = EvaluationHarness(
        benchmark_revision="fixture-v1",
        command="uv run dafg eval --suite v03 --adapter cli",
        model_backend="fixture-adapter",
        seed=7,
        oracle_revision="oracle-v2",
    )
    output = tmp_path / "results.json"

    harness.save_results(output, suite="v03", adapter_name="cli", tier="dev")

    manifest = json.loads(output.read_text(encoding="utf-8"))["manifest"]
    assert manifest["run_id"]
    assert manifest["suite"] == "v03"
    assert manifest["tier"] == "dev"
    assert manifest["adapter"] == "cli"
    assert manifest["benchmark_revision"] == "fixture-v1"
    assert manifest["command"].startswith("uv run dafg eval")
    assert manifest["model_backend"] == "fixture-adapter"
    assert manifest["seed"] == 7
    assert manifest["oracle_revision"] == "oracle-v2"
    assert len(manifest["environment_digest"]) == 64


def test_save_results_does_not_invent_optional_provenance(tmp_path):
    harness = EvaluationHarness()
    output = tmp_path / "results.json"

    harness.save_results(output, suite="v03", adapter_name="cli")

    manifest = json.loads(output.read_text(encoding="utf-8"))["manifest"]
    assert manifest["benchmark_revision"] is None
    assert manifest["command"] is None
    assert manifest["model_backend"] is None
    assert manifest["seed"] is None
    assert manifest["oracle_revision"] is None


def test_cli_eval_loop_passes_explicit_provenance(monkeypatch, tmp_path):
    from dafg import cli

    captured = []
    real_init = EvaluationHarness.__init__

    def mock_init(self, *args, **kwargs):
        captured.append(kwargs)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(EvaluationHarness, "__init__", mock_init)
    monkeypatch.setattr(EvaluationHarness, "load_builtin_tasks", lambda self, *a, **kw: [])
    monkeypatch.setattr(EvaluationHarness, "save_results", lambda *a, **kw: None)
    monkeypatch.setattr(EvaluationHarness, "update_benchmark_matrix", lambda *a, **kw: None)

    ret = cli.main(["eval", "--suite", "v03", "--tier", "dev", "--adapter", "cli", "--out", str(tmp_path / "out.json")])
    assert ret == 0
    assert len(captured) == 1
    assert captured[0]["command"] == "uv run dafg eval --suite v03 --tier dev --adapter cli"
    assert captured[0]["benchmark_revision"] == "v03"
    assert captured[0]["model_backend"] == "iterative-cli"


def test_cli_eval_loop_passes_explicit_provenance_without_tier(monkeypatch, tmp_path):
    from dafg import cli

    captured = []
    real_init = EvaluationHarness.__init__

    def mock_init(self, *args, **kwargs):
        captured.append(kwargs)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(EvaluationHarness, "__init__", mock_init)
    monkeypatch.setattr(EvaluationHarness, "load_builtin_tasks", lambda self, *a, **kw: [])
    monkeypatch.setattr(EvaluationHarness, "save_results", lambda *a, **kw: None)
    monkeypatch.setattr(EvaluationHarness, "update_benchmark_matrix", lambda *a, **kw: None)

    ret = cli.main(["eval", "--suite", "v02-regression", "--adapter", "dispatch", "--out", str(tmp_path / "out.json")])
    assert ret == 0
    assert len(captured) == 1
    assert captured[0]["command"] == "uv run dafg eval --suite v02-regression --adapter dispatch"
    assert captured[0]["benchmark_revision"] == "v02-regression"
    assert captured[0]["model_backend"] == "tool-dispatch"


def test_cli_eval_loop_all_adapters(monkeypatch, tmp_path):
    from dafg import cli

    captured = []
    real_init = EvaluationHarness.__init__

    def mock_init(self, *args, **kwargs):
        captured.append(kwargs)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(EvaluationHarness, "__init__", mock_init)
    monkeypatch.setattr(EvaluationHarness, "load_builtin_tasks", lambda self, *a, **kw: [])
    monkeypatch.setattr(EvaluationHarness, "save_results", lambda *a, **kw: None)
    monkeypatch.setattr(EvaluationHarness, "update_benchmark_matrix", lambda *a, **kw: None)

    ret = cli.main(["eval", "--suite", "v03", "--tier", "calibration", "--all-adapters"])
    assert ret == 0
    assert len(captured) == 3
    assert captured[0]["command"] == "uv run dafg eval --suite v03 --tier calibration --adapter cli"
    assert captured[0]["model_backend"] == "iterative-cli"
    assert captured[1]["command"] == "uv run dafg eval --suite v03 --tier calibration --adapter dispatch"
    assert captured[1]["model_backend"] == "tool-dispatch"
    assert captured[2]["command"] == "uv run dafg eval --suite v03 --tier calibration --adapter react"
    assert captured[2]["model_backend"] == "react-state-machine"

