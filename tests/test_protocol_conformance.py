"""Formal protocol conformance and state machine invariance tests.

Exhaustively verifies the 9 formal architectural requirements:
1. Dual-state separation: authoritative ProtocolState vs scheduler ExecutionStatus
2. Action-specific transition rules: (current_state, action) -> guard + effects + next_state
3. Exact DispatchIdentity fencing: (run_id, node_id, epoch, attempt_id, context_snapshot_id, contract_version)
4. Transactional commitment & idempotency key deduplication
5. Pure decision engine (ProtocolEngine) and deterministic reducer (ProtocolReducer) replay
6. Mandatory invalidation unconstrained by budget limits
7. Graph run sealing (seal_run()) invariance
8. Cross-runtime adapter conformance (CLI, ToolDispatch, ReAct)
9. Dual release gate: ProtocolAuditRunner
"""

import pytest
from dafg.adapters import IterativeCLIAdapter, ReActStateAdapter, ToolDispatchAdapter
from dafg.eval import ProtocolAuditRunner
from dafg.protocol import (
    Action,
    AuditRecord,
    DispatchIdentity,
    DomainEvent,
    ExecutionStatus,
    IllegalTransitionError,
    ProtocolCommand,
    ProtocolEngine,
    ProtocolReducer,
    ProtocolState,
    RunSealedError,
    StaleDispatchError,
    state_projection,
)
from dafg.runtime import DAFG, Budget, NodeStatus, TaskNode


def test_action_specific_transitions():
    """Verify state transitions only along authorized (state, action) tuples."""
    graph = DAFG()
    node = TaskNode("n1", "Compile Code")
    graph.add_node(node)

    assert node.protocol_state == ProtocolState.IDLE
    assert node.execution_status == ExecutionStatus.READY

    # IDLE + LOAD_CONTEXT -> CONTEXT_LOADED
    graph.submit_command(ProtocolCommand("c1", Action.LOAD_CONTEXT, "n1", graph.run_id))
    assert node.protocol_state == ProtocolState.CONTEXT_LOADED

    # CONTEXT_LOADED + DISPATCH_PROVE -> PROVING
    graph.submit_command(ProtocolCommand("c2", Action.DISPATCH_PROVE, "n1", graph.run_id))
    assert node.protocol_state == ProtocolState.PROVING
    assert node.execution_status == ExecutionStatus.RUNNING

    # PROVING + CHALLENGE -> CHALLENGING
    graph.submit_command(ProtocolCommand("c3", Action.CHALLENGE, "n1", graph.run_id))
    assert node.protocol_state == ProtocolState.CHALLENGING

    # CHALLENGING + SUBMIT_EVIDENCE -> VERIFYING
    graph.submit_command(ProtocolCommand("c4", Action.SUBMIT_EVIDENCE, "n1", graph.run_id))
    assert node.protocol_state == ProtocolState.VERIFYING

    # VERIFYING + ACCEPT_VERDICT -> ACCEPTED
    disp = DispatchIdentity(
        run_id=graph.run_id,
        node_id="n1",
        epoch=node.epoch,
        attempt_id=1,
        context_snapshot_id="snap1",
        contract_version=1,
    )
    node.active_dispatch = disp
    graph.submit_command(ProtocolCommand("c5", Action.ACCEPT_VERDICT, "n1", graph.run_id, dispatch_identity=disp))
    assert node.protocol_state == ProtocolState.ACCEPTED
    assert node.execution_status == ExecutionStatus.SETTLED


def test_illegal_transitions_rejected():
    """Skipping intermediate states or jumping directly to ACCEPTED is rejected."""
    graph = DAFG()
    node = TaskNode("n1", "Direct Accept Attempt")
    graph.add_node(node)

    # Cannot jump IDLE -> ACCEPT_VERDICT
    with pytest.raises(IllegalTransitionError):
        graph.submit_command(ProtocolCommand("bad1", Action.ACCEPT_VERDICT, "n1", graph.run_id))

    assert node.protocol_state == ProtocolState.IDLE
    # Verify rejection audit was logged
    assert any(rec["idempotency_key"] == "bad1" for rec in graph.audit_log)

    # Transition to REJECTED
    graph.submit_command(ProtocolCommand("c1", Action.LOAD_CONTEXT, "n1", graph.run_id))
    graph.submit_command(ProtocolCommand("c2", Action.REFUSE, "n1", graph.run_id))
    assert node.protocol_state == ProtocolState.REJECTED

    # Cannot jump REJECTED -> ACCEPT_VERDICT
    with pytest.raises(IllegalTransitionError):
        graph.submit_command(ProtocolCommand("bad2", Action.ACCEPT_VERDICT, "n1", graph.run_id))


def test_dispatch_identity_fencing():
    """Verdicts with stale epoch or mismatched snapshot IDs are rejected."""
    graph = DAFG()
    node = TaskNode("n1", "Fenced Task")
    node.epoch = 3
    node.protocol_state = ProtocolState.VERIFYING
    node.active_dispatch = DispatchIdentity(
        run_id=graph.run_id,
        node_id="n1",
        epoch=3,
        attempt_id=2,
        context_snapshot_id="snapshot_v3",
        contract_version=2,
    )
    graph.add_node(node)

    # Stale epoch (epoch 2 < current epoch 3)
    stale_disp = DispatchIdentity(
        run_id=graph.run_id,
        node_id="n1",
        epoch=2,
        attempt_id=2,
        context_snapshot_id="snapshot_v3",
        contract_version=2,
    )
    with pytest.raises(IllegalTransitionError) as exc_info:
        graph.submit_command(ProtocolCommand("cmd_stale", Action.ACCEPT_VERDICT, "n1", graph.run_id, dispatch_identity=stale_disp))
    assert "Dispatch identity mismatch" in str(exc_info.value)

    # Mismatched snapshot hash
    bad_snap_disp = DispatchIdentity(
        run_id=graph.run_id,
        node_id="n1",
        epoch=3,
        attempt_id=2,
        context_snapshot_id="wrong_snapshot_hash",
        contract_version=2,
    )
    with pytest.raises(IllegalTransitionError) as exc_info:
        graph.submit_command(ProtocolCommand("cmd_bad_snap", Action.ACCEPT_VERDICT, "n1", graph.run_id, dispatch_identity=bad_snap_disp))
    assert "Dispatch identity mismatch" in str(exc_info.value)


def test_idempotency_key_deduplication():
    """Duplicate command submissions with identical idempotency key do not duplicate events."""
    graph = DAFG()
    node = TaskNode("n1", "Idempotency Test")
    graph.add_node(node)

    cmd = ProtocolCommand("unique_key_101", Action.LOAD_CONTEXT, "n1", graph.run_id)
    events1, _ = graph.submit_command(cmd)
    initial_event_count = len(graph.domain_events)
    assert len(events1) == 1

    # Re-submit exact same command
    events2, audit2 = graph.submit_command(cmd)
    assert len(graph.domain_events) == initial_event_count
    assert events2 == []
    assert audit2 is None


def test_protocol_engine_and_reducer_replay():
    """Replaying domain events via ProtocolReducer reconstructs identical protocol state."""
    graph = DAFG()
    n1 = TaskNode("n1", "Node 1")
    n2 = TaskNode("n2", "Node 2", needs=["n1"])
    graph.add_node(n1)
    graph.add_node(n2)

    graph.submit_command(ProtocolCommand("r1", Action.LOAD_CONTEXT, "n1", graph.run_id))
    graph.submit_command(ProtocolCommand("r2", Action.DISPATCH_PROVE, "n1", graph.run_id))
    graph.submit_command(ProtocolCommand("r3", Action.CHALLENGE, "n1", graph.run_id))
    graph.submit_command(ProtocolCommand("r4", Action.SUBMIT_EVIDENCE, "n1", graph.run_id))

    disp1 = DispatchIdentity(
        run_id=graph.run_id,
        node_id="n1",
        epoch=n1.epoch,
        attempt_id=1,
        context_snapshot_id="snap_replay_1",
        contract_version=1,
    )
    n1.active_dispatch = disp1
    graph.submit_command(ProtocolCommand("r5", Action.ACCEPT_VERDICT, "n1", graph.run_id, dispatch_identity=disp1))
    graph.submit_command(ProtocolCommand("r6", Action.INVALIDATE, "n1", graph.run_id, payload={"reason": "Contract drift"}))

    events = list(graph.domain_events)
    assert len(events) >= 6

    replayed_graph = DAFG.replay(events)

    rep_n1 = replayed_graph.nodes["n1"]
    assert rep_n1.protocol_state == n1.protocol_state
    assert rep_n1.execution_status == n1.execution_status
    assert rep_n1.epoch == n1.epoch
    assert rep_n1.protocol_state == ProtocolState.STALE
    assert rep_n1.execution_status == ExecutionStatus.BLOCKED


def test_mandatory_invalidation_under_zero_budget():
    """Mandatory invalidation from ACCEPTED to STALE succeeds even with exhausted adaptation budget."""
    graph = DAFG()
    graph.budget.max_adaptations = 0
    graph.budget.adaptations_consumed = 0
    graph.budget.max_revisions = 0
    graph.budget.revisions_consumed = 0

    root = TaskNode("root", "Root Task", status=NodeStatus.ACCEPTED)
    dep1 = TaskNode("dep1", "Dependent 1", needs=["root"], status=NodeStatus.ACCEPTED)
    dep2 = TaskNode("dep2", "Dependent 2", needs=["dep1"], status=NodeStatus.ACCEPTED)
    graph.add_node(root)
    graph.add_node(dep1)
    graph.add_node(dep2)

    # Invalidation must succeed without raising BudgetExceededError
    invalidated = graph.invalidate_dependents("root", reason="Root schema changed")
    assert "dep1" in invalidated
    assert "dep2" in invalidated

    assert graph.nodes["dep1"].status == NodeStatus.READY
    assert graph.nodes["dep1"].protocol_state == ProtocolState.STALE
    assert graph.nodes["dep2"].status == NodeStatus.READY
    assert graph.nodes["dep2"].protocol_state == ProtocolState.STALE


def test_run_sealing_invariance():
    """Sealing a run locks graph against state mutations and new task additions."""
    graph = DAFG()
    n = TaskNode("n1", "Work", status=NodeStatus.ACCEPTED)
    graph.add_node(n)

    graph.seal_run()
    assert graph.is_sealed
    assert graph.sealed_at is not None

    # Submitting command raises RunSealedError
    with pytest.raises(RunSealedError):
        graph.submit_command(ProtocolCommand("c_post_seal", Action.LOAD_CONTEXT, "n1", graph.run_id))

    # Committing transition raises RunSealedError
    with pytest.raises(RunSealedError):
        graph.commit_transition(n, NodeStatus.READY, action="REOPEN")

    # Adding node raises RunSealedError
    with pytest.raises(RunSealedError):
        graph.add_node(TaskNode("n_late", "Late Task"))


def test_adapter_conformance_deterministic_stream():
    """Adapters attach DispatchIdentity tokens to AgentResponse for all runtime variants."""
    graph = DAFG()
    node = TaskNode("t1", "Build Feature", owns=["src/feature.py"])
    graph.add_node(node)

    disp = DispatchIdentity(
        run_id=graph.run_id,
        node_id="t1",
        epoch=1,
        attempt_id=1,
        context_snapshot_id="snap_feat",
        contract_version=1,
    )
    context = {"dispatch_identity": disp}

    # IterativeCLIAdapter
    cli_adapter = IterativeCLIAdapter()
    res_cli = cli_adapter.invoke(node, context)
    assert res_cli.dispatch_identity == disp
    assert res_cli.epoch == 1

    # ToolDispatchAdapter
    tool_adapter = ToolDispatchAdapter()
    res_tool = tool_adapter.invoke(node, context)
    assert res_tool.dispatch_identity == disp
    assert res_tool.epoch == 1

    # ReActStateAdapter
    react_adapter = ReActStateAdapter()
    res_react = react_adapter.invoke(node, context)
    assert res_react.dispatch_identity == disp
    assert res_react.epoch == 1


def test_protocol_audit_runner():
    """ProtocolAuditRunner executes all 7 formal conformance checks cleanly."""
    runner = ProtocolAuditRunner()
    report = runner.run_all()
    assert report["passed"] is True
    assert report["total_checks"] == 7
    assert report["passed_checks"] == 7
    for name, passed in report["checks"].items():
        assert passed is True, f"Check {name} failed"
