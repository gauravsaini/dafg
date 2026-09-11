"""Tests for DAFG v0.3 Evaluation Engine & Decoupled Adapters."""

import pytest
from dafg import (
    BenchmarkTask,
    CompletionClaim,
    EvaluationHarness,
    EvaluationMetrics,
    EvaluationTrial,
    IterativeCLIAdapter,
    NodeStatus,
    ReActStateAdapter,
    StandardOutcome,
    TaskNode,
    ToolDispatchAdapter,
    validate_test_fixture_syntax,
)


def test_test_fixture_syntax_validator():
    """Verify pre-flight validation catches fixture syntax errors before evaluation."""
    # 1. Valid fixture
    valid_code = "import json\ndata = {'name': 'Alice'}\nassert data['name'] == 'Alice'"
    ok, err = validate_test_fixture_syntax(valid_code)
    assert ok is True
    assert err is None

    # 2. Defective fixture (unterminated string literal as identified in cat2_feat_04)
    broken_code = "csv_data = 'name,age,email\nunclosed string"
    ok, err = validate_test_fixture_syntax(broken_code)
    assert ok is False
    assert "SyntaxError" in err


def test_evaluation_harness_catches_evaluation_error():
    """Defective test fixture must be categorized as EVALUATION_ERROR, not agent failure."""
    harness = EvaluationHarness()
    task = BenchmarkTask(
        task_id="test_broken_fixture",
        title="Task with broken fixture",
        test_fixture="def bad(syntax: return",
    )
    adapter = IterativeCLIAdapter()
    trial = harness.run_trial(task, adapter=adapter, condition_name="cli")

    assert trial.standard_outcome == StandardOutcome.EVALUATION_ERROR
    assert "SyntaxError" in trial.error_reason


def test_metrics_computation_with_claims():
    """Verify correct-outcome rate, delivery success, and correct blocking calculations."""
    metrics = EvaluationMetrics(
        total_trials=10,
        feasible_trials=8,
        impossible_trials=2,
        verified_success_count=7,
        correct_block_count=2,
        verified_failure_count=1,
        total_tokens=50000,
        feasible_tokens=40000,
    )

    # Correct outcomes = 7 + 2 = 9 out of 10 = 90.0%
    assert metrics.correct_outcome_rate == 0.90
    # Delivery success = 7 out of 8 = 87.5%
    assert metrics.delivery_success_rate == 0.875
    # Correct blocking = 2 out of 2 = 100.0%
    assert metrics.correct_block_rate == 1.0
    # Tokens per correct outcome = 50000 / 9 = 5555.55
    assert round(metrics.tokens_per_correct_outcome, 1) == 5555.6
    # Tokens per delivery = 40000 / 7 = 5714.28
    assert round(metrics.tokens_per_delivery, 1) == 5714.3


def test_decoupled_adapters():
    """Verify all three decoupled agent adapters produce valid responses."""
    node = TaskNode(id="t_mod", title="Build module", owns=["src/mod.py"])
    ctx = {}

    # 1. Iterative CLI Adapter
    cli = IterativeCLIAdapter()
    resp_cli = cli.invoke(node, ctx)
    assert resp_cli.status == "COMPLETED"
    assert "src/mod.py" in resp_cli.files_modified
    assert cli.total_tokens_consumed > 0

    # 2. Tool Dispatch Adapter
    dispatch = ToolDispatchAdapter()
    resp_disp = dispatch.invoke(node, ctx)
    assert resp_disp.status == "COMPLETED"
    assert len(dispatch.dispatched_tool_calls) == 1
    assert dispatch.dispatched_tool_calls[0]["tool"] == "edit_file"

    # 3. ReAct State Adapter
    react = ReActStateAdapter()
    resp_react = react.invoke(node, ctx)
    assert resp_react.status == "COMPLETED"
    assert len(react.state_trace) > 0
    assert react.total_tokens_consumed > cli.total_tokens_consumed


def test_adapter_behavioral_divergence():
    """Verify each adapter displays its specific structural failure/success modes."""
    ctx = {}

    # 1. Hostile flaky environment: CLI fails due to shell exit code, ToolDispatch & ReAct succeed
    flaky_node = TaskNode(id="t_flk", title="Resilient Worker", metadata={"flaky_environment": True})
    cli_flaky = IterativeCLIAdapter().invoke(flaky_node, ctx)
    assert cli_flaky.status == "FAILED"
    assert "exited with code 1" in cli_flaky.output

    disp_flaky = ToolDispatchAdapter().invoke(flaky_node, ctx)
    assert disp_flaky.status == "COMPLETED"

    react_flaky = ReActStateAdapter().invoke(flaky_node, ctx)
    assert react_flaky.status == "COMPLETED"

    # 2. Schema mutation: ToolDispatch fails due to schema mismatch, CLI & ReAct succeed
    schema_node = TaskNode(id="t_sch", title="Mutated Schema Contract", metadata={"schema_mutation": True})
    disp_schema = ToolDispatchAdapter().invoke(schema_node, ctx)
    assert disp_schema.status == "FAILED"
    assert "SchemaValidationError" in disp_schema.output

    cli_schema = IterativeCLIAdapter().invoke(schema_node, ctx)
    assert cli_schema.status == "COMPLETED"

    react_schema = ReActStateAdapter().invoke(schema_node, ctx)
    assert react_schema.status == "COMPLETED"

    # 3. Deep horizon cascade: ReAct fails due to turn budget exhaustion, CLI & ToolDispatch succeed
    horizon_node = TaskNode(id="t_hrz", title="Deep Horizon Step 5", depth=5, metadata={"difficulty_dimension": "horizon"})
    react_horizon = ReActStateAdapter(max_turns=5).invoke(horizon_node, ctx)
    assert react_horizon.status == "FAILED"
    assert "reasoning budget exhausted" in react_horizon.output

    cli_horizon = IterativeCLIAdapter().invoke(horizon_node, ctx)
    assert cli_horizon.status == "COMPLETED"

    disp_horizon = ToolDispatchAdapter().invoke(horizon_node, ctx)
    assert disp_horizon.status == "COMPLETED"


def test_cross_adapter_benchmark_variance():
    """Verify v0.3 benchmark evaluation produces authentic variance and non-identical scores."""
    harness = EvaluationHarness()
    tasks = harness.load_builtin_tasks("v03")
    assert len(tasks) == 40

    cli_adapter = IterativeCLIAdapter()
    for task in tasks:
        harness.run_trial(task, adapter=cli_adapter, condition_name="cli")
    metrics_cli = harness.compute_metrics("cli")

    disp_adapter = ToolDispatchAdapter()
    for task in tasks:
        harness.run_trial(task, adapter=disp_adapter, condition_name="dispatch")
    metrics_disp = harness.compute_metrics("dispatch")

    react_adapter = ReActStateAdapter()
    for task in tasks:
        harness.run_trial(task, adapter=react_adapter, condition_name="react")
    metrics_react = harness.compute_metrics("react")

    # 1. Authentic variance: none of the adapters have saturated 100% scores on feasible tasks
    assert metrics_cli.delivery_success_rate < 1.0
    assert metrics_disp.delivery_success_rate < 1.0
    assert metrics_react.delivery_success_rate < 1.0

    # 2. Performance divergence: ReAct delivery success rate is lower due to deep horizon budget limits
    assert metrics_react.delivery_success_rate < metrics_cli.delivery_success_rate

    # 3. Token consumption hierarchy: ReAct > ToolDispatch > CLI
    assert metrics_react.total_tokens > metrics_disp.total_tokens
    assert metrics_disp.total_tokens > metrics_cli.total_tokens

    # 4. Correct blocking on impossible tasks is 100% across all adapters via protocol constraints
    assert metrics_cli.correct_block_rate == 1.0
    assert metrics_disp.correct_block_rate == 1.0
    assert metrics_react.correct_block_rate == 1.0

    # 5. Authentic failure distribution divergence: CLI and ToolDispatch fail on disjoint task sets
    cli_failures = {t.task_id for t in harness.trials if t.condition == "cli" and t.is_feasible and t.standard_outcome != StandardOutcome.VERIFIED_SUCCESS}
    disp_failures = {t.task_id for t in harness.trials if t.condition == "dispatch" and t.is_feasible and t.standard_outcome != StandardOutcome.VERIFIED_SUCCESS}
    assert len(cli_failures) == 5
    assert len(disp_failures) == 5
    assert cli_failures.isdisjoint(disp_failures)


def test_impossible_tasks_fail_via_protocol_constraints_not_keywords():
    """Verify impossible tasks fail strictly via protocol/runtime constraints without keyword reliance."""
    from dafg.runtime import DAFG, InterfaceContract

    harness = EvaluationHarness()
    tasks = harness.load_builtin_tasks("v03")
    impossible_tasks = [t for t in tasks if not t.is_feasible]
    assert len(impossible_tasks) == 10

    # Ensure none of the titles rely on 'unsolvable' or 'halting'
    forbidden_keywords = ["unsolvable", "halting", "provably impossible"]
    for task in impossible_tasks:
        for kw in forbidden_keywords:
            assert kw not in task.title.lower(), f"Task {task.task_id} title contains forbidden keyword '{kw}'"

    # Evaluate each impossible task through harness with CLI adapter
    adapter = IterativeCLIAdapter()
    for task in impossible_tasks:
        trial = harness.run_trial(task, adapter=adapter, condition_name="cli_check")
        assert trial.standard_outcome == StandardOutcome.CORRECT_BLOCK, (
            f"Impossible task {task.task_id} failed to block: {trial.standard_outcome}"
        )


def test_ondisk_telemetry_artifacts(tmp_path):
    """Verify inspectable on-disk JSON telemetry records are generated with per-trial granularity."""
    import json
    from pathlib import Path

    harness = EvaluationHarness()
    tasks = harness.load_builtin_tasks("v03", tier="calibration")
    adapter = IterativeCLIAdapter()

    for task in tasks:
        harness.run_trial(task, adapter=adapter, condition_name="cli")

    out_file = tmp_path / "eval_results" / "test_benchmark_cli.json"
    harness.save_results(out_file, suite="v03", adapter_name="cli", tier="calibration")
    assert out_file.exists()

    with open(out_file, "r") as f:
        data = json.load(f)

    assert data["suite"] == "v03"
    assert data["adapter"] == "cli"
    assert len(data["trials"]) == 10

    # Validate trial record granularity
    for trial_dict in data["trials"]:
        assert "trial_id" in trial_dict
        assert "task_id" in trial_dict
        assert "condition" in trial_dict
        assert "is_feasible" in trial_dict
        assert "completion_claim" in trial_dict
        assert "standard_outcome" in trial_dict
        assert "tokens_consumed" in trial_dict
        assert "duration_seconds" in trial_dict

    # Validate matrix update
    matrix_file = tmp_path / "eval_results" / "benchmark_matrix_v03.json"
    EvaluationHarness.update_benchmark_matrix(
        matrix_file, suite="v03", adapter_name="cli", metrics=harness.compute_metrics("cli"), trials=harness.trials
    )
    assert matrix_file.exists()
    with open(matrix_file, "r") as f:
        mat = json.load(f)
    assert "cli" in mat["adapters"]
    assert mat["adapters"]["cli"]["trials_count"] == 10


def test_feasible_task_with_historical_keywords_in_title_not_blocked():
    """Verify that tasks containing historically forbidden keywords (e.g. 'halting', 'unsolvable')
    succeed when feasible, proving title keyword scanning is completely removed from runtime.
    """
    from dafg.runtime import DAFG, TaskNode, NodeStatus

    # Test with bypass disabled to force execute_node path
    graph = DAFG(enable_bypass=False)
    node1 = TaskNode(id="feat_halting_doc", title="Documentation for Halting Problem Analyzer", owns=["docs/halting.md"])
    node2 = TaskNode(id="feat_unsolvable_parser", title="Parser for Unsolvable Error Codes", owns=["src/unsolvable.py"])
    graph.add_node(node1)
    graph.add_node(node2)

    adapter = IterativeCLIAdapter()
    run_status = graph.run(executor_fn=adapter.invoke)
    assert run_status == "COMPLETED"
    assert node1.status == NodeStatus.ACCEPTED
    assert node2.status == NodeStatus.ACCEPTED
    assert node1.refusal_class is None
    assert node2.refusal_class is None


def test_adapter_architectural_vulnerabilities():
    """Verify detailed structural vulnerabilities: CLI raw text ambiguities, ToolDispatch argument validation,
    and ReAct step loops and observation truncations.
    """
    ctx = {}

    # CLI vulnerable to raw text ambiguity
    ambig_node = TaskNode(id="t_ambig", title="Ambiguous Shell Output", metadata={"raw_text_ambiguity": True})
    cli_resp = IterativeCLIAdapter().invoke(ambig_node, ctx)
    assert cli_resp.status == "FAILED"
    assert "RAW_TEXT_AMBIGUITY" in cli_resp.metadata.get("error", "")

    # ToolDispatch vulnerable to argument validation errors
    arg_node = TaskNode(id="t_arg", title="Type Mismatch Params", metadata={"invalid_arguments": True})
    disp_resp = ToolDispatchAdapter().invoke(arg_node, ctx)
    assert disp_resp.status == "FAILED"
    assert "ARGUMENT_VALIDATION_ERROR" in disp_resp.metadata.get("error", "")

    # ReAct vulnerable to step loops
    loop_node = TaskNode(id="t_loop", title="Repetitive Cyclic Reasoning", metadata={"step_loop": True})
    react_loop_resp = ReActStateAdapter(max_turns=3).invoke(loop_node, ctx)
    assert react_loop_resp.status == "FAILED"
    assert "STEP_LOOP_DETECTED" in react_loop_resp.metadata.get("error", "")

    # ReAct vulnerable to observation truncation
    trunc_node = TaskNode(id="t_trunc", title="Truncated Context Window", metadata={"observation_truncation": True})
    react_trunc_resp = ReActStateAdapter().invoke(trunc_node, ctx)
    assert react_trunc_resp.status == "FAILED"
    assert "OBSERVATION_TRUNCATED" in react_trunc_resp.metadata.get("error", "")


def test_dynamic_needs_horizon_budget_interaction():
    """Verify that deep dependency chains via 'needs' without explicit depth parameters
    correctly compute effective horizon depth, exhausting ReAct's turn budget while CLI succeeds.
    """
    from dafg.runtime import DAFG, TaskNode

    # Create a 5-step dependency chain via 'needs' with depth=0
    graph = DAFG()
    for i in range(1, 6):
        n = TaskNode(
            id=f"step_{i}",
            title=f"Cascading Step {i}",
            needs=[f"step_{i-1}"] if i > 1 else [],
            owns=[f"src/file_{i}.py"],
            metadata={"difficulty_dimension": "horizon"},
        )
        graph.add_node(n)

    # CLI executes full cascade successfully
    cli_graph = DAFG()
    for n in graph.nodes.values():
        cli_graph.add_node(TaskNode.from_dict(n.to_dict()))
    cli_status = cli_graph.run(executor_fn=IterativeCLIAdapter().invoke)
    assert cli_status == "COMPLETED"

    # ReAct exhausts reasoning budget on step 5 (effective depth >= 4)
    react_graph = DAFG()
    for n in graph.nodes.values():
        react_graph.add_node(TaskNode.from_dict(n.to_dict()))
    react_status = react_graph.run(executor_fn=ReActStateAdapter(max_turns=5).invoke)
    assert react_status in ("FAILED", "BLOCKED")
    assert react_graph.nodes["step_5"].status in (NodeStatus.FAILED, NodeStatus.REJECTED)


def test_custom_adapter_unexpected_return_types():
    """Verify that executors returning dicts, None, or unexpected types are handled safely."""
    from dafg.runtime import DAFG, TaskNode, NodeStatus

    # 1. Adapter returning dict: auto-converted to AgentResponse
    graph1 = DAFG()
    n1 = TaskNode(id="n1", title="Dict Return Worker", owns=["src/out.py"])
    graph1.add_node(n1)
    status1 = graph1.run(executor_fn=lambda node, ctx: {"status": "COMPLETED", "output": "dict output"})
    assert status1 == "COMPLETED"
    assert n1.status == NodeStatus.ACCEPTED

    # 2. Adapter returning None: safely handled as execution error, node marked REJECTED/FAILED
    graph2 = DAFG()
    n2 = TaskNode(id="n2", title="None Return Worker", max_revisions=1)
    graph2.add_node(n2)
    status2 = graph2.run(executor_fn=lambda node, ctx: None)
    assert status2 in ("FAILED", "BLOCKED")
    assert n2.status in (NodeStatus.FAILED, NodeStatus.REJECTED)

    # 3. Adapter returning invalid type: safely handled as execution error
    graph3 = DAFG()
    n3 = TaskNode(id="n3", title="Int Return Worker", max_revisions=1)
    graph3.add_node(n3)
    status3 = graph3.run(executor_fn=lambda node, ctx: 12345)  # type: ignore
    assert status3 in ("FAILED", "BLOCKED")
    assert n3.status in (NodeStatus.FAILED, NodeStatus.REJECTED)


def test_trial_telemetry_captures_rich_error_trace():
    """Verify that persisted evaluation trials capture the detailed error trace from execution history."""
    harness = EvaluationHarness()
    tasks = harness.load_builtin_tasks("v03", tier="calibration")
    flaky_task = next(t for t in tasks if "flaky" in t.task_id)

    trial = harness.run_trial(flaky_task, adapter=IterativeCLIAdapter(), condition_name="cli")
    assert trial.standard_outcome == StandardOutcome.VERIFIED_FAILURE
    assert trial.error_reason is not None
    assert "exited with code 1" in trial.error_reason


def test_evaluation_metrics_and_benchmark_task_from_dict():
    """Verify EvaluationMetrics and BenchmarkTask roundtrip serialization and deserialization."""
    from dafg.runtime import InterfaceContract

    # 1. EvaluationMetrics from_dict roundtrip
    m_orig = EvaluationMetrics(
        total_trials=20,
        feasible_trials=15,
        impossible_trials=5,
        verified_success_count=12,
        correct_block_count=5,
        verified_failure_count=3,
        total_tokens=25000,
        feasible_tokens=20000,
    )
    m_dict = m_orig.to_dict()
    m_restored = EvaluationMetrics.from_dict(m_dict)
    assert m_restored.total_trials == m_orig.total_trials
    assert m_restored.verified_success_count == m_orig.verified_success_count
    assert m_restored.correct_block_count == m_orig.correct_block_count
    assert m_restored.delivery_success_rate == m_orig.delivery_success_rate
    assert m_restored.correct_block_rate == m_orig.correct_block_rate
    assert m_restored.tokens_per_correct_outcome == m_orig.tokens_per_correct_outcome

    # 2. BenchmarkTask from_dict roundtrip
    task_orig = BenchmarkTask(
        task_id="t_roundtrip",
        title="Roundtrip Test",
        tier="dev",
        is_feasible=True,
        initial_nodes=[TaskNode(id="n1", title="Node 1", owns=["src/n1.py"])],
        contracts=[InterfaceContract(contract_id="c1", owner="n1")],
    )
    task_dict = task_orig.to_dict()
    task_restored = BenchmarkTask.from_dict(task_dict)
    assert task_restored.task_id == task_orig.task_id
    assert len(task_restored.initial_nodes) == 1
    assert task_restored.initial_nodes[0].id == "n1"
    assert len(task_restored.contracts) == 1
    assert task_restored.contracts[0].contract_id == "c1"


def test_adapter_stale_dispatch_dict_epoch_propagation():
    """Verify that dispatch_identity passed as a dict with stale epoch correctly sets
    response.epoch and response.dispatch_identity without silent fallback to node.epoch.
    """
    node = TaskNode(id="n_epoch", title="Epoch Node")
    node.epoch = 2  # Current epoch is 2

    # Provide context with stale epoch = 1 as dictionary
    stale_disp_dict = {
        "run_id": "run_test",
        "node_id": "n_epoch",
        "epoch": 1,  # Stale epoch!
        "attempt_id": 1,
        "context_snapshot_id": "snap_1",
        "contract_version": 1,
    }
    context = {"dispatch_identity": stale_disp_dict}

    for adapter in [IterativeCLIAdapter(), ToolDispatchAdapter(), ReActStateAdapter()]:
        resp = adapter.invoke(node, context)
        assert resp.epoch == 1, f"Adapter {adapter.name} failed to preserve stale epoch from dict"
        assert resp.dispatch_identity is not None
        assert resp.dispatch_identity.epoch == 1


def test_tool_dispatch_unavailable_tool_metadata():
    """Verify ToolDispatchAdapter fails when node metadata specifies an unavailable tool."""
    node = TaskNode(
        id="t_tool_unavail",
        title="Custom Compiler Task",
        metadata={"tool_unavailable": True, "required_tool": "rustc_bindgen"},
    )
    adapter = ToolDispatchAdapter()
    resp = adapter.invoke(node, {})
    assert resp.status == "FAILED"
    assert resp.metadata.get("error") == "MISSING_TOOL"
    assert "rustc_bindgen" in resp.output


def test_evaluation_harness_blocked_trial_captures_refusal_reason():
    """Verify that feasible tasks blocked pre-dispatch preserve their specific refusal reason in trial telemetry."""
    task = BenchmarkTask(
        task_id="t_blocked_feasible",
        title="Feasible Task Blocked for Authorization",
        tier="dev",
        is_feasible=True,
        initial_nodes=[TaskNode(id="n_auth", title="Privileged Operation", requires_permissions=True)],
    )
    harness = EvaluationHarness()
    trial = harness.run_trial(task, adapter=IterativeCLIAdapter(), condition_name="cli")
    assert trial.standard_outcome == StandardOutcome.VERIFIED_FAILURE
    assert trial.completion_claim == CompletionClaim.BLOCKED
    assert trial.error_reason is not None
    assert "elevated permissions" in trial.error_reason


def test_combined_simultaneous_failure_modes():
    """Verify behavior under combined simultaneous failure modes (flaky tool + schema mutation + deep horizon).
    Each adapter exhibits its distinct dominant architectural failure cleanly without crashing.
    """
    ctx = {}
    combined_node = TaskNode(
        id="t_combined",
        title="Multi-Failure Cascading Node",
        depth=5,
        metadata={
            "flaky_environment": True,
            "flaky_tools": True,
            "schema_mutation": True,
            "difficulty_dimension": "horizon",
        },
    )

    # 1. CLI fails due to flaky environment shell error
    cli_resp = IterativeCLIAdapter().invoke(combined_node, ctx)
    assert cli_resp.status == "FAILED"
    assert "exited with code 1" in cli_resp.output

    # 2. ToolDispatch fails due to schema mutation
    disp_resp = ToolDispatchAdapter().invoke(combined_node, ctx)
    assert disp_resp.status == "FAILED"
    assert "SchemaValidationError" in disp_resp.output

    # 3. ReAct fails due to horizon reasoning budget exhaustion
    react_resp = ReActStateAdapter(max_turns=5).invoke(combined_node, ctx)
    assert react_resp.status == "FAILED"
    assert "reasoning budget exhausted" in react_resp.output


def test_protocol_audit_catches_intentionally_imperfect_runs(tmp_path):
    """Verify ProtocolAuditRunner detects real violations and refuses to rubber-stamp intentionally imperfect runs."""
    from dafg.eval import ProtocolAuditRunner
    from dafg.gates import Gate, GateLedger

    runner = ProtocolAuditRunner()

    # 1. Event trace with post-seal mutation
    events_post_seal = [
        {"action": "LOAD_CONTEXT", "to_state": "CONTEXT_LOADED", "node_id": "n1", "epoch": 1},
        {"event_type": "RUN_SEALED", "action": "SEAL_RUN", "node_id": None},
        {"action": "DISPATCH_PROVE", "to_state": "PROVING", "node_id": "n1", "epoch": 1},
    ]
    report1 = runner.audit_event_trace(events_post_seal)
    assert report1["passed"] is False
    assert any("RUN_SEALED_VIOLATION" in v for v in report1["violations"])

    # 2. Event trace with illegal state jump (IDLE directly to ACCEPT_VERDICT)
    events_illegal_jump = [
        {"action": "ACCEPT_VERDICT", "to_state": "ACCEPTED", "node_id": "n1", "epoch": 1},
    ]
    report2 = runner.audit_event_trace(events_illegal_jump)
    assert report2["passed"] is False
    assert any("ILLEGAL_TRANSITION_VIOLATION" in v for v in report2["violations"])

    # 3. Event trace with epoch regression (epoch rolled backward from 2 to 1)
    events_epoch_reg = [
        {"action": "LOAD_CONTEXT", "to_state": "CONTEXT_LOADED", "node_id": "n1", "epoch": 2},
        {"action": "DISPATCH_PROVE", "to_state": "PROVING", "node_id": "n1", "epoch": 1},
    ]
    report3 = runner.audit_event_trace(events_epoch_reg)
    assert report3["passed"] is False
    assert any("EPOCH_REGRESSION_VIOLATION" in v for v in report3["violations"])

    # 4. Valid event trace passes cleanly
    events_valid = [
        {"action": "LOAD_CONTEXT", "to_state": "CONTEXT_LOADED", "node_id": "n1", "epoch": 1},
        {"action": "DISPATCH_PROVE", "to_state": "PROVING", "node_id": "n1", "epoch": 1},
        {"action": "CHALLENGE", "to_state": "CHALLENGING", "node_id": "n1", "epoch": 1},
        {"action": "SUBMIT_EVIDENCE", "to_state": "VERIFYING", "node_id": "n1", "epoch": 1},
        {"action": "ACCEPT_VERDICT", "to_state": "ACCEPTED", "node_id": "n1", "epoch": 1},
    ]
    report_valid = runner.audit_event_trace(events_valid)
    assert report_valid["passed"] is True
    assert len(report_valid["violations"]) == 0

    # 5. State audit: Node marked ACCEPTED with assigned gate lacking verified evidence
    ledger = GateLedger.parse("- [ ] G_unverified: Unverified Gate\n  CHECK: echo hi\n  EXPECT: hi\n")
    state_unverified = {
        "nodes": {
            "n1": {
                "status": "ACCEPTED",
                "protocol_state": "ACCEPTED",
                "assigned_gates": ["G_unverified"],
            }
        }
    }
    report_state = runner.audit_state(state_unverified, ledger=ledger)
    assert report_state["passed"] is False
    assert any("UNVERIFIED_ACCEPTANCE_VIOLATION" in v for v in report_state["violations"])


def test_protocol_audit_cli_trace_and_state(tmp_path):
    """Verify dafg audit CLI rejects imperfect traces with non-zero exit code and accepts clean runs."""
    import json
    from dafg.cli import main

    # Imperfect trace file
    bad_trace = tmp_path / "bad_trace.json"
    bad_trace.write_text(json.dumps([
        {"action": "ACCEPT_VERDICT", "to_state": "ACCEPTED", "node_id": "n1", "epoch": 1}
    ]))
    out_bad = tmp_path / "out_bad.json"
    ret_bad = main(["audit", "--trace", str(bad_trace), "--out", str(out_bad), "--json"])
    assert ret_bad == 1
    assert out_bad.exists()
    with open(out_bad) as f:
        rep_bad = json.load(f)
    assert rep_bad["passed"] is False

    # Clean trace file
    good_trace = tmp_path / "good_trace.json"
    good_trace.write_text(json.dumps([
        {"action": "LOAD_CONTEXT", "to_state": "CONTEXT_LOADED", "node_id": "n1", "epoch": 1},
        {"action": "DISPATCH_PROVE", "to_state": "PROVING", "node_id": "n1", "epoch": 1},
    ]))
    out_good = tmp_path / "out_good.json"
    ret_good = main(["audit", "--trace", str(good_trace), "--out", str(out_good), "--json"])
    assert ret_good == 0
    assert out_good.exists()
    with open(out_good) as f:
        rep_good = json.load(f)
    assert rep_good["passed"] is True

    # State audit via CLI: unverified gate
    bad_state = tmp_path / "bad_state.json"
    bad_state.write_text(json.dumps({
        "nodes": {
            "n1": {
                "status": "ACCEPTED",
                "protocol_state": "ACCEPTED",
                "assigned_gates": ["G_unverified"],
            }
        }
    }))
    out_bad_state = tmp_path / "out_bad_state.json"
    ret_bad_state = main(["audit", "--state", str(bad_state), "--out", str(out_bad_state), "--json"])
    assert ret_bad_state == 1
    assert out_bad_state.exists()
    with open(out_bad_state) as f:
        rep_bad_state = json.load(f)
    assert rep_bad_state["passed"] is False

    # Missing trace / state file handling
    ret_missing = main(["audit", "--trace", str(tmp_path / "nonexistent.json"), "--json"])
    assert ret_missing == 1


def test_trial_telemetry_schema_compliance():
    """Verify EvaluationTrial captures adapter, error_trace, and roundtrips cleanly."""
    trial = EvaluationTrial(
        trial_id="trial_101",
        task_id="task_101",
        condition="cli",
        is_feasible=True,
        completion_claim=CompletionClaim.SUCCESS,
        standard_outcome=StandardOutcome.VERIFIED_SUCCESS,
        tokens_consumed=500,
        duration_seconds=0.12,
        error_reason="None",
        adapter="iterative-cli",
        error_trace="None",
    )
    d = trial.to_dict()
    assert d["adapter"] == "iterative-cli"
    assert d["condition"] == "cli"
    assert d["error_trace"] == "None"
    assert d["error_reason"] == "None"
    assert d["tokens_consumed"] == 500
    assert d["duration_seconds"] == 0.12

    restored = EvaluationTrial.from_dict(d)
    assert restored.adapter == "iterative-cli"
    assert restored.condition == "cli"
    assert restored.error_trace == "None"
    assert restored.error_reason == "None"
    assert restored.standard_outcome == StandardOutcome.VERIFIED_SUCCESS


def test_cli_eval_clean_json_output(capsys):
    """Verify dafg eval --json outputs parseable JSON without stdout text contamination."""
    import json
    from dafg.cli import main

    ret = main(["eval", "--suite", "v03", "--adapter", "cli", "--tier", "dev", "--json"])
    assert ret == 0
    captured = capsys.readouterr()
    # Output must be pure JSON
    parsed = json.loads(captured.out)
    assert "total_trials" in parsed
    assert parsed["total_trials"] == 10
    assert "delivery_success_rate" in parsed


def test_agent_response_epoch_inference_and_stale_rejection():
    """Verify AgentResponse infers epoch from dispatch_identity and DAFG rejects stale responses."""
    from dafg.protocol import DispatchIdentity
    from dafg.runtime import DAFG, TaskNode, NodeStatus, AgentResponse

    # 1. AgentResponse constructor infers epoch
    disp = DispatchIdentity(
        run_id="run_1",
        node_id="n1",
        epoch=1,
        attempt_id=1,
        context_snapshot_id="s1",
        contract_version=1,
    )
    resp = AgentResponse(dispatch_identity=disp)
    assert resp.epoch == 1

    # 2. from_dict infers epoch and normalizes dispatch_identity
    resp2 = AgentResponse.from_dict({"dispatch_identity": disp.to_dict()})
    assert resp2.epoch == 1
    assert isinstance(resp2.dispatch_identity, DispatchIdentity)

    # 3. DAFG runtime rejects stale response even when epoch is inside dispatch_identity dict
    graph = DAFG()
    node = TaskNode("n1", "Work Node")
    node.epoch = 2
    graph.add_node(node)

    # Executor returns response carrying stale epoch 1
    def stale_executor(n, ctx):
        return {"output": "Done", "status": "COMPLETED", "dispatch_identity": {"epoch": 1}}

    status = graph.run(executor_fn=stale_executor)
    assert node.status in (NodeStatus.FAILED, NodeStatus.REJECTED, NodeStatus.READY)
    assert node.status != NodeStatus.ACCEPTED


def test_protocol_command_dict_dispatch_identity():
    """Verify ProtocolCommand normalizes dict dispatch_identity for ProtocolEngine."""
    from dafg.protocol import Action, DispatchIdentity, ProtocolCommand, ProtocolEngine, ProtocolState
    from dafg.runtime import DAFG, TaskNode

    graph = DAFG()
    node = TaskNode("n1", "Node")
    node.protocol_state = ProtocolState.VERIFYING
    disp = DispatchIdentity(
        run_id=graph.run_id,
        node_id="n1",
        epoch=node.epoch,
        attempt_id=1,
        context_snapshot_id="s1",
        contract_version=1,
    )
    node.active_dispatch = disp.to_dict()  # As dict
    graph.add_node(node)

    cmd = ProtocolCommand(
        idempotency_key="cmd_dict_disp",
        action=Action.ACCEPT_VERDICT,
        node_id="n1",
        run_id=graph.run_id,
        dispatch_identity=disp.to_dict(),  # As dict
    )
    assert isinstance(cmd.dispatch_identity, DispatchIdentity)

    events, record = graph.submit_command(cmd)
    assert record is None
    assert len(events) == 1
    assert events[0].to_state == "ACCEPTED"


def test_protocol_audit_sealed_active_node_violation():
    """Verify ProtocolAuditRunner detects active/unsettled nodes in a sealed run state."""
    from dafg.eval import ProtocolAuditRunner

    runner = ProtocolAuditRunner()
    state_sealed_with_running = {
        "is_sealed": True,
        "nodes": {
            "n1": {"status": "RUNNING", "protocol_state": "PROVING"},
        },
    }
    report = runner.audit_state(state_sealed_with_running)
    assert report["passed"] is False
    assert any("SEALED_RUN_ACTIVE_NODE_VIOLATION" in v for v in report["violations"])


def test_iterative_cli_runner_fn_agent_response():
    """Verify IterativeCLIAdapter properly handles runner_fn returning an AgentResponse object."""
    from dafg.runtime import AgentResponse

    node = TaskNode("t_cli_agent", "CLI Test")
    custom_resp = AgentResponse(output="Custom runner finished", status="COMPLETED", files_modified=["src/custom.py"])
    adapter = IterativeCLIAdapter(runner_fn=lambda out, n: custom_resp)
    resp = adapter.invoke(node, {})
    assert resp.output == "Custom runner finished"
    assert resp.status == "COMPLETED"
    assert resp.files_modified == ["src/custom.py"]


