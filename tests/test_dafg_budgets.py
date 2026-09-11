"""Tests for DAFG budget caps enforcement."""

import time
import pytest
from dafg.runtime import DAFG, Budget, BudgetExceededError, NodeStatus, TaskNode, AgentResponse


def test_call_budget_enforcement():
    budget = Budget(max_calls=2)
    graph = DAFG(budget=budget)
    graph.add_node(TaskNode("n1", "Node 1"))
    graph.add_node(TaskNode("n2", "Node 2", needs=["n1"]))
    graph.add_node(TaskNode("n3", "Node 3", needs=["n2"]))

    # Step 1: executes n1, consumes 1 call
    executed1 = graph.step()
    assert len(executed1) == 1
    assert budget.calls_consumed == 1

    # Step 2: executes n2, consumes 2nd call
    executed2 = graph.step()
    assert len(executed2) == 1
    assert budget.calls_consumed == 2

    # Step 3: attempting to execute n3 should exceed budget
    with pytest.raises(BudgetExceededError, match="Model call budget exceeded"):
        graph.step()


def test_node_budget_enforcement():
    budget = Budget(max_nodes=2)
    graph = DAFG(budget=budget)

    graph.add_node(TaskNode("n1", "Node 1"))
    graph.add_node(TaskNode("n2", "Node 2"))

    with pytest.raises(BudgetExceededError, match="Node budget exceeded"):
        graph.add_node(TaskNode("n3", "Node 3"))


def test_deadline_budget_enforcement():
    # Deadline in the past
    budget = Budget(deadline=time.time() - 10.0)
    graph = DAFG(budget=budget)
    graph.add_node(TaskNode("n1", "Node 1"))

    with pytest.raises(BudgetExceededError, match="Deadline exceeded"):
        graph.step()


def test_revision_budget_enforcement():
    budget = Budget(max_revisions=2)
    budget.check_revision()
    assert budget.revisions_consumed == 1
    budget.check_revision()
    assert budget.revisions_consumed == 2

    with pytest.raises(BudgetExceededError, match="Revision budget exceeded"):
        budget.check_revision()


def test_revision_budget_exhaustion_does_not_leave_node_in_running():
    """When a node failure causes revision budget exhaustion, node must transition to FAILED/REJECTED, not stay RUNNING."""
    budget = Budget(max_revisions=0)
    graph = DAFG(budget=budget)
    n1 = TaskNode("n1", "Failing task", max_revisions=3)
    graph.add_node(n1)

    def failing_agent(node, ctx):
        return AgentResponse(status="FAILED", output="simulated error")

    with pytest.raises(BudgetExceededError, match="Revision budget exceeded"):
        graph.step(executor_fn=failing_agent)

    # Node must NOT be left in RUNNING!
    assert n1.status in (NodeStatus.REJECTED, NodeStatus.FAILED)
    assert n1.revisions == 1


def test_dafg_run_returns_budget_exceeded_on_budget_exhaustion():
    """DAFG.run() must catch BudgetExceededError cleanly and return BUDGET_EXCEEDED."""
    budget = Budget(max_calls=1)
    graph = DAFG(budget=budget)
    graph.add_node(TaskNode("n1", "First node"))
    graph.add_node(TaskNode("n2", "Second node", needs=["n1"]))

    status = graph.run()
    assert status == "BUDGET_EXCEEDED"


