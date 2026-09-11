"""Tests for Depth Tree decomposition, disjoint file ownership, waves, and child reverification."""

import pytest
from dafg.gates import Gate, GateEngine, GateLedger
from dafg.runtime import (
    DAFG,
    AgentResponse,
    NodeStatus,
    Role,
    TaskNode,
    nodes_conflict,
    paths_overlap,
)


def test_paths_overlap():
    assert paths_overlap("src/auth.py", "src/auth.py")
    assert paths_overlap("./src/auth.py", "src/auth.py")
    assert paths_overlap("src/*.py", "src/auth.py")
    assert paths_overlap("src/models/", "src/models/user.py")
    assert not paths_overlap("src/auth.py", "src/db.py")
    assert not paths_overlap("src/api/*.py", "tests/*.py")
    # Disjoint nested paths with shared names in different subtrees must NOT conflict
    assert not paths_overlap("doc", "api/doc/index.html")
    assert not paths_overlap("test", "src/test/utils.py")
    assert not paths_overlap("src/app", "src/app_old")
    assert paths_overlap(".", "src/main.py")



def test_waves_separation_on_conflicting_ownership():
    graph = DAFG()
    n1 = TaskNode("n1", "Edit auth", owns=["src/auth.py"])
    n2 = TaskNode("n2", "Also edit auth", owns=["src/auth.py"])
    n3 = TaskNode("n3", "Edit docs", owns=["docs/readme.md"])

    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)

    ready = graph.get_ready_nodes()
    assert len(ready) == 3

    waves = graph.compute_waves(ready)
    # n1 and n3 can run together, but n2 conflicts with n1 and must be in wave 2
    assert len(waves) == 2
    wave1_ids = {n.id for n in waves[0]}
    wave2_ids = {n.id for n in waves[1]}

    assert "n1" in wave1_ids
    assert "n3" in wave1_ids
    assert "n2" in wave2_ids


def test_depth_tree_decomposition_and_parent_blocking():
    graph = DAFG()
    parent = TaskNode("parent", "Feature build", role=Role.PLANNER)
    graph.add_node(parent)

    def planner_agent(n: TaskNode, ctx: dict) -> AgentResponse:
        if n.id == "parent" and not n.children:
            return AgentResponse(
                output="Decomposed into 2 subtasks",
                spawn_children=[
                    TaskNode("child1", "Subtask 1", role=Role.CODER, owns=["src/sub1.py"]),
                    TaskNode("child2", "Subtask 2", role=Role.CODER, owns=["src/sub2.py"]),
                ],
            )
        return AgentResponse(output="Parent finalize")

    # Step 1: Parent decomposes
    graph.step(executor_fn=planner_agent)
    assert graph.nodes["parent"].status == NodeStatus.BLOCKED
    assert len(graph.nodes["parent"].children) == 2
    assert graph.nodes["child1"].depth == 1
    assert graph.nodes["child1"].parent_id == "parent"
    assert graph.nodes["child2"].depth == 1


def test_depth_tree_parent_not_ready_while_children_pending():
    """Parent must NOT be marked ready while child nodes are still executing/pending."""
    graph = DAFG()
    parent = TaskNode("parent", "Parent task", role=Role.PLANNER)
    c1 = TaskNode("c1", "Child 1", parent_id="parent")
    c2 = TaskNode("c2", "Child 2", parent_id="parent")
    graph.add_node(parent)
    graph.add_node(c1)
    graph.add_node(c2)

    parent.status = NodeStatus.BLOCKED

    # When children are pending, parent must NOT be ready
    ready_ids = [n.id for n in graph.get_ready_nodes()]
    assert "parent" not in ready_ids
    assert "c1" in ready_ids
    assert "c2" in ready_ids

    # Accept c1, parent should still NOT be ready
    c1.status = NodeStatus.ACCEPTED
    ready_ids = [n.id for n in graph.get_ready_nodes()]
    assert "parent" not in ready_ids
    assert "c2" in ready_ids

    # Accept c2, parent should now become ready
    c2.status = NodeStatus.ACCEPTED
    ready_ids = [n.id for n in graph.get_ready_nodes()]
    assert "parent" in ready_ids



def test_child_gate_reverification_before_parent_completion(tmp_path):
    """Parent requires child gate reverification before it can complete."""
    # Child check tests if child_flag.txt exists
    flag_file = tmp_path / "child_flag.txt"
    flag_file.write_text("ok", encoding="utf-8")

    ledger_text = f"""
- [ ] G_child: Child gate
  CHECK: python -c "import os; exit(0 if os.path.exists(r'{flag_file}') else 1)"
  EXPECT: .*
"""
    ledger = GateLedger.parse(ledger_text)
    engine = GateEngine(auto_approve=True)

    graph = DAFG(ledger=ledger, engine=engine)
    parent = TaskNode("parent", "Parent task", role=Role.PLANNER)
    child = TaskNode(
        "child",
        "Child task",
        parent_id="parent",
        assigned_gates=["G_child"],
    )
    graph.add_node(parent)
    graph.add_node(child)

    # Step 1: Child executes and passes gate G_child
    graph.step()
    assert graph.nodes["child"].status == NodeStatus.ACCEPTED
    assert ledger.gates["G_child"].status == "MET"

    # Now parent is ready to complete, but before step, we simulate a regression:
    # Delete child_flag.txt!
    flag_file.unlink()

    # Step 2: Parent attempts to complete. Reverification of child gate MUST run and fail!
    graph.step()
    assert graph.nodes["parent"].status == NodeStatus.REJECTED
    # Child status is demoted to REJECTED due to failed reverification!
    assert graph.nodes["child"].status == NodeStatus.REJECTED


def test_gate_declared_owns_enforces_wave_separation():
    text = """
- [ ] G1: First
  CHECK: echo 1
  EXPECT: 1
  OWNS: src/auth.py

- [ ] G2: Second
  CHECK: echo 2
  EXPECT: 2
  OWNS: src/auth.py
"""
    lg = GateLedger.parse(text)
    graph = DAFG(ledger=lg)
    n1 = TaskNode("n1", "Task 1", assigned_gates=["G1"])
    n2 = TaskNode("n2", "Task 2", assigned_gates=["G2"])
    graph.add_node(n1)
    graph.add_node(n2)

    assert "src/auth.py" in n1.owns
    assert "src/auth.py" in n2.owns

    ready = graph.get_ready_nodes()
    waves = graph.compute_waves(ready)
    assert len(waves) == 2
    assert {waves[0][0].id, waves[1][0].id} == {"n1", "n2"}


def test_depth_tree_multilevel_descendant_reverification(tmp_path):
    """Parent verifies all descendant subtree gates, including grandchildren."""
    gc_flag = tmp_path / "gc_flag.txt"
    gc_flag.write_text("ok", encoding="utf-8")

    text = f"""
- [ ] G_gc: Grandchild gate
  CHECK: python -c "import os; exit(0 if os.path.exists(r'{gc_flag}') else 1)"
  EXPECT: .*
"""
    lg = GateLedger.parse(text)
    eng = GateEngine(auto_approve=True)
    graph = DAFG(ledger=lg, engine=eng)

    parent = TaskNode("parent", "Parent task")
    child = TaskNode("child", "Child task", parent_id="parent")
    grandchild = TaskNode("grandchild", "Grandchild task", parent_id="child", assigned_gates=["G_gc"])

    graph.add_node(parent)
    graph.add_node(child)
    graph.add_node(grandchild)

    # Step 1: grandchild executes and completes
    graph.step()
    assert graph.nodes["grandchild"].status == NodeStatus.ACCEPTED

    # Step 2: child executes and completes
    graph.step()
    assert graph.nodes["child"].status == NodeStatus.ACCEPTED

    # Now simulate regression on grandchild before parent completes
    gc_flag.unlink()

    # Step 3: parent attempts to complete -> grandchild reverification fails -> parent rejected
    graph.step()
    assert graph.nodes["parent"].status == NodeStatus.REJECTED
    assert graph.nodes["grandchild"].status == NodeStatus.REJECTED


def test_add_node_bidirectional_parent_child_link():
    graph = DAFG()
    # Child added before parent
    child = TaskNode("c1", "Child", parent_id="p1")
    graph.add_node(child)

    assert child.depth == 0

    # Now add parent
    parent = TaskNode("p1", "Parent")
    graph.add_node(parent)

    assert "c1" in parent.children
    assert child.depth == 1


def test_descendants_cycle_handling_does_not_infinite_recurse():
    """Cycles in children must be safely bounded without RecursionError."""
    graph = DAFG()
    n1 = TaskNode("n1", "Node 1", children=["n2"])
    n2 = TaskNode("n2", "Node 2", children=["n1"])
    graph.nodes["n1"] = n1
    graph.nodes["n2"] = n2

    # Executing n1 should not stack overflow in _get_descendants
    # It will block waiting for unaccepted children
    graph.execute_node(n1)
    assert n1.status == NodeStatus.BLOCKED


def test_self_dependency_and_self_parent_prevented():
    """A task cannot depend on itself or be its own parent."""
    graph = DAFG()
    node = TaskNode("self_task", "Self referencing task", parent_id="self_task")
    graph.add_node(node)
    # parent_id should be reset to None
    assert node.parent_id is None

    # Agent attempts to add dynamic need on itself
    def agent_self_need(n, ctx):
        return AgentResponse(needs=["self_task"])

    graph.execute_node(node, executor_fn=agent_self_need)
    assert "self_task" not in node.needs


def test_missing_child_node_does_not_raise_keyerror():
    """If a child ID in node.children is missing from graph, execute_node must handle gracefully."""
    graph = DAFG()
    parent = TaskNode("p1", "Parent", children=["non_existent_child"])
    graph.add_node(parent)

    # Must not crash with KeyError
    graph.execute_node(parent)
    assert parent.status == NodeStatus.BLOCKED

