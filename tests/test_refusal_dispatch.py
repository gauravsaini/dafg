"""Tests for DAFG 5-Class Refusal Dispatch and Pre-Dispatch Gating Engine."""

import pytest
from dafg.runtime import DAFG, TaskNode, NodeStatus, RefusalClass, InterfaceContract, InputManifest
from dafg.adapters import IterativeCLIAdapter, ToolDispatchAdapter, ReActStateAdapter


def test_refusal_missing_authorization():
    """Verify task requiring elevated permissions halts pre-dispatch with MISSING_AUTHORIZATION."""
    graph = DAFG()
    node = TaskNode(
        id="t_perm",
        title="Flush system iptables rules",
        requires_permissions=True,
    )
    graph.add_node(node)

    executed = False
    def dummy_exec(n, ctx):
        nonlocal executed
        executed = True
        return None

    status = graph.run(executor_fn=dummy_exec)
    assert status == "BLOCKED"
    assert executed is False
    assert node.status == NodeStatus.BLOCKED
    assert node.refusal_class == RefusalClass.MISSING_AUTHORIZATION
    assert "elevated permissions" in str(node.refusal_reason).lower()


def test_refusal_contradictory_requirements():
    """Verify task with contradictory contract invariants halts pre-dispatch."""
    graph = DAFG()
    contract = InterfaceContract(
        contract_id="c_paradox",
        invariants=["status == 'ACTIVE'", "not status == 'ACTIVE'"],
    )
    graph.register_contract(contract)

    node = TaskNode(
        id="t_contra",
        title="Reconcile state",
        consumed_contracts={"c_paradox": 1},
    )
    graph.add_node(node)

    status = graph.run()
    assert status == "BLOCKED"
    assert node.status == NodeStatus.BLOCKED
    assert node.refusal_class == RefusalClass.CONTRADICTORY_REQUIREMENTS


def test_refusal_unavailable_capability():
    """Verify provably impossible or uncomputable tasks halt with UNAVAILABLE_CAPABILITY."""
    graph = DAFG()
    node = TaskNode(
        id="t_halt",
        title="Unsolvable Halting Task for arbitrary Turing machine",
    )
    graph.add_node(node)

    status = graph.run()
    assert status == "BLOCKED"
    assert node.status == NodeStatus.BLOCKED
    assert node.refusal_class == RefusalClass.UNAVAILABLE_CAPABILITY


def test_refusal_missing_prerequisite():
    """Verify missing inputs halt with MISSING_PREREQUISITE and spawn dependency stubs."""
    graph = DAFG()
    manifest = InputManifest(required_inputs=[{"artifact": "config_spec", "mandatory": True}])
    node = TaskNode(
        id="t_consumer",
        title="Consume config spec",
        manifest=manifest,
    )
    graph.add_node(node)

    res = graph.execute_node(node)
    assert res is False
    assert node.status == NodeStatus.BLOCKED
    assert node.refusal_class == RefusalClass.MISSING_PREREQUISITE
    # Verifies requirement was spawned
    assert "config_spec" in graph.nodes


def test_adapter_honest_refusal():
    """Verify decoupled runtime adapters honestly refuse unauthorized and impossible directives."""
    perm_node = TaskNode(id="p1", title="Restricted action", requires_permissions=True)
    imp_node = TaskNode(id="i1", title="Solve halting problem for universal interpreter")

    for adapter in [IterativeCLIAdapter(), ToolDispatchAdapter(), ReActStateAdapter()]:
        resp_perm = adapter.invoke(perm_node, {})
        assert resp_perm.status == "BLOCKED"
        assert resp_perm.metadata.get("refusal_class") == "MISSING_AUTHORIZATION"

        resp_imp = adapter.invoke(imp_node, {})
        assert resp_imp.status == "BLOCKED"
        assert resp_imp.metadata.get("refusal_class") == "UNAVAILABLE_CAPABILITY"


def test_token_overhead_optimization():
    """Verify ToolDispatch uses role-scoped schemas and ReAct maintains compact history."""
    dispatch = ToolDispatchAdapter()
    coder_node = TaskNode(id="c1", title="Refactor parser", role="coder", owns=["src/parser.py"])
    planner_node = TaskNode(id="p1", title="Architect flow", role="planner")

    dispatch.invoke(coder_node, {})
    tokens_coder = dispatch.total_tokens_consumed
    dispatch.invoke(planner_node, {})
    tokens_planner = dispatch.total_tokens_consumed - tokens_coder
    # Planner has fewer scoped tools than coder
    assert tokens_planner < tokens_coder

    react = ReActStateAdapter(max_turns=5)
    react.invoke(coder_node, {})
    # Verify scratchpad history was compacted to rolling active window
    assert len(react.state_trace) <= 2
