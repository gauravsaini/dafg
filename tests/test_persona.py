"""Unit and integration tests for Persona Compiler, Agent Router, and Bounded Adaptation."""

import pytest

from dafg import (
    DAFG,
    AgentResponse,
    AgentRouter,
    ApprovalStore,
    Backend,
    BackendRegistry,
    Budget,
    FailureClassifier,
    FailureKind,
    Gate,
    GateEngine,
    GateLedger,
    NodeStatus,
    PersonaCompiler,
    PersonaProfile,
    PersonaSwitcher,
    PolicyEngine,
    RoutingBlockedError,
    TaskNode,
)


def test_persona_compiler_basic():
    compiler = PersonaCompiler()
    task = TaskNode(
        id="N3",
        title="Design downstream artifact invalidation and consistency",
        role="Distributed systems specialist",
        assigned_gates=["G1"],
    )
    profile = compiler.compile(task)

    assert profile.persona_id == "P-N3-v1"
    assert profile.role == "Distributed systems specialist"
    assert "system_design" in profile.required_capabilities
    assert "technical_reasoning" in profile.required_capabilities
    assert "distributed consistency" in profile.expertise
    assert any("invalidation races" in rf for rf in profile.review_focus)
    assert "repository_read" in profile.requested_tools
    # Fix verification: 'invalidation' must NOT trigger 'malformed payload handling'
    assert "malformed payload handling" not in profile.review_focus


def test_persona_compiler_no_spurious_substring_matches():
    compiler = PersonaCompiler()

    # 1. Default task with role='coder' must NOT pick up code_analysis if title has no coding words
    task_default = TaskNode(id="T1", title="Plan high level migration strategy")
    profile_default = compiler.compile(task_default)
    assert "code_analysis" not in profile_default.required_capabilities
    assert "software engineering" not in profile_default.expertise
    assert profile_default.required_capabilities == ["technical_reasoning"]

    # 2. 'author' must not trigger 'auth' (security_auditing)
    task_author = TaskNode(id="T2", title="Author release summary")
    profile_author = compiler.compile(task_author)
    assert "security_auditing" not in profile_author.required_capabilities

    # 3. 'statement' must not trigger 'state' (system_design)
    task_statement = TaskNode(id="T3", title="Review statement of work")
    profile_statement = compiler.compile(task_statement)
    assert "system_design" not in profile_statement.required_capabilities


def test_persona_serialization():
    p = PersonaProfile(
        persona_id="P-1",
        role="Architect",
        mission="Design system",
        expertise=["networking"],
        method=["step 1"],
        required_capabilities=["system_design"],
        requested_tools=["test_runner"],
    )
    d = p.to_dict()
    assert d["persona_id"] == "P-1"
    p2 = PersonaProfile.from_dict(d)
    assert p2.role == "Architect"
    assert p2.expertise == ["networking"]


def test_backend_registry_and_capabilities():
    reg = BackendRegistry.default_registry()
    fast = reg.get("fast-worker")
    assert fast is not None
    assert fast.supports(["fast_generation"])
    assert not fast.supports(["formal_verification"])

    expert = reg.get("expert-architect")
    assert expert is not None
    assert expert.supports(["system_design", "technical_reasoning"])


def test_policy_engine_tool_authorization():
    # Persona requests tools, but policy strictly filters them
    policy = PolicyEngine(allowed_tools={"repository_read", "file_write"})
    task = TaskNode(id="T1", title="Write test")
    
    requested = ["repository_read", "file_write", "arbitrary_network_exec", "delete_all_files"]
    authorized = policy.authorize(requested, task)
    assert authorized == ["repository_read", "file_write"]
    assert "arbitrary_network_exec" not in authorized


def test_policy_engine_risk_tier_enforcement():
    policy = PolicyEngine(max_risk_tier="medium")
    high_backend = Backend(name="risky-untrusted", capabilities={"technical_reasoning"}, risk_tier="high")
    persona = PersonaProfile(persona_id="P1", role="Worker", mission="test")
    task = TaskNode(id="T1", title="Test")

    assert not policy.allows(high_backend, persona, task)


def test_agent_router_selection():
    reg = BackendRegistry()
    reg.register(Backend(name="cheap-coder", capabilities={"code_analysis"}, cost_per_call=0.005, priority=1))
    reg.register(Backend(name="pro-architect", capabilities={"code_analysis", "system_design"}, cost_per_call=0.03, priority=2))
    
    router = AgentRouter(registry=reg)

    # 1. Simple task requiring only code_analysis
    p1 = PersonaProfile(persona_id="P1", role="Coder", mission="Code", required_capabilities=["code_analysis"])
    t1 = TaskNode(id="T1", title="Code")
    plan1 = router.dispatch(t1, p1)
    assert plan1.backend.name == "cheap-coder"

    # 2. Complex task requiring system_design
    p2 = PersonaProfile(persona_id="P2", role="Architect", mission="Design", required_capabilities=["system_design"])
    t2 = TaskNode(id="T2", title="Design")
    plan2 = router.dispatch(t2, p2)
    assert plan2.backend.name == "pro-architect"


def test_agent_router_blocked_when_no_backend_qualifies():
    reg = BackendRegistry()
    reg.register(Backend(name="cheap-coder", capabilities={"code_analysis"}))
    router = AgentRouter(registry=reg)

    p = PersonaProfile(persona_id="P1", role="Quantum Specialist", mission="Quantum computation", required_capabilities=["quantum_compilation"])
    t = TaskNode(id="T1", title="Quantum job")

    with pytest.raises(RoutingBlockedError) as exc_info:
        router.dispatch(t, p)
    assert "quantum_compilation" in str(exc_info.value)


def test_agent_router_escalates_on_prior_failures():
    reg = BackendRegistry()
    reg.register(Backend(name="tier1-worker", capabilities={"code_analysis"}, cost_per_call=0.01, priority=1))
    reg.register(Backend(name="tier2-expert", capabilities={"code_analysis"}, cost_per_call=0.05, priority=3))
    router = AgentRouter(registry=reg)

    p = PersonaProfile(persona_id="P1", role="Worker", mission="Work", required_capabilities=["code_analysis"])
    
    # Fresh task -> chooses cheapest
    t_fresh = TaskNode(id="T1", title="Work", revisions=0)
    assert router.dispatch(t_fresh, p).backend.name == "tier1-worker"

    # Task with prior failures -> escalates to stronger priority backend
    t_failed = TaskNode(id="T1", title="Work", revisions=1)
    assert router.dispatch(t_failed, p).backend.name == "tier2-expert"


def test_failure_classifier():
    classifier = FailureClassifier()
    assert classifier.classify(error_message="Permission denied: unapproved command") == FailureKind.MISSING_PERMISSION
    assert classifier.classify(error_message="Missing dependency N1 not found") == FailureKind.MISSING_DEPENDENCY
    assert classifier.classify(error_message="Reasoning limit reached, task too complex for model") == FailureKind.CAPABILITY_MISMATCH
    assert classifier.classify(error_message="Invariant violated: race condition in invalidation") == FailureKind.WRONG_APPROACH
    assert classifier.classify(error_message="AssertionError: expected 5 got 3") == FailureKind.INCOMPLETE_WORK


def test_persona_switcher_bounded_adaptation():
    switcher = PersonaSwitcher(max_persona_switches=2)
    task = TaskNode(id="T1", title="Solve Problem")
    p = PersonaProfile(
        persona_id="P-T1-v1",
        role="Developer",
        mission="Solve Problem",
        required_capabilities=["technical_reasoning"],
        method=["naive search"],
    )

    # Incomplete work does not trigger persona switch
    p_inc, switched_inc = switcher.adapt(task, p, FailureKind.INCOMPLETE_WORK, feedback="syntax error")
    assert not switched_inc
    assert p_inc.persona_id == "P-T1-v1"
    assert task.persona_switches == 0

    # Wrong approach triggers method adaptation
    p_wa, switched_wa = switcher.adapt(task, p, FailureKind.WRONG_APPROACH, feedback="deadlock in loop")
    assert switched_wa
    assert p_wa.persona_id == "P-T1-v2"
    assert task.persona_switches == 1
    assert any("ADAPTED METHOD" in m for m in p_wa.method)

    # Capability mismatch triggers capability upgrade
    p_cap, switched_cap = switcher.adapt(task, p_wa, FailureKind.CAPABILITY_MISMATCH, feedback="needs deeper architecture")
    assert switched_cap
    assert p_cap.persona_id == "P-T1-v3"
    assert task.persona_switches == 2
    assert "system_design" in p_cap.required_capabilities or "security_auditing" in p_cap.required_capabilities

    # Switch budget reached (max=2) -> no further switches
    p_stop, switched_stop = switcher.adapt(task, p_cap, FailureKind.WRONG_APPROACH, feedback="another failure")
    assert not switched_stop
    assert p_stop.persona_id == "P-T1-v3"
    assert task.persona_switches == 2


def test_dafg_full_integration_with_compiler_router_and_switcher():
    compiler = PersonaCompiler()
    router = AgentRouter()
    classifier = FailureClassifier()
    switcher = PersonaSwitcher(max_persona_switches=2)

    ledger = GateLedger.parse("""
# Test Gates
- [ ] G_p1: Persona test gate
  CHECK: python -c "print('GATE_OK')"
  EXPECT: GATE_OK
  EVIDENCE: pending
""")
    engine = GateEngine(auto_approve=True)

    graph = DAFG(
        ledger=ledger,
        engine=engine,
        compiler=compiler,
        router=router,
        classifier=classifier,
        switcher=switcher,
    )

    node = TaskNode(
        id="T_P",
        title="Design distributed cache invalidation",
        role="Cache Specialist",
        assigned_gates=["G_p1"],
    )
    graph.add_node(node)

    executed_backends = []

    def mock_executor(n, ctx):
        executed_backends.append(n.backend_name)
        assert "persona" in ctx
        assert "authorized_tools" in ctx
        return AgentResponse(output="Cache design complete", status="COMPLETED")

    status = graph.run(executor_fn=mock_executor)

    assert status == "COMPLETED"
    assert node.status == NodeStatus.ACCEPTED
    assert node.persona is not None
    assert node.persona["persona_id"].startswith("P-T_P")
    assert node.backend_name in ("standard-developer", "expert-architect")
    assert len(executed_backends) == 1
