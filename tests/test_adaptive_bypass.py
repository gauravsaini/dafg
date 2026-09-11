"""Tests for DAFG v0.3 Adaptive Protocol Bypass & Safety Guards."""

import pytest
from dafg import (
    DAFG,
    AgentResponse,
    BypassPolicy,
    BypassTelemetry,
    InterfaceContract,
    NodeStatus,
    Role,
    TaskNode,
)


def test_bypass_eligibility_conservative_guards():
    """Verify conservative guard conditions for protocol bypass eligibility."""
    graph = DAFG()

    # 1. Eligible single-file bug fix
    eligible_node = TaskNode(
        id="t_leaf",
        title="Fix typo in config",
        role="coder",
        owns=["src/config.py"],
        ambiguity_score=0.05,
    )
    assert graph.is_eligible_for_bypass(eligible_node) is True

    # 2. Ineligible: multiple files declared
    multi_file_node = TaskNode(
        id="t_multi",
        title="Refactor models",
        owns=["src/a.py", "src/b.py"],
    )
    assert graph.is_eligible_for_bypass(multi_file_node) is False

    # 3. Ineligible: touches shared interface contract
    contract = InterfaceContract(contract_id="auth", owner="t_auth")
    graph.register_contract(contract)

    contract_node = TaskNode(
        id="t_auth",
        title="Auth module",
        owns=["src/auth.py"],
    )
    assert graph.is_eligible_for_bypass(contract_node) is False

    # 4. Ineligible: requires security permissions
    perm_node = TaskNode(
        id="t_perm",
        title="Run network command",
        owns=["src/net.py"],
        requires_permissions=True,
    )
    assert graph.is_eligible_for_bypass(perm_node) is False

    # 5. Ineligible: high ambiguity score
    ambig_node = TaskNode(
        id="t_ambig",
        title="Unclear requirement",
        owns=["src/unclear.py"],
        ambiguity_score=0.45,
    )
    assert graph.is_eligible_for_bypass(ambig_node) is False


def test_bypass_execution_successful():
    """Verify fastpath completes and records telemetry for eligible node."""
    graph = DAFG()
    node = TaskNode(
        id="t_quick",
        title="Quick fix",
        owns=["src/fix.py"],
        ambiguity_score=0.05,
    )
    graph.add_node(node)

    def mock_executor(n, ctx):
        assert ctx.get("fastpath") is True
        return AgentResponse(output="Fixed", status="COMPLETED", files_modified=["src/fix.py"])

    res = graph.execute_node_fastpath(node, executor_fn=mock_executor)
    assert res is True
    assert node.status == NodeStatus.ACCEPTED
    assert graph.bypass_telemetry.total_runs == 1
    assert graph.bypass_telemetry.bypassed_runs == 1
    assert graph.bypass_telemetry.misrouted_runs == 0
    assert graph.bypass_telemetry.bypass_rate == 1.0


def test_bypass_aborts_and_escalates_on_scope_violation():
    """Post-execution diff check aborts fastpath if worker touched multiple files."""
    graph = DAFG()
    node = TaskNode(
        id="t_greedy",
        title="Single file task",
        owns=["src/one.py"],
        ambiguity_score=0.05,
    )
    graph.add_node(node)

    invocations = []

    def rogue_executor(n, ctx):
        invocations.append(ctx.get("fastpath", False))
        if ctx.get("fastpath"):
            # Rogue worker touched 2 files instead of 1!
            return AgentResponse(
                output="Touched too many files",
                status="COMPLETED",
                files_modified=["src/one.py", "src/two.py"],
            )
        # Full protocol invocation
        return AgentResponse(
            output="Full protocol completed",
            status="COMPLETED",
            files_modified=["src/one.py"],
        )

    res = graph.execute_node_fastpath(node, executor_fn=rogue_executor)
    assert res is True
    # Fastpath aborted and escalated to full execute_node!
    assert invocations == [True, False]
    assert graph.bypass_telemetry.misrouted_runs == 1
    assert graph.bypass_telemetry.bypass_misroute_rate == 1.0


def test_bypass_aborts_and_escalates_on_contract_violation():
    """Post-execution diff check aborts fastpath if worker modified contract invariant files."""
    graph = DAFG()
    contract = InterfaceContract(contract_id="c1", invariants=["src/protected.py"])
    graph.register_contract(contract)

    node = TaskNode(
        id="t_trespass",
        title="Unsuspecting task",
        owns=["src/one.py"],
        ambiguity_score=0.05,
    )
    graph.add_node(node)

    def contract_violator(n, ctx):
        if ctx.get("fastpath"):
            return AgentResponse(
                output="Violated contract file",
                status="COMPLETED",
                files_modified=["src/protected.py"],
            )
        return AgentResponse(output="Full protocol safe", status="COMPLETED")

    res = graph.execute_node_fastpath(node, executor_fn=contract_violator)
    assert res is True
    assert graph.bypass_telemetry.misrouted_runs == 1


def test_bypass_shadow_audit_telemetry():
    """Verify shadow execution audits fastpath runs."""
    graph = DAFG()
    # Force 100% shadow sampling for test
    graph.bypass_policy.shadow_sample_rate = 1.0

    for i in range(10):
        node = TaskNode(id=f"t_{i}", title=f"Task {i}", owns=[f"src/{i}.py"])
        graph.add_node(node)
        graph.execute_node_fastpath(node)

    assert graph.bypass_telemetry.bypassed_runs == 10
    assert graph.bypass_telemetry.shadow_runs >= 1
