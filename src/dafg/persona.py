"""DAFG Persona Compiler, Capability-Aware Agent Router, and Bounded Persona Adaptation.

Provides structured persona compilation from task nodes, policy-checked
capability-aware routing to backend execution engines, and failure-classified
bounded persona adaptation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union


class FailureKind(str, Enum):
    """Classification of task attempt failure."""
    INCOMPLETE_WORK = "INCOMPLETE_WORK"
    WRONG_APPROACH = "WRONG_APPROACH"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    MISSING_PERMISSION = "MISSING_PERMISSION"


class PersonaArchetype(str, Enum):
    """Classification of persona archetypes for multi-perspective task execution."""
    EXPLORER = "explorer"      # Surveys codebase, maps dependencies, identifies risks
    WORKER = "worker"          # Implements code changes
    REVIEWER = "reviewer"      # Reviews correctness, standards compliance
    CHALLENGER = "challenger"  # Stress-tests with adversarial inputs, concurrency
    AUDITOR = "auditor"        # Forensic integrity audit with zero shared context


class RoutingBlockedError(Exception):
    """Raised when no registered backend satisfies capability, policy, or budget constraints."""
    pass


@dataclass
class PersonaProfile:
    """Structured execution profile for a specialized agent persona."""
    persona_id: str
    role: str
    mission: str
    expertise: List[str] = field(default_factory=list)
    method: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    requested_tools: List[str] = field(default_factory=list)
    output_schema: Optional[str] = None
    review_focus: List[str] = field(default_factory=list)
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PersonaProfile:
        return cls(**data)


class PersonaCompiler:
    """Compiles structured PersonaProfiles from task specifications and context."""

    def __init__(self, custom_compiler: Optional[Callable[..., PersonaProfile]] = None):
        self.custom_compiler = custom_compiler

    def compile(
        self,
        task: Any,
        context: Optional[Dict[str, Any]] = None,
        previous_feedback: Optional[str] = None,
        attempt: int = 1,
    ) -> PersonaProfile:
        if self.custom_compiler:
            return self.custom_compiler(task, context, previous_feedback, attempt)

        task_id = getattr(task, "id", "T1")
        title = getattr(task, "title", "Perform task")
        role_label = getattr(task, "role", "Specialist")
        assigned_gates = getattr(task, "assigned_gates", [])
        owns = getattr(task, "owns", [])

        # Extract word tokens for exact word-boundary matching
        tokens = set(re.findall(r"\b[a-z0-9_-]+\b", f"{title.lower()} {str(role_label).lower()} {' '.join(assigned_gates).lower()}"))

        def has_words(*targets: str) -> bool:
            return any(target in tokens for target in targets)

        expertise: List[str] = []
        capabilities: List[str] = ["technical_reasoning"]
        requested_tools: List[str] = ["repository_read"]
        review_focus: List[str] = ["edge cases", "interface consistency"]

        # Domain & capability heuristics (word-boundary matched)
        if has_words("distributed", "consistency", "invalidation", "invalidate", "sync", "synchronization", "state", "states"):
            expertise.extend(["distributed consistency", "cache invalidation", "state transitions"])
            capabilities.append("system_design")
            review_focus.extend(["invalidation races", "obsolete state acceptance"])

        if has_words("security", "auth", "authentication", "authorization", "approval", "permission", "permissions", "sandbox", "boundary", "boundaries"):
            expertise.extend(["access control", "cryptographic hashing", "privilege separation"])
            capabilities.append("security_auditing")
            review_focus.extend(["privilege escalation", "unauthorized execution"])

        if has_words("test", "testing", "tests", "verify", "verification", "verifying", "gate", "gates", "pytest", "check", "checks"):
            expertise.extend(["automated verification", "regression testing"])
            capabilities.append("code_analysis")
            requested_tools.append("test_runner")

        if has_words("code", "coding", "implement", "implementation", "build", "builder", "runtime", "engine"):
            expertise.append("software engineering")
            capabilities.append("code_analysis")
            requested_tools.extend(["file_write", "test_runner"])

        if has_words("schema", "schemas", "validation", "validate", "validating", "json", "parser", "parsing"):
            expertise.extend(["data validation", "type systems"])
            review_focus.append("malformed payload handling")

        if has_words("formal", "proof", "proofs", "prover", "invariant", "invariants", "math"):
            capabilities.append("formal_verification")
            review_focus.append("invariant violation")

        if not expertise:
            expertise = ["general software development"]

        # Deduplicate while preserving order
        capabilities = list(dict.fromkeys(capabilities))
        expertise = list(dict.fromkeys(expertise))
        requested_tools = list(dict.fromkeys(requested_tools))
        review_focus = list(dict.fromkeys(review_focus))

        method = [
            "Inspect task specification and declared file ownership boundaries",
            "Formulate concrete implementation invariants and error paths",
            "Implement solution adhering to standard library and minimal diff discipline",
            "Execute acceptance gate checks and verify against expected patterns",
        ]

        if previous_feedback:
            method.insert(0, f"Address previous feedback: {previous_feedback}")

        return PersonaProfile(
            persona_id=f"P-{task_id}-v{attempt}",
            role=role_label,
            mission=f"Execute task: {title}",
            expertise=expertise,
            method=method,
            required_capabilities=capabilities,
            requested_tools=requested_tools,
            review_focus=review_focus,
            version=attempt,
            metadata={"assigned_gates": assigned_gates, "owns": owns},
        )

    # -- Archetype factory methods -------------------------------------------

    def compile_explorer(
        self,
        task: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> PersonaProfile:
        """Compile an explorer persona that surveys codebase and maps dependencies.

        The explorer focuses on discovery: scanning owned files, mapping the
        dependency graph, and identifying risk areas before implementation begins.
        """
        task_id = getattr(task, "id", "T1")
        title = getattr(task, "title", "Perform task")
        owns = getattr(task, "owns", [])
        assigned_gates = getattr(task, "assigned_gates", [])

        return PersonaProfile(
            persona_id=f"P-{task_id}-{PersonaArchetype.EXPLORER.value}-v1",
            role="Explorer",
            mission=f"Survey and map dependencies for task: {title}",
            expertise=["dependency analysis", "codebase navigation", "risk assessment"],
            method=[
                "Survey owned files and their imports",
                "Map dependency graph",
                "Identify risk areas and missing coverage",
            ],
            required_capabilities=["technical_reasoning"],
            requested_tools=["repository_read"],
            review_focus=[
                "missing dependencies",
                "architectural boundaries",
                "hidden coupling",
            ],
            version=1,
            metadata={
                "archetype": PersonaArchetype.EXPLORER.value,
                "assigned_gates": assigned_gates,
                "owns": owns,
            },
        )

    def compile_worker(
        self,
        task: Any,
        context: Optional[Dict[str, Any]] = None,
        previous_feedback: Optional[str] = None,
        attempt: int = 1,
    ) -> PersonaProfile:
        """Compile a worker persona for implementation.

        Delegates to the existing ``compile()`` method which already generates
        worker-style profiles, augmenting metadata with the archetype tag.
        """
        profile = self.compile(
            task,
            context=context,
            previous_feedback=previous_feedback,
            attempt=attempt,
        )
        profile.metadata["archetype"] = PersonaArchetype.WORKER.value
        profile.persona_id = f"P-{getattr(task, 'id', 'T1')}-{PersonaArchetype.WORKER.value}-v{attempt}"
        return profile

    def compile_reviewer(
        self,
        task: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> PersonaProfile:
        """Compile a reviewer persona focused on correctness and standards.

        The reviewer reads implementation against specification, traces error
        paths, and verifies interface contracts.
        """
        task_id = getattr(task, "id", "T1")
        title = getattr(task, "title", "Perform task")
        owns = getattr(task, "owns", [])
        assigned_gates = getattr(task, "assigned_gates", [])

        return PersonaProfile(
            persona_id=f"P-{task_id}-{PersonaArchetype.REVIEWER.value}-v1",
            role="Reviewer",
            mission=f"Review correctness and standards for task: {title}",
            expertise=["code review", "correctness analysis"],
            method=[
                "Read implementation against specification",
                "Trace error paths",
                "Verify interface contracts",
            ],
            required_capabilities=["technical_reasoning", "code_analysis"],
            requested_tools=["repository_read"],
            review_focus=[
                "off-by-one errors",
                "error handling gaps",
                "API contract violations",
                "missing edge cases",
            ],
            version=1,
            metadata={
                "archetype": PersonaArchetype.REVIEWER.value,
                "assigned_gates": assigned_gates,
                "owns": owns,
            },
        )

    def compile_challenger(
        self,
        task: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> PersonaProfile:
        """Compile a challenger persona for adversarial stress testing.

        The challenger designs adversarial test scenarios, stress tests with
        concurrent load, and injects faults to verify recovery.
        """
        task_id = getattr(task, "id", "T1")
        title = getattr(task, "title", "Perform task")
        owns = getattr(task, "owns", [])
        assigned_gates = getattr(task, "assigned_gates", [])

        return PersonaProfile(
            persona_id=f"P-{task_id}-{PersonaArchetype.CHALLENGER.value}-v1",
            role="Challenger",
            mission=f"Adversarial stress testing for task: {title}",
            expertise=["adversarial testing", "concurrency analysis"],
            method=[
                "Design adversarial test scenarios",
                "Stress test with concurrent load",
                "Inject faults and verify recovery",
            ],
            required_capabilities=["technical_reasoning", "code_analysis"],
            requested_tools=["repository_read", "test_runner"],
            review_focus=[
                "concurrency races",
                "resource exhaustion",
                "boundary inputs",
                "error injection",
            ],
            version=1,
            metadata={
                "archetype": PersonaArchetype.CHALLENGER.value,
                "assigned_gates": assigned_gates,
                "owns": owns,
            },
        )

    def compile_auditor(
        self,
        task: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> PersonaProfile:
        """Compile an auditor persona for forensic integrity audit.

        The auditor operates with zero shared context, independently runs all
        verification commands, and cross-references evidence with source to
        detect fabricated or stub artifacts.
        """
        task_id = getattr(task, "id", "T1")
        title = getattr(task, "title", "Perform task")
        owns = getattr(task, "owns", [])
        assigned_gates = getattr(task, "assigned_gates", [])

        return PersonaProfile(
            persona_id=f"P-{task_id}-{PersonaArchetype.AUDITOR.value}-v1",
            role="Auditor",
            mission=f"Forensic integrity audit for task: {title}",
            expertise=["forensic auditing", "evidence verification"],
            method=[
                "Independently run all verification commands",
                "Cross-reference evidence with source",
                "Verify no fabricated or stub artifacts",
            ],
            required_capabilities=["technical_reasoning", "code_analysis"],
            requested_tools=["repository_read", "test_runner"],
            review_focus=[
                "test adequacy",
                "evidence authenticity",
                "gate coverage gaps",
            ],
            version=1,
            metadata={
                "archetype": PersonaArchetype.AUDITOR.value,
                "assigned_gates": assigned_gates,
                "owns": owns,
            },
        )

    # -- Archetype dispatch --------------------------------------------------

    def compile_for_archetype(
        self,
        archetype: PersonaArchetype,
        task: Any,
        context: Optional[Dict[str, Any]] = None,
        previous_feedback: Optional[str] = None,
        attempt: int = 1,
    ) -> PersonaProfile:
        """Dispatch to the correct archetype factory method.

        Args:
            archetype: The persona archetype to compile.
            task: Task specification object.
            context: Optional context dict.
            previous_feedback: Feedback from previous attempt (worker only).
            attempt: Attempt number (worker only).

        Returns:
            A PersonaProfile configured for the requested archetype.

        Raises:
            ValueError: If the archetype is not recognized.
        """
        dispatch = {
            PersonaArchetype.EXPLORER: lambda: self.compile_explorer(task, context=context),
            PersonaArchetype.WORKER: lambda: self.compile_worker(
                task, context=context, previous_feedback=previous_feedback, attempt=attempt,
            ),
            PersonaArchetype.REVIEWER: lambda: self.compile_reviewer(task, context=context),
            PersonaArchetype.CHALLENGER: lambda: self.compile_challenger(task, context=context),
            PersonaArchetype.AUDITOR: lambda: self.compile_auditor(task, context=context),
        }
        factory = dispatch.get(archetype)
        if factory is None:
            raise ValueError(f"Unknown archetype: {archetype!r}")
        return factory()


@dataclass
class Backend:
    """Model or worker backend with explicit capability and risk declarations."""
    name: str
    capabilities: Set[str] = field(default_factory=set)
    cost_per_call: float = 0.01
    risk_tier: str = "medium"  # "low", "medium", "high"
    max_context: int = 128000
    priority: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def supports(self, required_capabilities: Iterable[str]) -> bool:
        return all(cap in self.capabilities for cap in required_capabilities)


class BackendRegistry:
    """Registry of available agent and model execution backends."""

    def __init__(self):
        self._backends: Dict[str, Backend] = {}

    def register(self, backend: Backend) -> None:
        self._backends[backend.name] = backend

    def get(self, name: str) -> Optional[Backend]:
        return self._backends.get(name)

    def list_backends(self) -> List[Backend]:
        return list(self._backends.values())

    @classmethod
    def default_registry(cls) -> BackendRegistry:
        reg = cls()
        reg.register(Backend(
            name="fast-worker",
            capabilities={"fast_generation", "code_analysis"},
            cost_per_call=0.002,
            risk_tier="low",
            priority=1,
        ))
        reg.register(Backend(
            name="standard-developer",
            capabilities={"technical_reasoning", "code_analysis", "tool_execution"},
            cost_per_call=0.01,
            risk_tier="medium",
            priority=2,
        ))
        reg.register(Backend(
            name="expert-architect",
            capabilities={"technical_reasoning", "code_analysis", "system_design", "security_auditing", "tool_execution"},
            cost_per_call=0.03,
            risk_tier="high",
            priority=3,
        ))
        reg.register(Backend(
            name="formal-verifier",
            capabilities={"technical_reasoning", "formal_verification", "system_design", "security_auditing", "code_analysis", "tool_execution"},
            cost_per_call=0.05,
            risk_tier="high",
            priority=4,
        ))
        return reg


@dataclass
class PolicyEngine:
    """Validates execution permissions and enforces tool authorization boundaries."""
    allowed_tools: Set[str] = field(default_factory=lambda: {"repository_read", "file_write", "test_runner"})
    max_risk_tier: str = "high"
    allowed_backends: Optional[Set[str]] = None
    denied_backends: Set[str] = field(default_factory=set)

    def allows(self, backend: Backend, persona: PersonaProfile, task: Any) -> bool:
        if backend.name in self.denied_backends:
            return False
        if self.allowed_backends is not None and backend.name not in self.allowed_backends:
            return False

        tier_rank = {"low": 1, "medium": 2, "high": 3}
        backend_rank = tier_rank.get(backend.risk_tier, 2)
        policy_max_rank = tier_rank.get(self.max_risk_tier, 3)
        if backend_rank > policy_max_rank:
            return False

        task_risk = getattr(task, "metadata", {}).get("risk", "medium")
        task_rank = tier_rank.get(task_risk, 2)
        # Backend must be rated at least as high as task risk
        if backend_rank < task_rank:
            return False

        return True

    def authorize(self, requested_tools: Iterable[str], task: Any) -> List[str]:
        """Personas may request tools; policy strictly authorizes them."""
        task_allowed = getattr(task, "metadata", {}).get("allowed_tools", None)
        authorized = []
        for tool in requested_tools:
            if tool not in self.allowed_tools:
                continue
            if task_allowed is not None and tool not in task_allowed:
                continue
            authorized.append(tool)
        return authorized


@dataclass
class DispatchPlan:
    """Resolved dispatch configuration for task execution."""
    backend: Backend
    persona: PersonaProfile
    authorized_tools: List[str]
    scoped_context: Dict[str, Any]


class AgentRouter:
    """Selects execution configuration from registered backends based on capabilities, policy, and budget."""

    def __init__(
        self,
        registry: Optional[BackendRegistry] = None,
        policy: Optional[PolicyEngine] = None,
    ):
        self.registry = registry or BackendRegistry.default_registry()
        self.policy = policy or PolicyEngine()

    def find_eligible(
        self,
        persona: PersonaProfile,
        task: Any,
        budget: Optional[Any] = None,
    ) -> List[Backend]:
        eligible: List[Backend] = []
        for backend in self.registry.list_backends():
            if not backend.supports(persona.required_capabilities):
                continue
            if not self.policy.allows(backend, persona, task):
                continue
            # Budget verification if applicable
            if budget is not None and hasattr(budget, "can_afford"):
                if not budget.can_afford(backend):
                    continue
            eligible.append(backend)
        return eligible

    def select_backend(
        self,
        eligible: List[Backend],
        task_risk: str = "medium",
        prior_failures: int = 0,
    ) -> Backend:
        if not eligible:
            raise RoutingBlockedError("No registered backend qualifies for required capabilities and policy.")

        # When prior attempts failed, prefer higher priority (stronger) backends
        if prior_failures > 0:
            return max(eligible, key=lambda b: (b.priority, b.cost_per_call))
        # Otherwise, pick most cost-effective eligible backend that matches priority
        return min(eligible, key=lambda b: (b.cost_per_call, -b.priority))

    def dispatch(
        self,
        task: Any,
        persona: PersonaProfile,
        context: Optional[Dict[str, Any]] = None,
        budget: Optional[Any] = None,
    ) -> DispatchPlan:
        eligible = self.find_eligible(persona, task, budget=budget)
        if not eligible:
            missing_caps = persona.required_capabilities
            raise RoutingBlockedError(
                f"Routing blocked: No backend supports required capabilities {missing_caps} under active policy."
            )

        task_risk = getattr(task, "metadata", {}).get("risk", "medium")
        prior_failures = getattr(task, "revisions", 0)
        selected_backend = self.select_backend(eligible, task_risk=task_risk, prior_failures=prior_failures)

        authorized_tools = self.policy.authorize(persona.requested_tools, task)

        # Build scoped context
        scoped = dict(context or {})
        scoped["persona"] = persona.to_dict()
        scoped["backend"] = selected_backend.name
        scoped["authorized_tools"] = authorized_tools
        scoped["task_id"] = getattr(task, "id", "")
        scoped["owns"] = getattr(task, "owns", [])

        return DispatchPlan(
            backend=selected_backend,
            persona=persona,
            authorized_tools=authorized_tools,
            scoped_context=scoped,
        )


class FailureClassifier:
    """Classifies task failure causes to guide bounded persona adaptation."""

    @staticmethod
    def classify(
        error_message: str = "",
        feedback: str = "",
        gate_failures: Optional[List[str]] = None,
    ) -> FailureKind:
        text = f"{error_message} {feedback} {' '.join(gate_failures or [])}".lower()

        if any(term in text for term in ("unapproved", "permission", "not allowed", "forbidden", "unauthorized")):
            return FailureKind.MISSING_PERMISSION

        if any(term in text for term in ("dependency", "prerequisite", "missing dep", "unresolved reference", "not found")):
            return FailureKind.MISSING_DEPENDENCY

        if any(term in text for term in ("capability mismatch", "reasoning limit", "unsupported capability", "hallucinated", "too complex for model")):
            return FailureKind.CAPABILITY_MISMATCH

        if any(term in text for term in ("wrong approach", "flawed architecture", "race condition", "deadlock", "invariant violated", "redesign required")):
            return FailureKind.WRONG_APPROACH

        # Default fallback is incomplete work (syntax error, failed test assertions, timeouts)
        return FailureKind.INCOMPLETE_WORK


class PersonaSwitcher:
    """Manages bounded persona and capability adaptation upon task failures."""

    def __init__(self, max_persona_switches: int = 2):
        self.max_persona_switches = max_persona_switches

    def adapt(
        self,
        task: Any,
        persona: PersonaProfile,
        failure: FailureKind,
        feedback: str = "",
    ) -> Tuple[PersonaProfile, bool]:
        """Adapt persona based on failure classification.
        
        Returns (adapted_persona, switched_flag).
        """
        switches_count = getattr(task, "persona_switches", 0)

        # 1. Incomplete work -> retain persona, provide feedback
        if failure == FailureKind.INCOMPLETE_WORK:
            return persona, False

        # 2. Missing dependency or permission -> handled externally, retain persona
        if failure in (FailureKind.MISSING_DEPENDENCY, FailureKind.MISSING_PERMISSION):
            return persona, False

        # Check switch budget
        if switches_count >= self.max_persona_switches:
            return persona, False

        new_version = persona.version + 1
        task_id = getattr(task, "id", "T1")
        new_persona_id = f"P-{task_id}-v{new_version}"

        # 3. Wrong approach -> regenerate method and adjust focus
        if failure == FailureKind.WRONG_APPROACH:
            new_method = [
                f"ADAPTED METHOD: Overcome previous approach failure: {feedback}",
                "Deconstruct failure mode and prove counter-invariants",
                *persona.method,
            ]
            new_profile = PersonaProfile(
                persona_id=new_persona_id,
                role=persona.role,
                mission=persona.mission,
                expertise=list(persona.expertise),
                method=new_method,
                required_capabilities=list(persona.required_capabilities),
                requested_tools=list(persona.requested_tools),
                output_schema=persona.output_schema,
                review_focus=["failure regression", *persona.review_focus],
                version=new_version,
                metadata=dict(persona.metadata),
            )
            setattr(task, "persona_switches", switches_count + 1)
            return new_profile, True

        # 4. Capability mismatch -> escalate required capabilities
        if failure == FailureKind.CAPABILITY_MISMATCH:
            new_caps = list(persona.required_capabilities)
            for upgrade in ("system_design", "security_auditing", "formal_verification"):
                if upgrade not in new_caps:
                    new_caps.append(upgrade)
                    break
            new_profile = PersonaProfile(
                persona_id=new_persona_id,
                role=f"Senior {persona.role}",
                mission=persona.mission,
                expertise=["advanced systems engineering", *persona.expertise],
                method=["Apply rigorous formal proofs and architectural isolation", *persona.method],
                required_capabilities=new_caps,
                requested_tools=list(persona.requested_tools),
                output_schema=persona.output_schema,
                review_focus=persona.review_focus,
                version=new_version,
                metadata=dict(persona.metadata),
            )
            setattr(task, "persona_switches", switches_count + 1)
            return new_profile, True

        return persona, False


class ArchetypeDeriver:
    """Derives default persona archetypes from gate ledger signals.

    Analyzes a ``GateLedger`` (from ``dafg.gates``) and returns the list
    of archetypes that should be activated for a given execution run.

    The ledger is typed as ``Any`` to avoid circular imports with the
    ``dafg.gates`` module.  At runtime it must be a ``GateLedger`` instance
    with ``.gates`` (dict of gate_id -> Gate), ``.mode`` (str), and
    ``.abandon_threshold`` (float or None).
    """

    @staticmethod
    def from_ledger(ledger: Any) -> List[Tuple[PersonaArchetype, Dict[str, Any]]]:
        """Analyze a GateLedger and derive which archetypes should be activated.

        Args:
            ledger: A ``dafg.gates.GateLedger`` instance.  Must expose
                ``gates`` (dict mapping gate_id to Gate objects),
                ``mode`` (one of ``'quick'``, ``'standard'``, ``'strict'``),
                and ``abandon_threshold`` (float or ``None``).

        Returns:
            A list of ``(PersonaArchetype, context_dict)`` tuples.
            ``context_dict`` contains ``gate_ids`` — the gate IDs that
            motivated inclusion of that archetype.
        """
        gates: Dict[str, Any] = getattr(ledger, "gates", {})
        mode: str = getattr(ledger, "mode", "standard")
        abandon_threshold = getattr(ledger, "abandon_threshold", None)

        result: List[Tuple[PersonaArchetype, Dict[str, Any]]] = []
        seen: set = set()

        def _add(archetype: PersonaArchetype, gate_ids: List[str]) -> None:
            if archetype not in seen:
                seen.add(archetype)
                result.append((archetype, {"gate_ids": list(gate_ids)}))

        # Always include WORKER and REVIEWER
        _add(PersonaArchetype.WORKER, list(gates.keys()))
        _add(PersonaArchetype.REVIEWER, list(gates.keys()))

        explorer_gates: List[str] = []
        challenger_gates: List[str] = []
        auditor_gates: List[str] = []

        for gate_id, gate in gates.items():
            # EXPLORER: any gate that owns files needs dependency survey
            owns = getattr(gate, "owns", None)
            if owns:
                explorer_gates.append(gate_id)

            # CHALLENGER: any gate with test/pytest in its check command
            check = getattr(gate, "check", None) or ""
            check_lower = check.lower()
            if "pytest" in check_lower or "test" in check_lower:
                challenger_gates.append(gate_id)

            # AUDITOR: self-authored gates need independent audit
            author = getattr(gate, "author", None) or ""
            if author.strip().lower() == "implementer":
                auditor_gates.append(gate_id)

        if explorer_gates:
            _add(PersonaArchetype.EXPLORER, explorer_gates)

        if challenger_gates:
            _add(PersonaArchetype.CHALLENGER, challenger_gates)

        # AUDITOR: strict mode requires forensic audit
        if mode == "strict":
            _add(PersonaArchetype.AUDITOR, list(gates.keys()))

        # AUDITOR: self-authored gates detected above
        if auditor_gates:
            _add(PersonaArchetype.AUDITOR, auditor_gates)

        # AUDITOR: governance monitoring when abandon_threshold is set
        if abandon_threshold is not None:
            _add(PersonaArchetype.AUDITOR, list(gates.keys()))

        return result
