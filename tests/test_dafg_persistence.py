"""Tests for atomic state persistence and clean resumption."""

import json
from pathlib import Path
import pytest
from dafg.runtime import DAFG, Budget, NodeStatus, TaskNode, AgentResponse


def test_atomic_persistence_and_resumption(tmp_path):
    state_file = tmp_path / "state.json"

    budget = Budget(max_calls=10, max_nodes=5)
    graph = DAFG(budget=budget, state_path=state_file)

    n1 = TaskNode("n1", "First node")
    n2 = TaskNode("n2", "Second node", needs=["n1"])
    graph.add_node(n1)
    graph.add_node(n2)

    # Step 1: Execute n1 only
    graph.step()
    assert graph.nodes["n1"].status == NodeStatus.ACCEPTED
    assert graph.nodes["n2"].status == NodeStatus.PENDING
    assert graph.budget.calls_consumed == 1

    # Verify state.json exists and is valid JSON
    assert state_file.exists()
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved_data["nodes"]["n1"]["status"] == "ACCEPTED"
    assert saved_data["nodes"]["n2"]["status"] == "PENDING"
    assert saved_data["budget"]["calls_consumed"] == 1
    assert len(saved_data["execution_history"]) > 0

    # Resume graph in a fresh instance from state_file
    resumed = DAFG.load_state(state_file)
    assert resumed.nodes["n1"].status == NodeStatus.ACCEPTED
    assert resumed.nodes["n2"].status == NodeStatus.PENDING
    assert resumed.budget.calls_consumed == 1
    assert len(resumed.execution_history) == len(saved_data["execution_history"])

    # Resume execution: only n2 should run
    executed = resumed.step()
    assert len(executed) == 1
    assert executed[0].id == "n2"
    assert resumed.nodes["n2"].status == NodeStatus.ACCEPTED
    assert resumed.budget.calls_consumed == 2
    assert resumed.is_completed()


def test_gate_states_persistence_and_resumption(tmp_path):
    from dafg.gates import GateLedger, GateEngine
    state_file = tmp_path / "state.json"
    ledger_file = tmp_path / "GATES.md"
    ledger_text = """
- [ ] G1: First check
  CHECK: python -c "print('ok1')"
  EXPECT: ok1

- [ ] G2: Second check
  CHECK: python -c "print('ok2')"
  EXPECT: ok2
"""
    ledger_file.write_text(ledger_text, encoding="utf-8")
    ledger = GateLedger.load(ledger_file)
    engine = GateEngine(auto_approve=True)

    graph = DAFG(ledger=ledger, engine=engine, state_path=state_file)
    n1 = TaskNode("n1", "Work 1", assigned_gates=["G1"])
    graph.add_node(n1)
    graph.step()

    assert graph.nodes["n1"].status == NodeStatus.ACCEPTED
    assert ledger.gates["G1"].status == "MET"
    assert ledger.gates["G2"].status == "UNMET"

    # Check that state.json persisted gate_states
    saved_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "gate_states" in saved_data
    assert saved_data["gate_states"]["G1"]["status"] == "MET"
    assert "exit_code=0" in saved_data["gate_states"]["G1"]["evidence"]
    assert saved_data["gate_states"]["G2"]["status"] == "UNMET"

    # Reload fresh instance and verify gate_states are restored
    fresh_ledger = GateLedger.parse(ledger_text)  # initial unmet state
    assert fresh_ledger.gates["G1"].status == "UNMET"

    resumed = DAFG.load_state(state_file, ledger=fresh_ledger, engine=engine)
    assert resumed.gate_states["G1"]["status"] == "MET"
    assert fresh_ledger.gates["G1"].status == "MET"
    assert "exit_code=0" in fresh_ledger.gates["G1"].evidence


def test_resumption_recovers_interrupted_running_nodes(tmp_path):
    """Interrupted runs with nodes stuck in RUNNING must be reset to PENDING upon load."""
    state_file = tmp_path / "state.json"
    data = {
        "version": "1.0",
        "timestamp": "2026-09-10T12:00:00Z",
        "budget": {"max_calls": 10, "calls_consumed": 2},
        "nodes": {
            "in_flight": {
                "id": "in_flight",
                "title": "In flight task",
                "status": "RUNNING",
                "role": "coder",
                "needs": [],
                "assigned_gates": [],
                "owns": [],
                "parent_id": None,
                "children": [],
                "depth": 0,
                "revisions": 0,
                "max_revisions": 3,
                "result": None,
                "metadata": {},
            }
        },
        "gate_states": {},
        "execution_history": [],
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    resumed = DAFG.load_state(state_file)
    assert resumed.nodes["in_flight"].status == NodeStatus.PENDING

    ready = resumed.get_ready_nodes()
    assert len(ready) == 1
    assert ready[0].id == "in_flight"


def test_state_file_preserves_history_and_gate_states_on_disk_across_loads(tmp_path):
    """load_state must NOT wipe execution_history or gate_states on disk."""
    state_file = tmp_path / "state.json"
    data = {
        "version": "1.0",
        "timestamp": "2026-09-10T12:00:00Z",
        "budget": {"max_calls": 10, "calls_consumed": 1, "max_nodes": 5, "nodes_created": 1},
        "nodes": {
            "n1": {
                "id": "n1",
                "title": "Task 1",
                "status": "ACCEPTED",
                "role": "coder",
                "needs": [],
                "assigned_gates": ["G1"],
                "owns": [],
                "parent_id": None,
                "children": [],
                "depth": 0,
                "revisions": 0,
                "max_revisions": 3,
                "result": None,
                "metadata": {},
            }
        },
        "gate_states": {
            "G1": {"status": "MET", "evidence": "exit_code=0 timestamp=now match='1'", "abandon_reason": None}
        },
        "execution_history": [
            {"timestamp": "2026-09-10T12:00:00Z", "node_id": "n1", "action": "ACCEPTED", "details": "passed", "revisions": 0}
        ],
    }
    state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Load state
    resumed = DAFG.load_state(state_file)
    assert len(resumed.execution_history) == 1
    assert len(resumed.gate_states) == 1

    # CRITICAL: Inspect the state file ON DISK immediately after load_state
    on_disk = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(on_disk["execution_history"]) == 1
    assert on_disk["execution_history"][0]["node_id"] == "n1"
    assert len(on_disk["gate_states"]) == 1
    assert on_disk["gate_states"]["G1"]["status"] == "MET"


