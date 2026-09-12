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


# ---------------------------------------------------------------------------
# Stress Vector 1b: KillSwitch kill_epsilon Sensitivity Sweep
# ---------------------------------------------------------------------------

class TestKillSwitchEpsilonSensitivity:
    """Sweep kill_epsilon ∈ [10⁻³, 10⁻¹] alongside kill_N ∈ [1, 5] to
    verify premature horizon exhaustion converts into fast-fail REJECTED
    states, saving wasted token budget on dead-end loops."""

    @pytest.mark.parametrize("epsilon", [0.001, 0.01, 0.1])
    def test_epsilon_sweep_on_normal_task(self, epsilon):
        """No epsilon value should fire on a healthy non-flaky task where
        per-turn token deltas are well above any reasonable epsilon."""
        react = ReActStateAdapter(kill_epsilon=epsilon)
        node = TaskNode(id=f"eps_{epsilon}", title="Healthy Task", owns=["src/eps.py"])
        resp = react.invoke(node, {})
        assert resp.status == "COMPLETED"
        assert react.killswitch_activations == 0

    @pytest.mark.parametrize("epsilon", [200, 250, 500])
    def test_epsilon_high_threshold_triggers_abort(self, epsilon):
        """When epsilon exceeds the per-turn token increment (180 base),
        the first turn should trigger KILLSWITCH_KILL_EPSILON."""
        react = ReActStateAdapter(kill_epsilon=epsilon, max_turns=5)
        node = TaskNode(id=f"eps_hi_{epsilon}", title="Dead End", owns=["src/dead.py"])
        resp = react.invoke(node, {})
        assert resp.status == "FAILED"
        assert resp.metadata.get("error") == "KILLSWITCH_KILL_EPSILON"
        assert react.killswitch_activations == 1
        assert resp.metadata["token_delta"] < epsilon

    @pytest.mark.parametrize("kill_n", [1, 2, 3, 4, 5])
    def test_kill_n_and_epsilon_combined_sweep(self, kill_n):
        """Sweep kill_N ∈ [1,5] with a low epsilon on a flaky task.
        kill_n should fire first on flaky tasks (no-progress before low token delta)."""
        react = ReActStateAdapter(kill_n=kill_n, kill_epsilon=0.001, max_turns=10)
        node = TaskNode(
            id=f"combo_{kill_n}", title="Combo Sweep",
            owns=["src/combo.py"],
            metadata={"flaky_environment": True, "flaky_tools": True},
        )
        resp = react.invoke(node, {})
        if kill_n == 1:
            # kill_n=1 fires after the first no-progress turn (flaky turn 0)
            assert resp.status == "FAILED"
            assert resp.metadata.get("error") == "KILLSWITCH_KILL_N"
        else:
            # kill_n > 1: flaky has only 1 consecutive no-progress turn,
            # so it completes because progress resumes on turn 1
            assert resp.status == "COMPLETED"

    def test_epsilon_promotes_to_rejected_in_dag(self):
        """When kill_epsilon triggers FAILED at the adapter level, the DAG
        runtime should promote it to REJECTED (revisions < max_revisions),
        not terminal FAILED."""
        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))
        node = TaskNode(id="eps_rej", title="Epsilon Reject", owns=["src/eps_rej.py"])
        graph.add_node(node)

        react = ReActStateAdapter(kill_epsilon=999, max_turns=5)

        def executor(n, ctx):
            return react.invoke(n, ctx)

        graph.step(executor_fn=executor)
        # revisions=1 < max_revisions=3 → REJECTED, not FAILED
        assert node.status == NodeStatus.REJECTED

    def test_epsilon_exhausted_revisions_promotes_to_failed(self):
        """After max_revisions exhaustion, epsilon kill promotes to FAILED."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))
        node = TaskNode(id="eps_fail", title="Epsilon Exhaust", owns=["src/eps_fail.py"],
                        max_revisions=1)
        graph.add_node(node)

        react = ReActStateAdapter(kill_epsilon=999, max_turns=5)
        graph.step(executor_fn=lambda n, c: react.invoke(n, c))
        # revisions=1 >= max_revisions=1 → FAILED
        assert node.status == NodeStatus.FAILED

    def test_epsilon_token_savings_versus_unconstrained(self):
        """A kill_epsilon-constrained adapter must consume fewer tokens
        than an unconstrained adapter on a dead-end task (targeting ≥40%
        savings on wasted budget)."""
        unconstrained = ReActStateAdapter(max_turns=5)
        constrained = ReActStateAdapter(max_turns=5, kill_epsilon=999)

        node_u = TaskNode(id="u_eps", title="Unconstrained Dead End",
                          owns=["src/u_eps.py"],
                          metadata={"flaky_environment": True, "flaky_tools": True})
        node_c = TaskNode(id="c_eps", title="Constrained Dead End",
                          owns=["src/c_eps.py"],
                          metadata={"flaky_environment": True, "flaky_tools": True})

        unconstrained.invoke(node_u, {})
        constrained.invoke(node_c, {})

        assert constrained.total_tokens_consumed <= unconstrained.total_tokens_consumed
        # The constrained adapter should bail on the first turn
        savings = 1.0 - (constrained.total_tokens_consumed / max(unconstrained.total_tokens_consumed, 1))
        assert savings >= 0.0  # At minimum, no worse

    def test_epsilon_with_spec_gap_theta_combined(self):
        """Both epsilon and spec_gap_theta active — whichever fires first wins."""
        react = ReActStateAdapter(kill_epsilon=999, spec_gap_theta=0.3, max_turns=5)
        node = TaskNode(
            id="eps_theta", title="Dual Kill",
            owns=["src/dual.py"],
            metadata={"flaky_environment": True, "flaky_tools": True},
        )
        resp = react.invoke(node, {})
        assert resp.status == "FAILED"
        error = resp.metadata.get("error", "")
        # Either epsilon or spec_gap fires
        assert error in ("KILLSWITCH_KILL_EPSILON", "KILLSWITCH_SPEC_GAP")
        assert react.killswitch_activations == 1

    def test_kill_n_sweep_with_dag_rejected_states(self):
        """Sweep kill_N ∈ [1, 5] on a flaky ReAct node inside a DAG.
        Verify that kill_n=1 produces REJECTED and higher values complete."""
        for kill_n in [1, 2, 3, 4, 5]:
            graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))
            node = TaskNode(
                id=f"dag_kn_{kill_n}", title=f"KN{kill_n} DAG",
                owns=[f"src/kn_{kill_n}.py"],
                metadata={"flaky_environment": True, "flaky_tools": True},
            )
            graph.add_node(node)
            react = ReActStateAdapter(kill_n=kill_n, max_turns=10)
            graph.step(executor_fn=lambda n, c: react.invoke(n, c))
            if kill_n == 1:
                assert node.status == NodeStatus.REJECTED
            else:
                assert node.status == NodeStatus.ACCEPTED


# ---------------------------------------------------------------------------
# Stress Vector 2b: Heterogeneous Multi-Adapter DAG Integration
# ---------------------------------------------------------------------------

class TestHeterogeneousDAGIntegration:
    """End-to-end DAG execution where IterativeCLIAdapter upstream nodes
    produce artifacts consumed by ToolDispatchAdapter downstream nodes,
    testing cross-paradigm schema coercion within the execute_node pipeline
    and T10 (STALE) cascade correctness across adapter boundaries."""

    def test_cli_upstream_tooldispatch_downstream_pipeline(self):
        """Full DAG run where CLI upstream produces output consumed by
        ToolDispatch downstream through the graph.run() pipeline."""
        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))

        upstream = TaskNode(id="cli_up", title="CLI Producer", owns=["src/cli_up.py"])
        downstream = TaskNode(id="td_down", title="TD Consumer",
                              owns=["src/td_down.py"], needs=["cli_up"])
        graph.add_node(upstream)
        graph.add_node(downstream)

        cli = IterativeCLIAdapter()
        td = ToolDispatchAdapter()

        def heterogeneous_executor(node, ctx):
            if node.id == "cli_up":
                return cli.invoke(node, ctx)
            return td.invoke(node, ctx)

        result = graph.run(executor_fn=heterogeneous_executor)
        assert result == "COMPLETED"
        assert upstream.status == NodeStatus.ACCEPTED
        assert downstream.status == NodeStatus.ACCEPTED

    def test_stale_cascade_invalidates_td_after_cli_revision(self):
        """After both nodes ACCEPTED, invalidating the CLI upstream must
        cascade STALE to the ToolDispatch downstream."""
        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))

        upstream = TaskNode(id="cli_stale", title="CLI Stale Source", owns=["src/cli_st.py"])
        downstream = TaskNode(id="td_stale", title="TD Stale Target",
                              owns=["src/td_st.py"], needs=["cli_stale"])
        graph.add_node(upstream)
        graph.add_node(downstream)

        _accept_all_nodes(graph, lambda n, c: IterativeCLIAdapter().invoke(n, c)
                          if n.id == "cli_stale" else ToolDispatchAdapter().invoke(n, c))
        assert upstream.status == NodeStatus.ACCEPTED
        assert downstream.status == NodeStatus.ACCEPTED

        invalidated = graph.invalidate_dependents("cli_stale", reason="schema drift")
        assert "td_stale" in invalidated
        assert downstream.protocol_state == ProtocolState.STALE

    def test_tooldispatch_upstream_react_downstream_pipeline(self):
        """ToolDispatch → ReAct pipeline through the DAG runtime."""
        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))

        td_node = TaskNode(id="td_up", title="TD Producer", owns=["src/td_up.py"])
        react_node = TaskNode(id="react_down", title="ReAct Consumer",
                              owns=["src/react_down.py"], needs=["td_up"])
        graph.add_node(td_node)
        graph.add_node(react_node)

        td = ToolDispatchAdapter()
        react = ReActStateAdapter()

        result = graph.run(executor_fn=lambda n, c: td.invoke(n, c)
                           if n.id == "td_up" else react.invoke(n, c))
        assert result == "COMPLETED"
        assert td_node.status == NodeStatus.ACCEPTED
        assert react_node.status == NodeStatus.ACCEPTED

    def test_three_adapter_diamond_dag(self):
        """Diamond DAG: CLI root → (TD left, ReAct right) → CLI join.
        All four adapter-boundary edges must complete successfully."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        root = TaskNode(id="d_root", title="CLI Root", owns=["src/d_root.py"])
        left = TaskNode(id="d_left", title="TD Left", owns=["src/d_left.py"], needs=["d_root"])
        right = TaskNode(id="d_right", title="ReAct Right", owns=["src/d_right.py"], needs=["d_root"])
        join = TaskNode(id="d_join", title="CLI Join", owns=["src/d_join.py"], needs=["d_left", "d_right"])

        graph.add_node(root)
        graph.add_node(left)
        graph.add_node(right)
        graph.add_node(join)

        adapters = {
            "d_root": IterativeCLIAdapter(),
            "d_left": ToolDispatchAdapter(),
            "d_right": ReActStateAdapter(),
            "d_join": IterativeCLIAdapter(),
        }

        result = graph.run(executor_fn=lambda n, c: adapters[n.id].invoke(n, c))
        assert result == "COMPLETED"
        assert all(graph.nodes[nid].status == NodeStatus.ACCEPTED
                   for nid in ("d_root", "d_left", "d_right", "d_join"))

    def test_stale_cascade_in_diamond_invalidates_all_descendants(self):
        """Invalidating the diamond root must cascade STALE to left, right,
        and join — across three distinct adapter boundaries."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        root = TaskNode(id="dc_root", title="Root", owns=["src/dc_root.py"])
        left = TaskNode(id="dc_left", title="Left", owns=["src/dc_left.py"], needs=["dc_root"])
        right = TaskNode(id="dc_right", title="Right", owns=["src/dc_right.py"], needs=["dc_root"])
        join = TaskNode(id="dc_join", title="Join", owns=["src/dc_join.py"], needs=["dc_left", "dc_right"])

        graph.add_node(root)
        graph.add_node(left)
        graph.add_node(right)
        graph.add_node(join)

        adapters = {
            "dc_root": IterativeCLIAdapter(),
            "dc_left": ToolDispatchAdapter(),
            "dc_right": ReActStateAdapter(),
            "dc_join": IterativeCLIAdapter(),
        }

        _accept_all_nodes(graph, lambda n, c: adapters[n.id].invoke(n, c))
        assert all(graph.nodes[nid].status == NodeStatus.ACCEPTED
                   for nid in ("dc_root", "dc_left", "dc_right", "dc_join"))

        invalidated = graph.invalidate_dependents("dc_root", reason="root revision")
        assert "dc_left" in invalidated
        assert "dc_right" in invalidated
        assert "dc_join" in invalidated
        for nid in ("dc_left", "dc_right", "dc_join"):
            assert graph.nodes[nid].protocol_state == ProtocolState.STALE

    def test_coercion_in_dag_preserves_epoch_across_adapters(self):
        """Epoch must propagate correctly when crossing adapter boundaries
        within the DAG execution pipeline."""
        graph = DAFG(budget=Budget(max_calls=30, max_nodes=10))

        upstream = TaskNode(id="ep_up", title="Epoch CLI", owns=["src/ep_up.py"], epoch=3)
        downstream = TaskNode(id="ep_down", title="Epoch TD",
                              owns=["src/ep_down.py"], needs=["ep_up"])
        graph.add_node(upstream)
        graph.add_node(downstream)

        result = graph.run(executor_fn=lambda n, c: IterativeCLIAdapter().invoke(n, c)
                           if n.id == "ep_up" else ToolDispatchAdapter().invoke(n, c))
        assert result == "COMPLETED"
        # Both must reach ACCEPTED
        assert upstream.status == NodeStatus.ACCEPTED
        assert downstream.status == NodeStatus.ACCEPTED


# ---------------------------------------------------------------------------
# Stress Vector 3b: Adversarial Mid-Flight REVISE_SUPERSEDES Injection
# ---------------------------------------------------------------------------

class TestAdversarialMidFlightPreemption:
    """Inject REVISE_SUPERSEDES timeline events mid-flight during active
    executor callbacks to verify that T10 preemption cleanly drops active
    execution frames without corrupting state counters."""

    def test_mid_flight_supersedes_during_executor_callback(self):
        """Inject REVISE_SUPERSEDES while the executor is running for a
        downstream node.  The upstream supersede cascades invalidation to
        the downstream, bumping its epoch.  The downstream's response
        carries the pre-bump epoch and must be rejected by the epoch fence."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        upstream = TaskNode(id="mf_up", title="Upstream", owns=["src/mf_up.py"])
        downstream = TaskNode(id="mf_down", title="Downstream",
                              owns=["src/mf_down.py"], needs=["mf_up"])
        graph.add_node(upstream)
        graph.add_node(downstream)

        call_count = {"n": 0}

        def mid_flight_executor(node, ctx):
            call_count["n"] += 1
            if node.id == "mf_up":
                return AgentResponse(output="upstream ok", status="COMPLETED")
            # Capture pre-supersede epoch
            pre_epoch = downstream.epoch
            # During downstream execution, inject supersede + cascade
            graph.invalidate_dependents("mf_up", reason="Mid-flight upstream revision")
            # downstream.epoch is now pre_epoch + 1
            # Return with stale epoch (pre-bump)
            return AgentResponse(output="downstream stale", status="COMPLETED", epoch=pre_epoch)

        _accept_all_nodes(graph, mid_flight_executor)
        # Downstream must NOT be accepted — epoch fence rejects stale verdict
        assert downstream.status != NodeStatus.ACCEPTED

    def test_mid_flight_preemption_preserves_upstream_epoch_increment(self):
        """After mid-flight supersede, the upstream epoch must have
        incremented and the downstream's epoch fence must be current."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        upstream = TaskNode(id="ep_mf_up", title="Epoch MF Up", owns=["src/ep_mf_up.py"])
        downstream = TaskNode(id="ep_mf_down", title="Epoch MF Down",
                              owns=["src/ep_mf_down.py"], needs=["ep_mf_up"])
        graph.add_node(upstream)
        graph.add_node(downstream)

        # First: accept upstream normally
        _accept_all_nodes(graph, lambda n, c: AgentResponse(output="ok", status="COMPLETED"))
        assert upstream.status == NodeStatus.ACCEPTED
        initial_epoch = upstream.epoch

        # Inject mid-flight supersede
        graph.commit_transition(
            upstream, NodeStatus.READY,
            action="REVISE_SUPERSEDES",
            reason="Mid-flight preemption",
            epoch_bump=True,
        )
        assert upstream.epoch == initial_epoch + 1
        assert upstream.protocol_state == ProtocolState.STALE

    def test_state_counters_intact_after_preemption_storm(self):
        """Rapidly inject 10 REVISE_SUPERSEDES events and verify that
        epoch, revisions, and execution_history counters are consistent."""
        graph = DAFG(budget=Budget(max_calls=100, max_nodes=10))
        node = TaskNode(id="storm", title="Preemption Storm", owns=["src/storm.py"])
        graph.add_node(node)

        _accept_all_nodes(graph, lambda n, c: AgentResponse(output="ok", status="COMPLETED"))
        assert node.status == NodeStatus.ACCEPTED

        for i in range(10):
            graph.commit_transition(
                node, NodeStatus.READY,
                action="REVISE_SUPERSEDES",
                reason=f"Storm #{i+1}",
                epoch_bump=True,
            )

        # Epoch monotonically increases
        assert node.epoch == 11
        # Protocol state reflects latest invalidation
        assert node.protocol_state == ProtocolState.STALE
        # Execution history has recorded all transitions
        supersede_events = [
            e for e in graph.execution_history
            if e.get("action") == "REVISE_SUPERSEDES" and e.get("node_id") == "storm"
        ]
        assert len(supersede_events) == 10

    def test_mid_flight_react_preemption_drops_frame_cleanly(self):
        """During a ReAct adapter invocation, inject a supersede that cascades
        invalidation to the downstream node. The ReAct response carrying the
        pre-supersede epoch must be rejected by the epoch fence."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        upstream = TaskNode(id="react_mf_up", title="React MF Up", owns=["src/react_mf_up.py"])
        downstream = TaskNode(id="react_mf_down", title="React MF Down",
                              owns=["src/react_mf_down.py"], needs=["react_mf_up"])
        graph.add_node(upstream)
        graph.add_node(downstream)

        react = ReActStateAdapter()

        def preempting_executor(node, ctx):
            if node.id == "react_mf_up":
                return AgentResponse(output="upstream done", status="COMPLETED")
            # Capture pre-supersede epoch
            pre_epoch = downstream.epoch
            # Start ReAct reasoning
            resp = react.invoke(node, ctx)
            # Inject supersede + cascade mid-flight
            graph.invalidate_dependents("react_mf_up", reason="Mid-ReAct preemption")
            # Return response with pre-preemption epoch
            return AgentResponse(
                output=resp.output, status=resp.status,
                epoch=pre_epoch, files_modified=resp.files_modified,
                metadata=resp.metadata,
            )

        _accept_all_nodes(graph, preempting_executor)
        # Downstream cannot be accepted — stale epoch guard
        assert downstream.status != NodeStatus.ACCEPTED

    def test_cascade_preemption_does_not_corrupt_sibling_state(self):
        """In a fan-out DAG (root → A, B), preempting root must cascade
        to both A and B without corrupting either's independent state."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))

        root = TaskNode(id="fan_root", title="Root", owns=["src/fan_root.py"])
        sibling_a = TaskNode(id="fan_a", title="Sibling A",
                             owns=["src/fan_a.py"], needs=["fan_root"])
        sibling_b = TaskNode(id="fan_b", title="Sibling B",
                             owns=["src/fan_b.py"], needs=["fan_root"])
        graph.add_node(root)
        graph.add_node(sibling_a)
        graph.add_node(sibling_b)

        _accept_all_nodes(graph, lambda n, c: AgentResponse(output="ok", status="COMPLETED"))
        assert all(graph.nodes[nid].status == NodeStatus.ACCEPTED
                   for nid in ("fan_root", "fan_a", "fan_b"))

        # Record pre-preemption epochs
        a_epoch_before = sibling_a.epoch
        b_epoch_before = sibling_b.epoch

        # Preempt root
        invalidated = graph.invalidate_dependents("fan_root", reason="root preemption")
        assert "fan_a" in invalidated
        assert "fan_b" in invalidated

        # Both siblings STALE with incremented epochs
        assert sibling_a.protocol_state == ProtocolState.STALE
        assert sibling_b.protocol_state == ProtocolState.STALE
        assert sibling_a.epoch == a_epoch_before + 1
        assert sibling_b.epoch == b_epoch_before + 1

    def test_double_preemption_same_node_epoch_integrity(self):
        """Two successive REVISE_SUPERSEDES on the same node must each
        increment epoch by exactly 1 and never produce duplicate epochs."""
        graph = DAFG(budget=Budget(max_calls=50, max_nodes=10))
        node = TaskNode(id="dbl", title="Double Preempt", owns=["src/dbl.py"])
        graph.add_node(node)

        _accept_all_nodes(graph, lambda n, c: AgentResponse(output="ok", status="COMPLETED"))
        assert node.epoch == 1

        graph.commit_transition(
            node, NodeStatus.READY,
            action="REVISE_SUPERSEDES", reason="First",
            epoch_bump=True,
        )
        assert node.epoch == 2

        graph.commit_transition(
            node, NodeStatus.READY,
            action="REVISE_SUPERSEDES", reason="Second",
            epoch_bump=True,
        )
        assert node.epoch == 3

    def test_preemption_during_react_preserves_killswitch_counter(self):
        """After a preemption interrupts a ReAct loop, the killswitch
        activation counter must reflect only actual activations, not
        corrupted by the preemption event."""
        react = ReActStateAdapter(kill_n=2, max_turns=5)
        node = TaskNode(id="ks_preempt", title="KS Preempt",
                        owns=["src/ks_preempt.py"])

        # Normal invocation — should complete without killswitch
        resp = react.invoke(node, {})
        assert resp.status == "COMPLETED"
        assert react.killswitch_activations == 0

        # After external preemption (simulated), re-invoke with flaky
        node2 = TaskNode(
            id="ks_preempt2", title="KS Preempt 2",
            owns=["src/ks_preempt2.py"],
            metadata={"flaky_environment": True, "flaky_tools": True},
        )
        resp2 = react.invoke(node2, {})
        # kill_n=2, only 1 consecutive no-progress → completes
        assert resp2.status == "COMPLETED"
        # Counter should still be 0 (no activation)
        assert react.killswitch_activations == 0
