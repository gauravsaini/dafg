"""Tests for DAFG task graph runtime, dynamic planning, and objective gate verification."""

import pytest
from dafg.gates import Gate, GateEngine, GateLedger
from dafg.runtime import DAFG, AgentResponse, NodeStatus, Role, TaskNode


def test_basic_node_lifecycle():
    graph = DAFG()
    node = TaskNode(
        id="t1",
        title="Initial task",
        role=Role.CODER,
    )
    graph.add_node(node)
    assert graph.nodes["t1"].status == NodeStatus.PENDING

    # Run execution
    status = graph.run()
    assert status == "COMPLETED"
    assert graph.nodes["t1"].status == NodeStatus.ACCEPTED


def test_dynamic_dependency_expansion():
    """Agent dynamically requests a new dependency task that must complete first."""
    graph = DAFG()
    node = TaskNode(id="main_task", title="Deploy app", role=Role.CODER)
    graph.add_node(node)

    call_count = 0

    def mock_agent(n: TaskNode, ctx: dict) -> AgentResponse:
        nonlocal call_count
        call_count += 1
        if n.id == "main_task" and "build_artifact" not in n.needs:
            # Dynamically request build_artifact prerequisite
            return AgentResponse(
                output="Needs artifact built first",
                needs=[
                    TaskNode(id="build_artifact", title="Build Artifact", role=Role.CODER)
                ],
            )
        return AgentResponse(output=f"Executed {n.id}")

    # Step 1: main_task discovers dependency and becomes BLOCKED
    graph.step(executor_fn=mock_agent)
    assert "build_artifact" in graph.nodes
    assert "build_artifact" in graph.nodes["main_task"].needs
    assert graph.nodes["main_task"].status == NodeStatus.BLOCKED
    assert graph.nodes["build_artifact"].status == NodeStatus.PENDING

    # Step 2: build_artifact runs and completes
    graph.step(executor_fn=mock_agent)
    assert graph.nodes["build_artifact"].status == NodeStatus.ACCEPTED
    # main_task is now ready again
    ready = graph.get_ready_nodes()
    assert any(n.id == "main_task" for n in ready)

    # Step 3: main_task runs and completes
    graph.step(executor_fn=mock_agent)
    assert graph.nodes["main_task"].status == NodeStatus.ACCEPTED
    assert graph.is_completed()


def test_objective_gate_verification_rejection():
    """Node cannot be accepted on LLM self-certification alone if assigned gate fails."""
    ledger_text = """
- [ ] G1: Database tests
  CHECK: python -c "exit(1)"
  EXPECT: ok
"""
    ledger = GateLedger.parse(ledger_text)
    engine = GateEngine(auto_approve=True)

    graph = DAFG(ledger=ledger, engine=engine)
    node = TaskNode(
        id="db_task",
        title="Setup DB",
        role=Role.CODER,
        assigned_gates=["G1"],
        max_revisions=2,
    )
    graph.add_node(node)

    def optimistic_agent(n: TaskNode, ctx: dict) -> AgentResponse:
        # Agent claims everything is great
        return AgentResponse(output="I am done, everything is 100% working!")

    # Execute once: gate fails -> node rejected, revision incremented
    graph.step(executor_fn=optimistic_agent)
    assert graph.nodes["db_task"].status == NodeStatus.REJECTED
    assert graph.nodes["db_task"].revisions == 1

    # Execute second time: gate fails again -> max_revisions reached -> FAILED
    graph.step(executor_fn=optimistic_agent)
    assert graph.nodes["db_task"].status == NodeStatus.FAILED
    assert graph.has_failed()


def test_objective_gate_verification_success():
    """Node is accepted when assigned gate executes and passes with evidence."""
    ledger_text = """
- [ ] G1: Schema migration
  CHECK: python -c "print('schema migrated successfully')"
  EXPECT: schema migrated successfully
"""
    ledger = GateLedger.parse(ledger_text)
    engine = GateEngine(auto_approve=True)

    graph = DAFG(ledger=ledger, engine=engine)
    node = TaskNode(
        id="migrate",
        title="Run migration",
        assigned_gates=["G1"],
    )
    graph.add_node(node)

    graph.run()
    assert graph.nodes["migrate"].status == NodeStatus.ACCEPTED
    assert ledger.gates["G1"].status == "MET"
    assert "exit_code=0" in ledger.gates["G1"].evidence


def test_execute_node_rejects_on_agent_failure_status():
    graph = DAFG()
    node = TaskNode("compile", "Compile code")
    graph.add_node(node)

    # Agent returns FAILED status
    failing_agent = lambda n, ctx: AgentResponse(status="FAILED", output="Syntax error in line 12")
    res = graph.execute_node(node, executor_fn=failing_agent)

    assert res is False
    assert node.status == NodeStatus.REJECTED
    assert node.revisions == 1


def test_execute_node_handles_agent_exception():
    graph = DAFG()
    node = TaskNode("crash", "Crashing task")
    graph.add_node(node)

    def crashing_agent(n, ctx):
        raise RuntimeError("LLM service unavailable")

    res = graph.execute_node(node, executor_fn=crashing_agent)
    assert res is False
    assert node.status == NodeStatus.REJECTED
    assert node.revisions == 1
    assert any("LLM service unavailable" in h["details"] for h in graph.execution_history)


def test_node_ready_status_in_get_ready_nodes():
    graph = DAFG()
    node = TaskNode("n1", "Ready task", status=NodeStatus.READY)
    graph.add_node(node)

    ready = graph.get_ready_nodes()
    assert len(ready) == 1
    assert ready[0].id == "n1"


def test_init_from_ledger():
    ledger_text = """
- [ ] G1: First gate
  CHECK: echo 1
  EXPECT: 1
  OWNS: src/foo.py

- [ ] G2: Second gate
  CHECK: echo 2
  EXPECT: 2
  OWNS: src/bar.py

- [-] G3: Abandoned gate
  ABANDON: Not needed
"""
    ledger = GateLedger.parse(ledger_text)
    graph = DAFG(ledger=ledger)
    created = graph.init_from_ledger()

    assert len(created) == 2
    assert "task_G1" in graph.nodes
    assert "task_G2" in graph.nodes
    assert "task_G3" not in graph.nodes
    assert graph.nodes["task_G1"].owns == ["src/foo.py"]
    assert graph.nodes["task_G2"].assigned_gates == ["G2"]
