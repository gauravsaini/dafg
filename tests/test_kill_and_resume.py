"""Integration tests for kill/resume resiliency, epoch fencing, and stale worker rejection."""

import json
import pytest
from pathlib import Path
from dafg.runtime import DAFG, Budget, NodeStatus, TaskNode, OutcomeStatus
from dafg.protocol import Action, DispatchIdentity, ProtocolCommand, ProtocolState, StaleDispatchError


def test_crash_recovery_bumps_run_epoch_and_attempts_leaving_revisions_unchanged(tmp_path):
    state_file = tmp_path / "state.json"
    
    # Simulate an in-flight execution at run_epoch=7
    initial_data = {
        "version": "1.0",
        "timestamp": "2026-09-14T00:00:00Z",
        "run_id": "run_initial_7",
        "run_epoch": 7,
        "outcome_status": "INCOMPLETE_RUN",
        "budget": {"max_calls": 10, "calls_consumed": 1},
        "nodes": {
            "n_worker": {
                "id": "n_worker",
                "title": "In flight task",
                "status": "RUNNING",
                "protocol_state": "VERIFYING",
                "epoch": 7,
                "attempts": 0,
                "revisions": 0,
                "active_dispatch": {
                    "run_id": "run_initial_7",
                    "node_id": "n_worker",
                    "epoch": 7,
                    "attempt_id": 1,
                    "context_snapshot_id": "snap_v7",
                    "contract_version": 1,
                },
            }
        },
        "gate_states": {},
        "execution_history": [],
    }
    state_file.write_text(json.dumps(initial_data), encoding="utf-8")

    # Orchestrator died via SIGKILL; fresh process resumes state
    resumed_graph = DAFG.load_state(state_file)

    # 1. Run epoch bumped from 7 to 8
    assert resumed_graph.run_epoch == 8

    # 2. Node reset to PENDING with attempts incremented, but revisions UNTOUCHED!
    recovered_node = resumed_graph.nodes["n_worker"]
    assert recovered_node.status == NodeStatus.PENDING
    assert recovered_node.epoch == 8
    assert recovered_node.attempts == 1
    assert recovered_node.revisions == 0
    assert recovered_node.active_dispatch is None

    # 3. Domain event recorded
    assert any(e["type"] == "RECOVERED_FROM_INTERRUPTION" for e in resumed_graph.domain_events)


def test_stale_delayed_worker_rejected_after_orchestrator_resume(tmp_path):
    state_file = tmp_path / "state.json"
    
    initial_data = {
        "version": "1.0",
        "timestamp": "2026-09-14T00:00:00Z",
        "run_id": "run_crash_test",
        "run_epoch": 1,
        "outcome_status": "INCOMPLETE_RUN",
        "budget": {"max_calls": 10, "calls_consumed": 1},
        "nodes": {
            "n1": {
                "id": "n1",
                "title": "Stale worker node",
                "status": "RUNNING",
                "protocol_state": "VERIFYING",
                "epoch": 1,
                "attempts": 0,
                "revisions": 0,
                "active_dispatch": {
                    "run_id": "run_crash_test",
                    "node_id": "n1",
                    "epoch": 1,
                    "attempt_id": 1,
                    "context_snapshot_id": "snap_v1",
                    "contract_version": 1,
                },
            }
        },
        "gate_states": {},
        "execution_history": [],
    }
    state_file.write_text(json.dumps(initial_data), encoding="utf-8")

    # Orchestrator recovers: epoch advances to 2, active_dispatch is cleared
    resumed_graph = DAFG.load_state(state_file)
    assert resumed_graph.run_epoch == 2
    assert resumed_graph.nodes["n1"].epoch == 2

    # Delayed old worker from epoch 1 attempts to submit ACCEPT_VERDICT
    stale_dispatch = DispatchIdentity(
        run_id="run_crash_test",
        node_id="n1",
        epoch=1,
        attempt_id=1,
        context_snapshot_id="snap_v1",
        contract_version=1,
    )
    cmd = ProtocolCommand(
        idempotency_key="delayed_commit_from_worker_epoch_1",
        action=Action.ACCEPT_VERDICT,
        node_id="n1",
        run_id="run_crash_test",
        dispatch_identity=stale_dispatch,
        payload={"result": {"success": True}},
    )

    with pytest.raises(StaleDispatchError) as exc_info:
        resumed_graph.submit_command(cmd)

    assert "Stale dispatch identity" in str(exc_info.value)
