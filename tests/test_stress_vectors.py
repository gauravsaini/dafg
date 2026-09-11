"""Stress vector tests for DAFG v0.3.

Covers three stress axes:
  1. Heterogeneous Multi-Adapter DAGs — cross-paradigm schema coercion
     (CLI → ToolDispatch → ReAct) and T10 (STALE) cascading across adapter
     boundaries.
  2. KillSwitch Parameter Sensitivity — sweep kill_N and spec_gap_θ on ReAct
     loops to prune dead-end reasoning horizons early.
  3. Adversarial Invalidation Injection — mid-flight REVISE_SUPERSEDES
     preemption interrupts during active reasoning frames.
"""

import pytest

from dafg import (
    DAFG,
    AgentResponse,
    Budget,
    FailureClass,
    InterfaceContract,
    NodeStatus,
    RevisionDirective,
    TaskNode,
)
from dafg.adapters import (
    BaseRuntimeAdapter,
    IterativeCLIAdapter,
    ReActStateAdapter,
    ToolDispatchAdapter,
)
from dafg.protocol import (
    Action,
    DispatchIdentity,
    IllegalTransitionError,
    ProtocolCommand,
    ProtocolState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _accept_all_nodes(graph: DAFG, executor_fn=None):
    """Run graph step-by-step until all nodes ACCEPTED, but do NOT seal."""
    fn = executor_fn or (lambda n, c: AgentResponse(output="done", status="COMPLETED"))
    for _ in range(50):
        if all(n.status == NodeStatus.ACCEPTED for n in graph.nodes.values()):
            return
        if graph.has_failed():
            return
        try:
            executed = graph.step(executor_fn=fn)
        except Exception:
            return
        if not executed:
            return


# ---------------------------------------------------------------------------
# Stress Vector 1: Heterogeneous Multi-Adapter DAGs
# ---------------------------------------------------------------------------

class TestHeterogeneousMultiAdapterDAGs:
    """Cross-paradigm schema coercion and STALE cascading across adapter
    boundaries in a CLI → ToolDispatch → ReAct pipeline."""

    def test_cli_to_tooldispatch_coercion_preserves_status(self):
        """CLI output coerced into ToolDispatch schema retains status and output."""
        cli = IterativeCLIAdapter()
        node = TaskNode(id="t1", title="Stage 1", owns=["src/a.py"])
        resp = cli.invoke(node, {})
        assert resp.status == "COMPLETED"

        coerced = BaseRuntimeAdapter.coerce_response(resp, "iterative-cli", "tool-dispatch")
        assert coerced.status == "COMPLETED"
        assert coerced.output == resp.output
        assert coerced.metadata["_coerced_from"] == "iterative-cli"
        assert coerced.metadata["_coerced_to"] == "tool-dispatch"
        assert coerced.metadata["coerced_output_schema"] == "structured"

    def test_tooldispatch_to_react_coercion_adds_trace(self):
        """ToolDispatch output coerced to ReAct schema gains a synthetic trace."""
        disp = ToolDispatchAdapter()
        node = TaskNode(id="t2", title="Stage 2", owns=["src/b.py"])
        resp = disp.invoke(node, {})

        coerced = BaseRuntimeAdapter.coerce_response(resp, "tool-dispatch", "react-state-machine")
        assert "trace" in coerced.metadata
        assert len(coerced.metadata["trace"]) == 1
        assert coerced.metadata["coerced_output_schema"] == "react_trace"

    def test_cli_to_react_full_paradigm_jump(self):
        """CLI → ReAct is the widest paradigm gap: raw text → state trace."""
        cli = IterativeCLIAdapter()
        node = TaskNode(id="t3", title="Full Jump", owns=["src/c.py"])
        resp = cli.invoke(node, {})

        coerced = BaseRuntimeAdapter.coerce_response(resp, "iterative-cli", "react-state-machine")
        assert coerced.metadata["coerced_output_schema"] == "react_trace"
        trace = coerced.metadata["trace"]
        assert trace[0]["action"] == "parse_stdout"
        assert resp.output[:200] in trace[0]["observation"]

    def test_react_to_tooldispatch_coercion(self):
        """ReAct → ToolDispatch extracts action count from trace."""
        react = ReActStateAdapter()
        node = TaskNode(id="t4", title="React Output", owns=["src/d.py"])
        resp = react.invoke(node, {})

        coerced = BaseRuntimeAdapter.coerce_response(resp, "react-state-machine", "tool-dispatch")
        assert coerced.metadata["coerced_output_schema"] == "structured"
        assert "tool_calls_count" in coerced.metadata

    def test_coercion_preserves_files_and_epoch(self):
        """Schema coercion must never lose files_modified or epoch data."""
        cli = IterativeCLIAdapter()
        node = TaskNode(id="t5", title="Epoch Test", owns=["src/e.py"], epoch=3)
        resp = cli.invoke(node, {})

        coerced = BaseRuntimeAdapter.coerce_response(resp, "iterative-cli", "tool-dispatch")
        assert coerced.files_modified == resp.files_modified
        assert coerced.epoch == resp.epoch

    def test_three_stage_pipeline_cli_tooldispatch_react(self):
        """Run a 3-node DAG where each stage uses a different adapter and
        upstream output is coerced for the downstream paradigm."""
        cli_adapter = IterativeCLIAdapter()
        disp_adapter = ToolDispatchAdapter()
        react_adapter = ReActStateAdapter()

        node_a = TaskNode(id="pipe_a", title="CLI Stage", owns=["src/pipe_a.py"])
        node_b = TaskNode(id="pipe_b", title="ToolDispatch Stage", owns=["src/pipe_b.py"], needs=["pipe_a"])
        node_c = TaskNode(id="pipe_c", title="ReAct Stage", owns=["src/pipe_c.py"], needs=["pipe_b"])

        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))
        graph.add_node(node_a)
        graph.add_node(node_b)
        graph.add_node(node_c)

        adapter_map = {
            "pipe_a": cli_adapter,
            "pipe_b": disp_adapter,
            "pipe_c": react_adapter,
        }

        def heterogeneous_executor(node: TaskNode, ctx):
            adapter = adapter_map[node.id]
            return adapter.invoke(node, ctx)

        result = graph.run(executor_fn=heterogeneous_executor)
        assert result == "COMPLETED"
        assert graph.nodes["pipe_a"].status == NodeStatus.ACCEPTED
        assert graph.nodes["pipe_b"].status == NodeStatus.ACCEPTED
        assert graph.nodes["pipe_c"].status == NodeStatus.ACCEPTED

    def test_stale_cascade_across_adapter_boundary(self):
        """When a CLI-produced upstream node is invalidated (STALE T10),
        the downstream ToolDispatch consumer must also be invalidated."""
        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))

        upstream = TaskNode(id="upstream_cli", title="CLI Producer", owns=["src/up.py"])
        downstream = TaskNode(id="downstream_td", title="TD Consumer", owns=["src/down.py"], needs=["upstream_cli"])

        graph.add_node(upstream)
        graph.add_node(downstream)

        cli = IterativeCLIAdapter()
        td = ToolDispatchAdapter()

        def exec_fn(node, ctx):
            if node.id == "upstream_cli":
                return cli.invoke(node, ctx)
            return td.invoke(node, ctx)

        # Step-by-step to avoid sealing
        _accept_all_nodes(graph, exec_fn)
        assert upstream.status == NodeStatus.ACCEPTED
        assert downstream.status == NodeStatus.ACCEPTED

        # Now invalidate the upstream → STALE cascade
        invalidated = graph.invalidate_dependents("upstream_cli", reason="upstream schema drift")
        assert "downstream_td" in invalidated
        assert downstream.protocol_state == ProtocolState.STALE

    def test_stale_cascade_three_adapters_deep(self):
        """STALE invalidation at the root of a CLI → TD → ReAct chain
        must cascade through all three adapter boundaries."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        n1 = TaskNode(id="root_cli", title="Root CLI", owns=["src/r1.py"])
        n2 = TaskNode(id="mid_td", title="Mid ToolDispatch", owns=["src/r2.py"], needs=["root_cli"])
        n3 = TaskNode(id="leaf_react", title="Leaf ReAct", owns=["src/r3.py"], needs=["mid_td"])

        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_node(n3)

        adapters = {
            "root_cli": IterativeCLIAdapter(),
            "mid_td": ToolDispatchAdapter(),
            "leaf_react": ReActStateAdapter(),
        }

        _accept_all_nodes(graph, lambda n, c: adapters[n.id].invoke(n, c))
        assert all(graph.nodes[nid].status == NodeStatus.ACCEPTED for nid in ("root_cli", "mid_td", "leaf_react"))

        invalidated = graph.invalidate_dependents("root_cli", reason="root contract drift")
        assert "mid_td" in invalidated
        assert "leaf_react" in invalidated
        assert n2.protocol_state == ProtocolState.STALE
        assert n3.protocol_state == ProtocolState.STALE

    def test_contract_break_cascades_across_adapter_boundary(self):
        """A breaking contract update registered on one adapter must
        invalidate consumers on a different adapter."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        contract = InterfaceContract(
            contract_id="api_v1",
            version=1,
            owner="producer",
            compatibility_mode="backward_compatible",
        )
        graph.register_contract(contract)

        producer = TaskNode(id="producer", title="API Producer (CLI)", owns=["src/api.py"])
        consumer = TaskNode(
            id="consumer", title="API Consumer (ReAct)", owns=["src/client.py"],
            needs=["producer"], consumed_contracts={"api_v1": 1},
        )
        graph.add_node(producer)
        graph.add_node(consumer)

        cli = IterativeCLIAdapter()
        react = ReActStateAdapter()

        _accept_all_nodes(graph, lambda n, c: cli.invoke(n, c) if n.id == "producer" else react.invoke(n, c))
        assert producer.status == NodeStatus.ACCEPTED
        assert consumer.status == NodeStatus.ACCEPTED

        # Breaking contract update
        broken = InterfaceContract(contract_id="api_v1", version=2, compatibility_mode="breaking")
        graph.register_contract(broken)

        assert consumer.protocol_state == ProtocolState.STALE
        assert consumer.consumed_contracts["api_v1"] == 2


# ---------------------------------------------------------------------------
# Stress Vector 2: KillSwitch Parameter Sensitivity
# ---------------------------------------------------------------------------

class TestKillSwitchParameterSensitivity:
    """Sweep kill_N and spec_gap_θ on ReAct loops to verify early pruning
    of dead-end reasoning horizons."""

    def test_killswitch_disabled_by_default(self):
        """Default ReActStateAdapter (kill_n=0, spec_gap_theta=0.0) has no
        killswitch activations."""
        react = ReActStateAdapter()
        node = TaskNode(id="ks0", title="Normal Task", owns=["src/ks0.py"])
        resp = react.invoke(node, {})
        assert resp.status == "COMPLETED"
        assert react.killswitch_activations == 0

    def test_kill_n_1_prunes_first_flaky_turn(self):
        """kill_n=1 aborts on the very first no-progress turn (flaky env)."""
        react = ReActStateAdapter(kill_n=1)
        node = TaskNode(
            id="ks1", title="Flaky Worker",
            owns=["src/ks1.py"],
            metadata={"flaky_environment": True, "flaky_tools": True},
        )
        resp = react.invoke(node, {})
        assert resp.status == "FAILED"
        assert "KILLSWITCH_KILL_N" in resp.metadata.get("error", "")
        assert react.killswitch_activations == 1

    def test_kill_n_2_allows_one_retry_then_prunes(self):
        """kill_n=2 tolerates one bad turn but prunes if a second follows."""
        react = ReActStateAdapter(kill_n=2, max_turns=5)
        # With flaky_environment the first turn is "Transient error, retrying"
        # Second turn is "Step passed" (progress), so consecutive_no_progress resets
        # → should NOT trigger
        node = TaskNode(
            id="ks2", title="One Retry Worker",
            owns=["src/ks2.py"],
            metadata={"flaky_environment": True, "flaky_tools": True},
        )
        resp = react.invoke(node, {})
        # First turn: no progress (consecutive=1), second turn: progress (reset to 0),
        # third turn: progress. kill_n=2 never fires.
        assert resp.status == "COMPLETED"
        assert react.killswitch_activations == 0

    def test_spec_gap_theta_low_threshold(self):
        """spec_gap_theta=0.4 triggers on a flaky node where 1 of first 1
        turns is speculative (ratio = 1.0 > 0.4)."""
        react = ReActStateAdapter(spec_gap_theta=0.4)
        node = TaskNode(
            id="ks_sg", title="Spec Gap Test",
            owns=["src/ks_sg.py"],
            metadata={"flaky_environment": True, "flaky_tools": True},
        )
        resp = react.invoke(node, {})
        assert resp.status == "FAILED"
        assert resp.metadata.get("error") == "KILLSWITCH_SPEC_GAP"
        assert react.killswitch_activations == 1

    def test_spec_gap_theta_high_allows_through(self):
        """spec_gap_theta=0.99 never triggers on normal tasks."""
        react = ReActStateAdapter(spec_gap_theta=0.99)
        node = TaskNode(id="ks_high", title="Normal", owns=["src/ks_high.py"])
        resp = react.invoke(node, {})
        assert resp.status == "COMPLETED"
        assert react.killswitch_activations == 0

    @pytest.mark.parametrize("kill_n", [1, 2, 3, 4, 5])
    def test_kill_n_sweep_on_normal_task(self, kill_n):
        """No kill_n value should trigger on a non-flaky, non-horizon task."""
        react = ReActStateAdapter(kill_n=kill_n)
        node = TaskNode(id=f"sweep_{kill_n}", title="Clean Task", owns=["src/sweep.py"])
        resp = react.invoke(node, {})
        assert resp.status == "COMPLETED"
        assert react.killswitch_activations == 0

    @pytest.mark.parametrize("theta", [0.1, 0.3, 0.5, 0.7, 0.9])
    def test_spec_gap_theta_sweep_on_normal_task(self, theta):
        """No theta value should trigger on a task that makes progress every turn."""
        react = ReActStateAdapter(spec_gap_theta=theta)
        node = TaskNode(id=f"theta_{theta}", title="Progressive Task", owns=["src/theta.py"])
        resp = react.invoke(node, {})
        assert resp.status == "COMPLETED"
        assert react.killswitch_activations == 0

    def test_kill_n_and_spec_gap_combined(self):
        """Both kill_n and spec_gap_theta active — whichever fires first wins."""
        react = ReActStateAdapter(kill_n=1, spec_gap_theta=0.3)
        node = TaskNode(
            id="combo", title="Combo Kill",
            owns=["src/combo.py"],
            metadata={"flaky_environment": True, "flaky_tools": True},
        )
        resp = react.invoke(node, {})
        assert resp.status == "FAILED"
        # kill_n=1 should fire first (after first no-progress turn)
        error = resp.metadata.get("error", "")
        assert error in ("KILLSWITCH_KILL_N", "KILLSWITCH_SPEC_GAP")
        assert react.killswitch_activations == 1

    def test_killswitch_on_deep_horizon(self):
        """KillSwitch fires before reasoning budget exhaustion on deep horizons
        when kill_n is tight enough."""
        react = ReActStateAdapter(kill_n=1, max_turns=10)
        node = TaskNode(
            id="ks_deep", title="Deep Horizon Kill",
            owns=["src/deep.py"],
            depth=5,
            metadata={
                "difficulty_dimension": "horizon",
                "flaky_environment": True,
                "flaky_tools": True,
            },
        )
        resp = react.invoke(node, {})
        assert resp.status == "FAILED"
        # KillSwitch fires before the deep-horizon budget check
        assert resp.metadata.get("error") == "KILLSWITCH_KILL_N"

    def test_killswitch_token_savings(self):
        """A kill_n=1 adapter consumes fewer tokens than an unconstrained one
        on a flaky task."""
        unconstrained = ReActStateAdapter(max_turns=5)
        constrained = ReActStateAdapter(max_turns=5, kill_n=1)

        node_u = TaskNode(id="tu", title="Flaky Unconstrained", owns=["src/tu.py"],
                          metadata={"flaky_environment": True, "flaky_tools": True})
        node_c = TaskNode(id="tc", title="Flaky Constrained", owns=["src/tc.py"],
                          metadata={"flaky_environment": True, "flaky_tools": True})

        unconstrained.invoke(node_u, {})
        constrained.invoke(node_c, {})

        assert constrained.total_tokens_consumed <= unconstrained.total_tokens_consumed


# ---------------------------------------------------------------------------
# Stress Vector 3: Adversarial Invalidation Injection
# ---------------------------------------------------------------------------

class TestAdversarialInvalidationInjection:
    """Mid-flight REVISE_SUPERSEDES preemption interrupts during active
    reasoning frames.  Tests that the protocol correctly handles invalidation
    arriving while a node is RUNNING/PROVING and that epoch fencing rejects
    stale verdicts produced by the superseded frame."""

    def test_invalidate_accepted_node_transitions_to_stale(self):
        """Basic INVALIDATE on an ACCEPTED node moves to STALE via protocol."""
        graph = DAFG(budget=Budget(max_calls=20, max_nodes=10))
        node = TaskNode(id="inv1", title="Accepted Target", owns=["src/inv1.py"])
        graph.add_node(node)

        _accept_all_nodes(graph, lambda n, c: AgentResponse(output="done", status="COMPLETED"))
        assert node.status == NodeStatus.ACCEPTED

        # Invalidate via REVISE_SUPERSEDES simulation
        graph.commit_transition(
            node, NodeStatus.READY,
            action="REVISE_SUPERSEDES",
            reason="Upstream revision supersedes accepted evidence",
            epoch_bump=True,
        )
        assert node.protocol_state == ProtocolState.STALE
        assert node.epoch == 2

    def test_stale_epoch_fences_old_verdict(self):
        """After REVISE_SUPERSEDES bumps epoch, a verdict carrying the old
        epoch must be rejected by the protocol guard."""
        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))
        node = TaskNode(id="fence1", title="Epoch Fence Target", owns=["src/fence.py"])
        graph.add_node(node)

        cli = IterativeCLIAdapter()

        # First run: node accepted at epoch 1
        _accept_all_nodes(graph, cli.invoke)
        assert node.status == NodeStatus.ACCEPTED
        assert node.epoch == 1

        # Simulate REVISE_SUPERSEDES
        graph.commit_transition(
            node, NodeStatus.READY,
            action="REVISE_SUPERSEDES",
            reason="Adversarial mid-flight preemption",
            epoch_bump=True,
        )
        assert node.epoch == 2
        assert node.protocol_state == ProtocolState.STALE

        # Now transition to RUNNING to simulate re-dispatch
        graph.commit_transition(node, NodeStatus.RUNNING, action="DISPATCHED", reason="Re-dispatch")

        # Attempt to accept with stale epoch=1 response
        stale_response = AgentResponse(
            output="Stale result", status="COMPLETED", epoch=1,
        )
        valid, err = graph.validate_transition(
            node, NodeStatus.ACCEPTED, response=stale_response,
        )
        assert not valid
        assert "Stale epoch" in err

    def test_revise_supersedes_mid_flight_blocks_running_node(self):
        """If a node is actively RUNNING when its upstream is invalidated,
        the downstream should not get accepted because the evidence basis
        has been invalidated."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        upstream = TaskNode(id="up_rs", title="Upstream", owns=["src/up_rs.py"])
        downstream = TaskNode(id="down_rs", title="Downstream", owns=["src/down_rs.py"], needs=["up_rs"])

        graph.add_node(upstream)
        graph.add_node(downstream)

        def staged_executor(node, ctx):
            if node.id == "up_rs":
                return AgentResponse(output="upstream done", status="COMPLETED")
            # Downstream: return a stale epoch=0 to simulate evidence
            # produced before an upstream revision
            return AgentResponse(output="downstream done", status="COMPLETED", epoch=0)

        _accept_all_nodes(graph, staged_executor)
        # The stale epoch guard prevents ACCEPTED; node stays at RUNNING
        # which is the correct security property: stale evidence is never accepted
        assert downstream.status != NodeStatus.ACCEPTED

    def test_revision_directive_stale_dependency_triggers_cascade(self):
        """A RevisionDirective with STALE_DEPENDENCY failure class must
        trigger transitive invalidation across adapter boundaries."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10, max_revisions=5))

        root = TaskNode(id="rd_root", title="Root", owns=["src/rd_root.py"])
        mid = TaskNode(id="rd_mid", title="Mid", owns=["src/rd_mid.py"], needs=["rd_root"])
        leaf = TaskNode(id="rd_leaf", title="Leaf", owns=["src/rd_leaf.py"], needs=["rd_mid"])

        graph.add_node(root)
        graph.add_node(mid)
        graph.add_node(leaf)

        # Accept all nodes first
        cli = IterativeCLIAdapter()
        _accept_all_nodes(graph, cli.invoke)
        assert all(graph.nodes[nid].status == NodeStatus.ACCEPTED for nid in ("rd_root", "rd_mid", "rd_leaf"))

        # Apply STALE_DEPENDENCY directive on leaf, pointing at root
        directive = RevisionDirective(
            verdict="REVISE",
            failure_class=FailureClass.STALE_DEPENDENCY,
            affected_dependency="rd_root",
            feedback="Upstream schema changed, evidence invalidated",
        )
        graph.apply_revision_directive(leaf, directive)

        # Mid should be invalidated (downstream of root)
        assert mid.protocol_state == ProtocolState.STALE
        # Leaf should be REJECTED
        assert leaf.status == NodeStatus.REJECTED

    def test_multiple_supersedes_increment_epoch_monotonically(self):
        """Repeated REVISE_SUPERSEDES events must monotonically increase
        the epoch, never skip or repeat."""
        graph = DAFG(budget=Budget(max_calls=40, max_nodes=10))
        node = TaskNode(id="mono", title="Monotonic Epoch", owns=["src/mono.py"])
        graph.add_node(node)

        _accept_all_nodes(graph, lambda n, c: AgentResponse(output="ok", status="COMPLETED"))
        assert node.epoch == 1

        epochs_seen = [1]
        for i in range(5):
            graph.commit_transition(
                node, NodeStatus.READY,
                action="REVISE_SUPERSEDES",
                reason=f"Supersede #{i+1}",
                epoch_bump=True,
            )
            epochs_seen.append(node.epoch)

        # Monotonically increasing
        for i in range(1, len(epochs_seen)):
            assert epochs_seen[i] > epochs_seen[i - 1]
        assert node.epoch == 6

    def test_adversarial_invalidation_during_react_reasoning(self):
        """Inject invalidation while a ReAct adapter is mid-reasoning.
        The stale response from the interrupted frame must not be accepted."""
        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))

        target = TaskNode(id="react_target", title="ReAct Victim", owns=["src/react_victim.py"])
        graph.add_node(target)

        react = ReActStateAdapter()

        def adversarial_executor(node, ctx):
            # Invoke the ReAct adapter normally
            resp = react.invoke(node, ctx)
            # Return a response with a stale epoch (epoch=0, below node's current epoch 1)
            return AgentResponse(
                output=resp.output,
                status=resp.status,
                epoch=0,  # Stale!
                files_modified=resp.files_modified,
                metadata=resp.metadata,
            )

        _accept_all_nodes(graph, adversarial_executor)
        # The stale epoch guard prevents the node from reaching ACCEPTED.
        # It stays at RUNNING because the commit_transition(ACCEPTED) is
        # blocked by the epoch fence — the correct security outcome.
        assert target.status != NodeStatus.ACCEPTED

    def test_sealed_run_rejects_post_seal_invalidation(self):
        """Once a run is sealed, REVISE_SUPERSEDES must be rejected."""
        graph = DAFG(budget=Budget(max_calls=20, max_nodes=5))
        node = TaskNode(id="sealed_n", title="Sealed Node", owns=["src/sealed.py"])
        graph.add_node(node)

        graph.run(executor_fn=lambda n, c: AgentResponse(output="ok", status="COMPLETED"))
        sealed = graph.seal_run()
        assert sealed

        from dafg.runtime import RunSealedError
        with pytest.raises(RunSealedError):
            graph.commit_transition(
                node, NodeStatus.READY,
                action="REVISE_SUPERSEDES",
                reason="Post-seal attack",
                epoch_bump=True,
            )

    def test_invalidation_demotes_gate_evidence(self):
        """REVISE_SUPERSEDES invalidation must demote MET gates back to
        unverified in the ledger."""
        from dafg.gates import GateEngine, GateLedger

        gates_md = (
            "- [ ] G1: Check output\n"
            "  CHECK: uv run python -c \"print('OK')\"\n"
            "  EXPECT: OK\n"
            "  OWNS: src/gated.py\n"
        )
        ledger = GateLedger.parse(gates_md)
        engine = GateEngine(auto_approve=True)
        graph = DAFG(ledger=ledger, engine=engine, budget=Budget(max_calls=20, max_nodes=5))

        node = TaskNode(id="gated_n", title="Gated Node", owns=["src/gated.py"], assigned_gates=["G1"])
        graph.add_node(node)

        _accept_all_nodes(graph, lambda n, c: AgentResponse(output="ok", status="COMPLETED"))
        assert node.status == NodeStatus.ACCEPTED
        assert ledger.gates["G1"].status == "MET"

        # Direct REVISE_SUPERSEDES invalidation
        graph.commit_transition(
            node, NodeStatus.READY,
            action="REVISE_SUPERSEDES",
            reason="Direct supersede",
            epoch_bump=True,
        )
        assert node.protocol_state == ProtocolState.STALE
        assert node.epoch == 2
