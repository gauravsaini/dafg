"""Tests for DAFG v0.2 Dependency Correctness & Manifest Dispatch Gating."""

import pytest
from dafg import (
    DAFG,
    AgentResponse,
    FailureClass,
    InputManifest,
    InterfaceContract,
    NodeStatus,
    OutcomeStatus,
    RevisionDirective,
    TaskNode,
)


def test_pre_dispatch_manifest_missing_context_blocks_worker():
    """Worker must NOT execute if declared mandatory inputs are missing or unaccepted."""
    graph = DAFG()
    worker_invoked = False

    def executor(node, context):
        nonlocal worker_invoked
        worker_invoked = True
        return AgentResponse(output="Should not run")

    node = TaskNode(
        id="worker_task",
        title="Process Schema",
        manifest=InputManifest(
            required_inputs=[
                {"artifact": "organization_schema", "version": 2, "mandatory": True}
            ]
        ),
    )
    graph.add_node(node)

    # Execute
    res = graph.execute_node(node, executor_fn=executor)
    assert res is False
    assert worker_invoked is False
    assert node.status == NodeStatus.BLOCKED
    assert "organization_schema" in graph.nodes  # Auto-spawned prerequisite


def test_pre_dispatch_manifest_stale_prerequisite_blocked():
    """Worker is blocked if prerequisite node is accepted but at an obsolete version."""
    graph = DAFG()
    worker_invoked = False

    def executor(node, context):
        nonlocal worker_invoked
        worker_invoked = True
        return AgentResponse(output="Running")

    # Upstream node is at version 1
    upstream = TaskNode(id="schema_gen", title="Generate Schema", version=1, status=NodeStatus.ACCEPTED)
    graph.add_node(upstream)

    # Downstream requires version 2
    downstream = TaskNode(
        id="api_builder",
        title="Build API",
        needs=["schema_gen"],
        manifest=InputManifest(
            required_inputs=[
                {"artifact": "schema_gen", "version": 2, "mandatory": True}
            ]
        ),
    )
    graph.add_node(downstream)

    res = graph.execute_node(downstream, executor_fn=executor)
    assert res is False
    assert worker_invoked is False
    assert downstream.status == NodeStatus.BLOCKED


def test_pre_dispatch_manifest_satisfied():
    """Worker proceeds when manifest inputs are accepted with current versions."""
    graph = DAFG()
    worker_invoked = False

    def executor(node, context):
        nonlocal worker_invoked
        worker_invoked = True
        return AgentResponse(output="Success", status="COMPLETED")

    upstream = TaskNode(id="schema_gen", title="Generate Schema", version=2, status=NodeStatus.ACCEPTED)
    graph.add_node(upstream)

    downstream = TaskNode(
        id="api_builder",
        title="Build API",
        needs=["schema_gen"],
        manifest=InputManifest(
            required_inputs=[
                {"artifact": "schema_gen", "version": 2, "mandatory": True}
            ]
        ),
    )
    graph.add_node(downstream)

    res = graph.execute_node(downstream, executor_fn=executor)
    assert res is True
    assert worker_invoked is True
    assert downstream.status == NodeStatus.ACCEPTED


def test_versioned_interface_contracts_backward_compatible():
    """Backward-compatible contract updates do not invalidate downstream consumers."""
    graph = DAFG()

    # 1. Register v1 contract
    c1 = InterfaceContract(
        contract_id="auth_contract",
        version=1,
        owner="node_auth",
        compatibility_mode="backward_compatible",
    )
    graph.register_contract(c1)

    # 2. Add consumer node
    consumer = TaskNode(
        id="node_client",
        title="Client implementation",
        consumed_contracts={"auth_contract": 1},
        status=NodeStatus.ACCEPTED,
    )
    graph.add_node(consumer)

    # 3. Update to v2 with backward compatibility
    c2 = InterfaceContract(
        contract_id="auth_contract",
        version=2,
        owner="node_auth",
        compatibility_mode="backward_compatible",
    )
    compatible = graph.register_contract(c2)
    assert compatible is True
    assert consumer.status == NodeStatus.ACCEPTED  # Not invalidated!


def test_versioned_interface_contracts_breaking_invalidates_consumers():
    """Breaking contract updates trigger targeted invalidation of consumers only."""
    graph = DAFG()

    c1 = InterfaceContract(
        contract_id="auth_contract",
        version=1,
        owner="node_auth",
    )
    graph.register_contract(c1)

    consumer = TaskNode(
        id="node_client",
        title="Client implementation",
        consumed_contracts={"auth_contract": 1},
        status=NodeStatus.ACCEPTED,
    )
    graph.add_node(consumer)

    unrelated = TaskNode(
        id="node_docs",
        title="Write Docs",
        status=NodeStatus.ACCEPTED,
    )
    graph.add_node(unrelated)

    # Breaking update
    c2 = InterfaceContract(
        contract_id="auth_contract",
        version=2,
        owner="node_auth",
        compatibility_mode="breaking",
    )
    compatible = graph.register_contract(c2)
    assert compatible is False
    assert consumer.status == NodeStatus.READY  # Invalidated for recomputation!
    assert consumer.epoch == 2
    assert unrelated.status == NodeStatus.ACCEPTED  # Unrelated node preserved!


def test_failure_directed_repair_stale_dependency():
    """Revision directive with STALE_DEPENDENCY invalidates only affected descendants."""
    graph = DAFG()

    upstream = TaskNode(id="n_core", title="Core Module", status=NodeStatus.ACCEPTED)
    mid = TaskNode(id="n_service", title="Service Layer", needs=["n_core"], status=NodeStatus.ACCEPTED)
    leaf = TaskNode(id="n_ui", title="UI View", needs=["n_service"], status=NodeStatus.ACCEPTED)
    independent = TaskNode(id="n_db", title="Database", status=NodeStatus.ACCEPTED)

    graph.add_node(upstream)
    graph.add_node(mid)
    graph.add_node(leaf)
    graph.add_node(independent)

    directive = RevisionDirective(
        verdict="REVISE",
        failure_class=FailureClass.STALE_DEPENDENCY,
        affected_dependency="n_core",
        required_version=2,
        feedback="Schema changed in core",
    )

    graph.apply_revision_directive(leaf, directive)

    assert leaf.status == NodeStatus.REJECTED
    assert mid.status == NodeStatus.READY  # Downstream from n_core
    assert independent.status == NodeStatus.ACCEPTED  # Independent node untouched


def test_priority_scored_wave_scheduling():
    """Ready nodes on critical path or owning contracts are scheduled into earlier waves."""
    graph = DAFG()

    # Low priority independent leaf
    leaf = TaskNode(id="leaf_doc", title="Docs", depth=0)
    # High priority contract owner with downstream dependents
    owner = TaskNode(id="core_contract_owner", title="Core Model", depth=2)

    graph.add_node(leaf)
    graph.add_node(owner)

    contract = InterfaceContract(contract_id="core_data", version=1, owner="core_contract_owner")
    graph.register_contract(contract)

    # Add dependent
    dep = TaskNode(id="service", title="Service", needs=["core_contract_owner"])
    graph.add_node(dep)

    ready = [leaf, owner]
    waves = graph.compute_waves(ready)

    # The contract owner with downstream dependents must be ordered first
    assert waves[0][0].id == "core_contract_owner"
