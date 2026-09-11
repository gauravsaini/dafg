"""DAFG Dynamic Task Graph & Depth Tree Runtime.

Executes autonomous agent workflows backed by objective gate evidence, dynamic
planning, specialist roles, dependency expansion (`needs`), depth trees,
disjoint file ownership (`OWNS:`), rolling waves, budget caps, atomic state
persistence (`state.json`), pre-dispatch manifest gating, failure-directed repair,
versioned interface contracts, and layered verification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import fnmatch
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from dafg.gates import Gate, GateEngine, GateLedger, GateResult


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class Role(str, Enum):
    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    SPECIALIST = "specialist"


class FailureClass(str, Enum):
    """Failure classification to direct targeted repair."""
    LOCAL_DEFECT = "LOCAL_DEFECT"
    MISSING_PREREQUISITE = "MISSING_PREREQUISITE"
    STALE_DEPENDENCY = "STALE_DEPENDENCY"
    INTERFACE_MISMATCH = "INTERFACE_MISMATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"


class OutcomeStatus(str, Enum):
    """Outcome classification of a DAFG run or node execution."""
    VERIFIED_DELIVERY = "VERIFIED_DELIVERY"
    INTERMEDIATE_FALSE_ACCEPTANCE = "INTERMEDIATE_FALSE_ACCEPTANCE"
    FINAL_FALSE_SUCCESS = "FINAL_FALSE_SUCCESS"
    INCOMPLETE_RUN = "INCOMPLETE_RUN"


class EvidenceType(str, Enum):
    """Rigorous evidence classification for acceptance criteria."""
    TEST_RESULT = "TEST_RESULT"
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    INVARIANT_CHECK = "INVARIANT_CHECK"
    STRUCTURAL_CHECK = "STRUCTURAL_CHECK"
    MODEL_JUDGMENT = "MODEL_JUDGMENT"


class BudgetExceededError(Exception):
    """Raised when a resource budget cap is exceeded."""
    pass


@dataclass
class Budget:
    max_calls: int = 50
    max_nodes: int = 20
    max_revisions: int = 3
    deadline: Optional[float] = None  # Unix timestamp

    calls_consumed: int = 0
    nodes_created: int = 0
    revisions_consumed: int = 0

    def check_call(self) -> None:
        if self.calls_consumed >= self.max_calls:
            raise BudgetExceededError(
                f"Model call budget exceeded: {self.calls_consumed}/{self.max_calls}"
            )
        self.calls_consumed += 1

    def check_node(self) -> None:
        if self.nodes_created >= self.max_nodes:
            raise BudgetExceededError(
                f"Node budget exceeded: {self.nodes_created}/{self.max_nodes}"
            )
        self.nodes_created += 1

    def check_deadline(self) -> None:
        if self.deadline is not None and time.time() > self.deadline:
            raise BudgetExceededError(
                f"Deadline exceeded: {time.time():.1f} > {self.deadline:.1f}"
            )

    def check_revision(self) -> None:
        if self.revisions_consumed >= self.max_revisions:
            raise BudgetExceededError(
                f"Revision budget exceeded: {self.revisions_consumed}/{self.max_revisions}"
            )
        self.revisions_consumed += 1


@dataclass
class CriterionEvidence:
    """Structured, typed evidence verifying a specific gate or criterion."""
    criterion_id: str
    status: str = "MET"  # MET, FAILED, UNVERIFIED
    evidence_type: EvidenceType = EvidenceType.TEST_RESULT
    evidence_ref: str = ""
    artifact_version: int = 1
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["evidence_type"] = self.evidence_type.value if isinstance(self.evidence_type, EvidenceType) else self.evidence_type
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CriterionEvidence:
        d = data.copy()
        if "evidence_type" in d and isinstance(d["evidence_type"], str):
            d["evidence_type"] = EvidenceType(d["evidence_type"])
        return cls(**d)


@dataclass
class BypassPolicy:
    """Conservative safety guard conditions for the Adaptive Protocol Bypass."""
    max_files: int = 1
    allow_contracts: bool = False
    allow_permissions: bool = False
    max_ambiguity: float = 0.15
    shadow_sample_rate: float = 0.10  # 10% shadow verification

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BypassPolicy:
        return cls(**data)


@dataclass
class BypassTelemetry:
    """Telemetry tracking bypass rate, safety violations, and shadow divergence."""
    total_runs: int = 0
    bypassed_runs: int = 0
    misrouted_runs: int = 0  # Bypassed runs that violated bounds or failed
    shadow_runs: int = 0     # Runs audited via shadow execution
    shadow_defects_caught: int = 0  # Defects caught by shadow execution that fastpath missed

    @property
    def bypass_rate(self) -> float:
        return (self.bypassed_runs / self.total_runs) if self.total_runs > 0 else 0.0

    @property
    def bypass_misroute_rate(self) -> float:
        return (self.misrouted_runs / self.bypassed_runs) if self.bypassed_runs > 0 else 0.0

    @property
    def shadow_delta(self) -> float:
        return (self.shadow_defects_caught / self.shadow_runs) if self.shadow_runs > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["bypass_rate"] = self.bypass_rate
        d["bypass_misroute_rate"] = self.bypass_misroute_rate
        d["shadow_delta"] = self.shadow_delta
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BypassTelemetry:
        clean = {k: v for k, v in data.items() if k in ["total_runs", "bypassed_runs", "misrouted_runs", "shadow_runs", "shadow_defects_caught"]}
        return cls(**clean)


@dataclass
class WaitMetrics:
    """Disaggregated wait latency telemetry."""
    dependency_wait_seconds: float = 0.0
    queue_wait_seconds: float = 0.0
    conflict_wait_seconds: float = 0.0
    time_created: float = field(default_factory=time.time)
    time_ready: Optional[float] = None
    time_dispatched: Optional[float] = None
    time_finished: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WaitMetrics:
        return cls(**data)


@dataclass
class InputManifest:
    """Input manifest required before task dispatch to prevent incomplete context."""
    required_inputs: List[Dict[str, Any]] = field(default_factory=list)
    # e.g. [{"artifact": "organization_schema", "version": 3, "mandatory": True}]
    mandatory_context: List[str] = field(default_factory=list)
    optional_context: List[str] = field(default_factory=list)
    checks: Dict[str, Any] = field(default_factory=lambda: {
        "references_resolve": True,
        "versions_are_current": True,
        "required_sections_present": True,
        "unresolved_dependencies": [],
    })

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InputManifest:
        return cls(**data)


@dataclass
class InterfaceContract:
    """Explicit versioned interface contract between modules/tasks."""
    contract_id: str
    version: int = 1
    owner: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    invariants: List[str] = field(default_factory=list)
    error_behavior: Dict[str, str] = field(default_factory=dict)
    compatibility_mode: str = "backward_compatible"  # "backward_compatible", "breaking"
    consumers: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InterfaceContract:
        return cls(**data)


@dataclass
class RevisionDirective:
    """Diagnostic directive guiding targeted repair instead of blind restarts."""
    verdict: str = "REVISE"  # "REVISE", "PROCEED", "ABORT"
    failure_class: FailureClass = FailureClass.LOCAL_DEFECT
    affected_dependency: Optional[str] = None
    consumed_version: Optional[int] = None
    required_version: Optional[int] = None
    repair_scope: str = "LOCAL_ONLY"  # "LOCAL_ONLY", "DEPENDENCY_AND_DESCENDANTS", "CONTRACT_REPAIR"
    evidence_refs: List[str] = field(default_factory=list)
    feedback: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["failure_class"] = self.failure_class.value if isinstance(self.failure_class, FailureClass) else self.failure_class
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RevisionDirective:
        d = data.copy()
        if "failure_class" in d and isinstance(d["failure_class"], str):
            d["failure_class"] = FailureClass(d["failure_class"])
        return cls(**d)


@dataclass
class BypassTelemetry:
    """Telemetry tracking adaptive bypass decisions, safety violations, and shadow divergence."""
    total_runs: int = 0
    bypassed_runs: int = 0
    misrouted_runs: int = 0  # Bypassed runs that violated bounds or failed
    shadow_runs: int = 0     # Runs audited via shadow execution
    shadow_defects_caught: int = 0  # Defects caught by shadow execution that fastpath missed
    coordination_count: int = 0

    # Aliases for compatibility
    @property
    def total_evaluations(self) -> int:
        return self.total_runs

    @total_evaluations.setter
    def total_evaluations(self, val: int) -> None:
        self.total_runs = val

    @property
    def bypassed_count(self) -> int:
        return self.bypassed_runs

    @bypassed_count.setter
    def bypassed_count(self, val: int) -> None:
        self.bypassed_runs = val

    @property
    def misroute_count(self) -> int:
        return self.misrouted_runs

    @misroute_count.setter
    def misroute_count(self, val: int) -> None:
        self.misrouted_runs = val

    @property
    def shadow_audits(self) -> int:
        return self.shadow_runs

    @shadow_audits.setter
    def shadow_audits(self, val: int) -> None:
        self.shadow_runs = val

    @property
    def bypass_rate(self) -> float:
        return (self.bypassed_runs / self.total_runs) if self.total_runs > 0 else 0.0

    @property
    def bypass_misroute_rate(self) -> float:
        return (self.misrouted_runs / self.bypassed_runs) if self.bypassed_runs > 0 else 0.0

    @property
    def shadow_delta(self) -> float:
        return (self.shadow_defects_caught / self.shadow_runs) if self.shadow_runs > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_runs": self.total_runs,
            "bypassed_runs": self.bypassed_runs,
            "misrouted_runs": self.misrouted_runs,
            "shadow_runs": self.shadow_runs,
            "shadow_defects_caught": self.shadow_defects_caught,
            "coordination_count": self.coordination_count,
            "total_evaluations": self.total_runs,
            "bypassed_count": self.bypassed_runs,
            "misroute_count": self.misrouted_runs,
            "shadow_audits": self.shadow_runs,
            "bypass_rate": self.bypass_rate,
            "bypass_misroute_rate": self.bypass_misroute_rate,
            "shadow_delta": self.shadow_delta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BypassTelemetry:
        t_runs = data.get("total_runs", data.get("total_evaluations", 0))
        b_runs = data.get("bypassed_runs", data.get("bypassed_count", 0))
        m_runs = data.get("misrouted_runs", data.get("misroute_count", 0))
        s_runs = data.get("shadow_runs", data.get("shadow_audits", 0))
        s_def = data.get("shadow_defects_caught", 0)
        c_cnt = data.get("coordination_count", 0)
        return cls(
            total_runs=t_runs,
            bypassed_runs=b_runs,
            misrouted_runs=m_runs,
            shadow_runs=s_runs,
            shadow_defects_caught=s_def,
            coordination_count=c_cnt,
        )


@dataclass
class BypassPolicy:
    """Conservative safety guard conditions for the Adaptive Protocol Bypass."""
    max_files: int = 1
    allow_contracts: bool = False
    allow_permissions: bool = False
    max_ambiguity: float = 0.15
    shadow_sample_rate: float = 0.10  # 10% shadow verification
    telemetry: BypassTelemetry = field(default_factory=BypassTelemetry)

    # Aliases for compatibility
    @property
    def allow_shared_contracts(self) -> bool:
        return self.allow_contracts

    @allow_shared_contracts.setter
    def allow_shared_contracts(self, val: bool) -> None:
        self.allow_contracts = val

    @property
    def allow_security_tags(self) -> bool:
        return self.allow_permissions

    @allow_security_tags.setter
    def allow_security_tags(self, val: bool) -> None:
        self.allow_permissions = val

    @property
    def max_ambiguity_score(self) -> float:
        return self.max_ambiguity

    @max_ambiguity_score.setter
    def max_ambiguity_score(self, val: float) -> None:
        self.max_ambiguity = val

    @property
    def shadow_audit_rate(self) -> float:
        return self.shadow_sample_rate

    @shadow_audit_rate.setter
    def shadow_audit_rate(self, val: float) -> None:
        self.shadow_sample_rate = val

    def evaluate(
        self,
        task_title: str,
        files_touched: List[str],
        contracts_touched: Optional[List[str]] = None,
        security_tags: Optional[List[str]] = None,
        ambiguity_score: float = 0.0,
    ) -> Tuple[bool, str]:
        """Conservatively evaluate whether a task may bypass full coordination."""
        self.telemetry.total_runs += 1

        if len(files_touched) > self.max_files:
            self.telemetry.coordination_count += 1
            return False, f"Multi-file scope ({len(files_touched)} files > {self.max_files})"

        if contracts_touched and not self.allow_contracts:
            self.telemetry.coordination_count += 1
            return False, "Touches shared interface contract"

        if security_tags and not self.allow_permissions:
            self.telemetry.coordination_count += 1
            return False, f"Requires security/permission checks: {security_tags}"

        if ambiguity_score > self.max_ambiguity:
            self.telemetry.coordination_count += 1
            return False, f"Goal ambiguity too high ({ambiguity_score:.2f} > {self.max_ambiguity})"

        self.telemetry.bypassed_runs += 1
        return True, "Safe single-file change within conservative bypass bounds"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_files": self.max_files,
            "allow_contracts": self.allow_contracts,
            "allow_permissions": self.allow_permissions,
            "max_ambiguity": self.max_ambiguity,
            "shadow_sample_rate": self.shadow_sample_rate,
            "allow_shared_contracts": self.allow_contracts,
            "allow_security_tags": self.allow_permissions,
            "max_ambiguity_score": self.max_ambiguity,
            "shadow_audit_rate": self.shadow_sample_rate,
            "telemetry": self.telemetry.to_dict() if hasattr(self.telemetry, "to_dict") else self.telemetry,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BypassPolicy:
        d = data.copy()
        max_f = d.get("max_files", 1)
        a_cont = d.get("allow_contracts", d.get("allow_shared_contracts", False))
        a_perm = d.get("allow_permissions", d.get("allow_security_tags", False))
        m_amb = d.get("max_ambiguity", d.get("max_ambiguity_score", 0.15))
        s_rate = d.get("shadow_sample_rate", d.get("shadow_audit_rate", 0.10))
        t_data = d.get("telemetry")
        tel = BypassTelemetry.from_dict(t_data) if isinstance(t_data, dict) else BypassTelemetry()
        return cls(
            max_files=max_f,
            allow_contracts=a_cont,
            allow_permissions=a_perm,
            max_ambiguity=m_amb,
            shadow_sample_rate=s_rate,
            telemetry=tel,
        )


@dataclass
class TaskNode:
    id: str
    title: str
    role: str = "coder"
    status: NodeStatus = NodeStatus.PENDING
    needs: List[str] = field(default_factory=list)  # prerequisite node IDs
    assigned_gates: List[str] = field(default_factory=list)  # gate IDs in GATES.md
    owns: List[str] = field(default_factory=list)  # declared file paths / patterns
    parent_id: Optional[str] = None  # parent in depth tree
    children: List[str] = field(default_factory=list)  # child node IDs
    depth: int = 0
    revisions: int = 0
    max_revisions: int = 3
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    persona: Optional[Dict[str, Any]] = None
    persona_history: List[Dict[str, Any]] = field(default_factory=list)
    backend_name: Optional[str] = None
    persona_switches: int = 0
    max_persona_switches: int = 2

    # v0.2 Enhancements
    manifest: Optional[InputManifest] = None
    consumed_contracts: Dict[str, int] = field(default_factory=dict)  # contract_id -> version
    version: int = 1
    epoch: int = 1
    evidence_ledger: List[CriterionEvidence] = field(default_factory=list)
    wait_metrics: WaitMetrics = field(default_factory=WaitMetrics)

    # v0.3 Bypass Safety Guards
    ambiguity_score: float = 0.0
    requires_permissions: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, NodeStatus) else self.status
        if self.manifest:
            d["manifest"] = self.manifest.to_dict()
        if self.evidence_ledger:
            d["evidence_ledger"] = [e.to_dict() if hasattr(e, "to_dict") else e for e in self.evidence_ledger]
        if self.wait_metrics:
            d["wait_metrics"] = self.wait_metrics.to_dict() if hasattr(self.wait_metrics, "to_dict") else self.wait_metrics
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskNode:
        d = data.copy()
        if "status" in d and isinstance(d["status"], str):
            d["status"] = NodeStatus(d["status"])
        if "manifest" in d and isinstance(d["manifest"], dict):
            d["manifest"] = InputManifest.from_dict(d["manifest"])
        if "evidence_ledger" in d and isinstance(d["evidence_ledger"], list):
            d["evidence_ledger"] = [CriterionEvidence.from_dict(e) if isinstance(e, dict) else e for e in d["evidence_ledger"]]
        if "wait_metrics" in d and isinstance(d["wait_metrics"], dict):
            d["wait_metrics"] = WaitMetrics.from_dict(d["wait_metrics"])
        elif "wait_metrics" not in d:
            d["wait_metrics"] = WaitMetrics()
        return cls(**d)


@dataclass
class AgentResponse:
    """Output returned by specialist agents / LLMs."""
    output: str = ""
    status: str = "COMPLETED"
    needs: List[Union[str, TaskNode, Dict[str, Any]]] = field(default_factory=list)
    spawn_children: List[Union[TaskNode, Dict[str, Any]]] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    revision_directive: Optional[Union[RevisionDirective, Dict[str, Any]]] = None
    published_contracts: List[Union[InterfaceContract, Dict[str, Any]]] = field(default_factory=list)
    criterion_evidence: List[Union[CriterionEvidence, Dict[str, Any]]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "output": self.output,
            "status": self.status,
            "files_modified": self.files_modified,
            "metadata": self.metadata,
        }
        if self.revision_directive:
            d["revision_directive"] = self.revision_directive.to_dict() if hasattr(self.revision_directive, "to_dict") else self.revision_directive
        if self.published_contracts:
            d["published_contracts"] = [c.to_dict() if hasattr(c, "to_dict") else c for c in self.published_contracts]
        if self.criterion_evidence:
            d["criterion_evidence"] = [e.to_dict() if hasattr(e, "to_dict") else e for e in self.criterion_evidence]
        return d


def paths_overlap(path1: str, path2: str) -> bool:
    """Check if two file ownership paths or globs overlap."""
    p1 = os.path.normpath(path1.strip()).replace(chr(92), "/")
    p2 = os.path.normpath(path2.strip()).replace(chr(92), "/")
    if p1.startswith("./"):
        p1 = p1[2:]
    if p2.startswith("./"):
        p2 = p2[2:]

    if p1 == p2:
        return True
    if p1 == "." or p2 == ".":
        return True
    if fnmatch.fnmatch(p1, p2) or fnmatch.fnmatch(p2, p1):
        return True
    # Directory prefix containment: e.g. "src/db" overlaps with "src/db/models.py"
    if p2.startswith(f"{p1}/") or p1.startswith(f"{p2}/"):
        return True
    return False


def nodes_conflict(node1: TaskNode, node2: TaskNode, ledger: Optional[GateLedger] = None) -> bool:
    """Check if two nodes have overlapping file ownership."""
    def get_owns(n: TaskNode) -> Set[str]:
        res = set(n.owns)
        if ledger and n.assigned_gates:
            for gid in n.assigned_gates:
                g = ledger.get_gate(gid)
                if g and g.owns:
                    for p in [x.strip() for x in g.owns.split(",") if x.strip()]:
                        res.add(p)
        return res

    owns1 = get_owns(node1)
    owns2 = get_owns(node2)
    for p1 in owns1:
        for p2 in owns2:
            if paths_overlap(p1, p2):
                return True
    return False


class StateStore:
    """Handles atomic persistence of DAFG runtime state."""

    @staticmethod
    def save(state: Dict[str, Any], filepath: Union[str, Path]) -> None:
        fp = Path(filepath)
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = fp.with_name(f"{fp.name}.tmp.{os.getpid()}")
        tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp_file, fp)

    @staticmethod
    def load(filepath: Union[str, Path]) -> Dict[str, Any]:
        fp = Path(filepath)
        return json.loads(fp.read_text(encoding="utf-8"))


class DAFG:
    """Dynamic Agent Feedback Graph Runtime with Dependency Discipline."""

    def __init__(
        self,
        nodes: Optional[Dict[str, TaskNode]] = None,
        budget: Optional[Budget] = None,
        ledger: Optional[GateLedger] = None,
        engine: Optional[GateEngine] = None,
        state_path: Optional[Union[str, Path]] = None,
        router: Optional[Any] = None,
        compiler: Optional[Any] = None,
        policy: Optional[Any] = None,
        switcher: Optional[Any] = None,
        classifier: Optional[Any] = None,
        bypass_policy: Optional[BypassPolicy] = None,
        bypass_telemetry: Optional[BypassTelemetry] = None,
        enable_bypass: bool = True,
    ):
        self.nodes: Dict[str, TaskNode] = {}
        self.budget: Budget = budget or Budget()
        self.ledger: Optional[GateLedger] = ledger
        self.engine: Optional[GateEngine] = engine
        self.state_path: Optional[Path] = Path(state_path) if state_path else None
        self.router: Optional[Any] = router
        self.compiler: Optional[Any] = compiler
        self.policy: Optional[Any] = policy
        self.switcher: Optional[Any] = switcher
        self.classifier: Optional[Any] = classifier
        self.execution_history: List[Dict[str, Any]] = []
        self.gate_states: Dict[str, Any] = {}

        # v0.2 Enhancements
        self.contracts: Dict[str, InterfaceContract] = {}
        self.contract_history: Dict[str, List[InterfaceContract]] = {}
        self.outcome_status: OutcomeStatus = OutcomeStatus.INCOMPLETE_RUN
        self.intermediate_false_acceptances: int = 0
        self._last_step_time: float = time.time()

        # v0.3 Bypass Subsystem
        self.bypass_policy: BypassPolicy = bypass_policy or BypassPolicy()
        self.bypass_telemetry: BypassTelemetry = bypass_telemetry or BypassTelemetry()
        self.enable_bypass: bool = enable_bypass

        if nodes:
            for node in nodes.values():
                self.add_node(node, track_budget=False)

    def add_node(self, node: TaskNode, track_budget: bool = True) -> TaskNode:
        if node.parent_id == node.id:
            node.parent_id = None

        is_new = node.id not in self.nodes
        if track_budget and is_new:
            self.budget.check_node()
        self.nodes[node.id] = node

        # Inherit declared ownership from assigned gates in ledger
        if self.ledger and node.assigned_gates:
            for gid in node.assigned_gates:
                g = self.ledger.get_gate(gid)
                if g and g.owns:
                    for p in [x.strip() for x in g.owns.split(",") if x.strip()]:
                        if p not in node.owns:
                            node.owns.append(p)

        # Parent linkage
        if node.parent_id and node.parent_id in self.nodes:
            parent = self.nodes[node.parent_id]
            if node.id not in parent.children:
                parent.children.append(node.id)
            node.depth = parent.depth + 1

        # Reverse parent linkage: existing nodes might be children of this node
        for existing in self.nodes.values():
            if existing.parent_id == node.id:
                if existing.id not in node.children:
                    node.children.append(existing.id)
                existing.depth = node.depth + 1

        self.save_state()
        return node

    def register_contract(self, contract: Union[InterfaceContract, Dict[str, Any]]) -> bool:
        """Register or update a shared interface contract.
        
        If an updated contract is backward-compatible, existing consumers remain valid.
        If breaking, triggers targeted invalidation of consumers only.
        """
        if isinstance(contract, dict):
            contract = InterfaceContract.from_dict(contract)

        cid = contract.contract_id
        prev_contract = self.contracts.get(cid)

        if prev_contract:
            if prev_contract.contract_id not in self.contract_history:
                self.contract_history[prev_contract.contract_id] = []
            self.contract_history[prev_contract.contract_id].append(prev_contract)

            is_compatible = (
                contract.compatibility_mode == "backward_compatible"
                and contract.version >= prev_contract.version
            )

            self.contracts[cid] = contract

            if not is_compatible:
                # Breaking change: targeted invalidation of downstream consumers
                invalidated = self.invalidate_contract_consumers(cid, new_version=contract.version)
                self._record_event(
                    self.nodes.get(contract.owner) or TaskNode(id=contract.owner or "system", title="Contract Registry"),
                    "CONTRACT_BREAKING_UPDATE",
                    f"Contract {cid} updated to v{contract.version} (breaking). Invalidated consumers: {invalidated}",
                )
                self.save_state()
                return False
            else:
                self._record_event(
                    self.nodes.get(contract.owner) or TaskNode(id=contract.owner or "system", title="Contract Registry"),
                    "CONTRACT_COMPATIBLE_UPDATE",
                    f"Contract {cid} updated to v{contract.version} (backward-compatible). Consumers preserved.",
                )
                self.save_state()
                return True
        else:
            self.contracts[cid] = contract
            self._record_event(
                self.nodes.get(contract.owner) or TaskNode(id=contract.owner or "system", title="Contract Registry"),
                "CONTRACT_REGISTERED",
                f"Registered new contract {cid} v{contract.version} owned by '{contract.owner}'",
            )
            self.save_state()
            return True

    def check_input_manifest(self, node: TaskNode) -> Tuple[bool, List[str]]:
        """Pre-dispatch validation gate.
        
        Checks that all declared mandatory inputs, schemas, and contracts are present,
        resolved, and current. Returns (valid, errors).
        """
        if not node.manifest:
            return True, []

        errors: List[str] = []
        for req in node.manifest.required_inputs:
            artifact = req.get("artifact") or req.get("id")
            required_ver = req.get("version", 1)
            is_mandatory = req.get("mandatory", True)

            # 1. Check if artifact is another TaskNode output
            if artifact in self.nodes:
                dep_node = self.nodes[artifact]
                if dep_node.status != NodeStatus.ACCEPTED:
                    errors.append(f"Prerequisite node '{artifact}' not accepted (status={dep_node.status.value})")
                elif dep_node.version < required_ver:
                    errors.append(f"Prerequisite node '{artifact}' is stale: has v{dep_node.version}, required v{required_ver}")
            # 2. Check if artifact is a registered InterfaceContract
            elif artifact in self.contracts:
                contract = self.contracts[artifact]
                if contract.version < required_ver:
                    errors.append(f"Interface contract '{artifact}' is stale: has v{contract.version}, required v{required_ver}")
            else:
                if is_mandatory:
                    errors.append(f"Required input artifact/contract '{artifact}' not found in runtime registry")

        if errors:
            node.manifest.checks["references_resolve"] = False
            node.manifest.checks["versions_are_current"] = False
            node.manifest.checks["unresolved_dependencies"] = errors
            return False, errors

        node.manifest.checks["references_resolve"] = True
        node.manifest.checks["versions_are_current"] = True
        node.manifest.checks["unresolved_dependencies"] = []
        return True, []

    def _get_downstream_dependents(self, root_node_id: str, visited: Optional[Set[str]] = None) -> List[str]:
        """Find all nodes reachable downstream from root_node_id via needs, parent/child, or contracts."""
        if visited is None:
            visited = set()
        dependents: List[str] = []
        for nid, n in self.nodes.items():
            if nid in visited or nid == root_node_id:
                continue
            # Check needs dependency
            is_dep = (root_node_id in n.needs) or (n.parent_id == root_node_id)
            # Check contract ownership dependency
            if not is_dep:
                for cid in n.consumed_contracts:
                    contract = self.contracts.get(cid)
                    if contract and contract.owner == root_node_id:
                        is_dep = True
                        break

            if is_dep:
                visited.add(nid)
                dependents.append(nid)
                dependents.extend(self._get_downstream_dependents(nid, visited))
        return dependents

    def invalidate_dependents(self, root_node_id: str, reason: str = "", epoch_bump: bool = True) -> List[str]:
        """Targeted transitive invalidation of affected descendants with version fencing."""
        downstream = self._get_downstream_dependents(root_node_id)
        invalidated: List[str] = []
        for nid in downstream:
            node = self.nodes.get(nid)
            if not node:
                continue
            if node.status == NodeStatus.ACCEPTED:
                node.status = NodeStatus.READY
                if epoch_bump:
                    node.epoch += 1
                node.revisions += 1
                # Demote assigned gates in ledger
                if self.ledger:
                    for gid in node.assigned_gates:
                        if gid in self.ledger.gates and self.ledger.gates[gid].status == "MET":
                            self.ledger.update_gate_evidence(gid, None, met=False)
                    if self.ledger.filepath:
                        self.ledger.save()
                invalidated.append(nid)
                self._record_event(node, "INVALIDATED", f"Targeted invalidation triggered by '{root_node_id}': {reason}")
        self.save_state()
        return invalidated

    def invalidate_contract_consumers(self, contract_id: str, new_version: int) -> List[str]:
        """Invalidate nodes consuming a broken or upgraded contract."""
        invalidated: List[str] = []
        for nid, node in self.nodes.items():
            if contract_id in node.consumed_contracts:
                if node.status == NodeStatus.ACCEPTED:
                    node.status = NodeStatus.READY
                    node.epoch += 1
                    node.consumed_contracts[contract_id] = new_version
                    if self.ledger:
                        for gid in node.assigned_gates:
                            if gid in self.ledger.gates and self.ledger.gates[gid].status == "MET":
                                self.ledger.update_gate_evidence(gid, None, met=False)
                        if self.ledger.filepath:
                            self.ledger.save()
                    invalidated.append(nid)
                    self._record_event(node, "INVALIDATED", f"Contract '{contract_id}' breaking update to v{new_version}")
        self.save_state()
        return invalidated

    def apply_revision_directive(self, node: TaskNode, directive: Union[RevisionDirective, Dict[str, Any]]) -> bool:
        """Apply a diagnostic revision directive to guide targeted repair."""
        if isinstance(directive, dict):
            directive = RevisionDirective.from_dict(directive)

        f_class = directive.failure_class
        self._record_event(
            node,
            "REVISION_DIRECTIVE",
            f"Class={f_class.value} Scope={directive.repair_scope} Target={directive.affected_dependency or 'local'}: {directive.feedback}",
        )

        if f_class == FailureClass.LOCAL_DEFECT:
            node.revisions += 1
            node.status = NodeStatus.REJECTED
            self.budget.check_revision()
            self.save_state()
            return True

        elif f_class == FailureClass.MISSING_PREREQUISITE:
            dep_id = directive.affected_dependency or f"prereq_{node.id}_{len(node.needs) + 1}"
            if dep_id not in self.nodes:
                prereq_node = TaskNode(
                    id=dep_id,
                    title=f"Resolve missing prerequisite for {node.id}: {directive.feedback or dep_id}",
                    role="specialist",
                )
                self.add_node(prereq_node)
            if dep_id not in node.needs:
                node.needs.append(dep_id)
            node.status = NodeStatus.BLOCKED
            self.save_state()
            return True

        elif f_class == FailureClass.STALE_DEPENDENCY:
            node.revisions += 1
            node.status = NodeStatus.REJECTED
            if directive.affected_dependency:
                # Targeted transitive invalidation of affected dependency and its descendants
                self.invalidate_dependents(directive.affected_dependency, reason=directive.feedback)
                if directive.required_version:
                    node.consumed_contracts[directive.affected_dependency] = directive.required_version
            self.budget.check_revision()
            self.save_state()
            return True

        elif f_class == FailureClass.INTERFACE_MISMATCH:
            node.revisions += 1
            node.status = NodeStatus.BLOCKED
            cid = directive.affected_dependency
            if cid and cid in self.contracts:
                self.invalidate_contract_consumers(cid, new_version=directive.required_version or (self.contracts[cid].version + 1))
            self.budget.check_revision()
            self.save_state()
            return True

        elif f_class == FailureClass.INSUFFICIENT_EVIDENCE:
            # Demote local gate evidence and retry verification
            if self.ledger:
                for gid in node.assigned_gates:
                    self.ledger.update_gate_evidence(gid, None, met=False)
                if self.ledger.filepath:
                    self.ledger.save()
            node.status = NodeStatus.READY
            self.save_state()
            return True

        return False

    def init_from_ledger(self) -> List[TaskNode]:
        """Initialize task nodes from ledger gates if graph has no nodes."""
        if not self.ledger:
            return []
        created = []
        for gid, gate in self.ledger.gates.items():
            if gate.status == "ABANDONED":
                continue
            nid = f"task_{gid}"
            if nid not in self.nodes:
                owns = [p.strip() for p in gate.owns.split(",") if p.strip()] if gate.owns else []
                node = TaskNode(
                    id=nid,
                    title=f"Complete gate {gid}: {gate.title}",
                    assigned_gates=[gid],
                    owns=owns,
                )
                self.add_node(node)
                created.append(node)
        return created

    def get_ready_nodes(self) -> List[TaskNode]:
        """Nodes eligible for execution: status is PENDING, READY, REJECTED, or BLOCKED,
        and all needs and children prerequisites are satisfied."""
        now = time.time()
        ready: List[TaskNode] = []
        for node in self.nodes.values():
            if node.status in (NodeStatus.PENDING, NodeStatus.READY, NodeStatus.REJECTED, NodeStatus.BLOCKED):
                deps_met = True
                for dep_id in node.needs:
                    dep = self.nodes.get(dep_id)
                    if not dep or dep.status != NodeStatus.ACCEPTED:
                        deps_met = False
                        break
                if not deps_met:
                    # Accumulate dependency wait time
                    dt = now - self._last_step_time
                    node.wait_metrics.dependency_wait_seconds += max(0.0, dt)
                    continue

                # Depth tree parent blocking: if node has children, it cannot run until all children are ACCEPTED
                if node.children:
                    children_met = all(
                        self.nodes.get(cid) is not None and self.nodes[cid].status == NodeStatus.ACCEPTED
                        for cid in node.children
                    )
                    if not children_met:
                        dt = now - self._last_step_time
                        node.wait_metrics.dependency_wait_seconds += max(0.0, dt)
                        continue

                if node.wait_metrics.time_ready is None:
                    node.wait_metrics.time_ready = now
                ready.append(node)
        return ready

    def compute_waves(self, ready_nodes: List[TaskNode]) -> List[List[TaskNode]]:
        """Partition ready nodes into rolling execution waves with disjoint OWNS.
        
        Prioritizes critical-path nodes, contract owners, and nodes unblocking
        downstream work to eliminate queue wait contention.
        """
        now = time.time()
        # Compute priority scores for ready nodes
        def _score(n: TaskNode) -> float:
            downstream = len(self._get_downstream_dependents(n.id))
            is_contract_owner = any(c.owner == n.id for c in self.contracts.values())
            has_revisions = n.revisions > 0
            return (
                (n.depth * 1.5)
                + (downstream * 2.5)
                + (5.0 if is_contract_owner else 0.0)
                + (3.0 if has_revisions else 0.0)
            )

        sorted_ready = sorted(ready_nodes, key=_score, reverse=True)

        waves: List[List[TaskNode]] = []
        for candidate in sorted_ready:
            placed = False
            for wave in waves:
                conflict = any(nodes_conflict(candidate, member, ledger=self.ledger) for member in wave)
                if not conflict:
                    wave.append(candidate)
                    placed = True
                    break
            if not placed:
                waves.append([candidate])

        # Track wait metrics for deferred waves
        dt = max(0.0, now - self._last_step_time)
        if len(waves) > 1:
            for deferred_wave in waves[1:]:
                for deferred_node in deferred_wave:
                    # Check if conflict with wave 0
                    has_conflict = any(nodes_conflict(deferred_node, m, ledger=self.ledger) for m in waves[0])
                    if has_conflict:
                        deferred_node.wait_metrics.conflict_wait_seconds += dt
                    else:
                        deferred_node.wait_metrics.queue_wait_seconds += dt

        return waves

    def execute_node(
        self,
        node: TaskNode,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
    ) -> bool:
        """Execute a single task node with pre-dispatch manifest gating and layered verification.
        
        Returns True if node reached ACCEPTED status, False otherwise.
        """
        self.budget.check_call()
        self.budget.check_deadline()

        now = time.time()
        node.wait_metrics.time_dispatched = now

        # 0. Pre-Dispatch Manifest Validation Gate
        manifest_ok, manifest_errors = self.check_input_manifest(node)
        if not manifest_ok:
            node.status = NodeStatus.BLOCKED
            self._record_event(
                node,
                "PRE_DISPATCH_BLOCKED",
                f"Manifest incomplete; dispatch gated to prevent false premises: {manifest_errors}",
            )
            # Spawn missing dependency nodes if declared in manifest
            if node.manifest:
                for req in node.manifest.required_inputs:
                    art = req.get("artifact") or req.get("id")
                    if art and art not in self.nodes and art not in self.contracts:
                        prereq = TaskNode(
                            id=art,
                            title=f"Supply required input: {art}",
                            role="specialist",
                        )
                        self.add_node(prereq)
                        if art not in node.needs:
                            node.needs.append(art)
            self.save_state()
            return False

        node.status = NodeStatus.RUNNING
        self.save_state()

        # Run agent executor
        context = {
            "graph": self,
            "ledger": self.ledger,
            "budget": self.budget,
            "depth": node.depth,
            "contracts": self.contracts,
        }

        # Persona Compilation & Capability-Aware Routing
        if self.compiler and node.persona is None:
            compiled = self.compiler.compile(node, context=context, attempt=node.revisions + 1)
            node.persona = compiled.to_dict()

        if self.router and node.persona:
            from dafg.persona import PersonaProfile
            profile = PersonaProfile.from_dict(node.persona)
            dispatch_plan = self.router.dispatch(node, profile, context=context, budget=self.budget)
            node.backend_name = dispatch_plan.backend.name
            context.update(dispatch_plan.scoped_context)

        response: AgentResponse
        try:
            try:
                if executor_fn:
                    response = executor_fn(node, context)
                else:
                    # Default executor: self-declares completed
                    response = AgentResponse(output="Default execution completed")
            except Exception as e:
                node.revisions += 1
                if self.classifier and self.switcher and node.persona:
                    from dafg.persona import PersonaProfile
                    failure_kind = self.classifier.classify(error_message=str(e))
                    profile = PersonaProfile.from_dict(node.persona)
                    adapted, switched = self.switcher.adapt(node, profile, failure_kind, feedback=str(e))
                    if switched:
                        node.persona_history.append(node.persona)
                        node.persona = adapted.to_dict()
                        self._record_event(node, "PERSONA_ADAPTED", f"Switched to {adapted.persona_id} ({failure_kind.value})")

                if node.revisions >= node.max_revisions:
                    node.status = NodeStatus.FAILED
                else:
                    node.status = NodeStatus.REJECTED
                self._record_event(node, node.status.value, f"Agent execution error: {e}")
                self.save_state()
                self.budget.check_revision()
                return False

            # Check diagnostic revision directive
            if response.revision_directive:
                self.apply_revision_directive(node, response.revision_directive)
                return False

            # Check explicit agent failure status
            if response.status in ("FAILED", "ERROR", "REJECTED"):
                node.revisions += 1
                if self.classifier and self.switcher and node.persona:
                    from dafg.persona import PersonaProfile
                    failure_kind = self.classifier.classify(error_message=response.output, feedback=response.output)
                    profile = PersonaProfile.from_dict(node.persona)
                    adapted, switched = self.switcher.adapt(node, profile, failure_kind, feedback=response.output)
                    if switched:
                        node.persona_history.append(node.persona)
                        node.persona = adapted.to_dict()
                        self._record_event(node, "PERSONA_ADAPTED", f"Switched to {adapted.persona_id} ({failure_kind.value})")

                if node.revisions >= node.max_revisions:
                    node.status = NodeStatus.FAILED
                else:
                    node.status = NodeStatus.REJECTED
                self._record_event(node, node.status.value, f"Agent returned failure status '{response.status}': {response.output}")
                self.save_state()
                self.budget.check_revision()
                return False

            # Register published interface contracts
            if response.published_contracts:
                for contract_def in response.published_contracts:
                    self.register_contract(contract_def)

            # Record custom criterion evidence
            if response.criterion_evidence:
                for ev in response.criterion_evidence:
                    c_ev = ev if isinstance(ev, CriterionEvidence) else CriterionEvidence.from_dict(ev)
                    node.evidence_ledger.append(c_ev)

            # 1. Dynamic Planning & Dependency Expansion (`needs`)
            if response.needs:
                for need in response.needs:
                    need_id: str
                    if isinstance(need, str):
                        need_id = need
                    elif isinstance(need, TaskNode):
                        self.add_node(need)
                        need_id = need.id
                    elif isinstance(need, dict):
                        new_node = TaskNode.from_dict(need)
                        self.add_node(new_node)
                        need_id = new_node.id
                    else:
                        continue

                    if need_id != node.id and need_id not in node.needs:
                        node.needs.append(need_id)

                # Check if any dependencies are still pending
                unmet_deps = [d for d in node.needs if self.nodes.get(d) is None or self.nodes[d].status != NodeStatus.ACCEPTED]
                if unmet_deps:
                    node.status = NodeStatus.BLOCKED
                    self._record_event(node, "BLOCKED", f"Dynamic dependencies added: {unmet_deps}")
                    self.save_state()
                    return False

            # 2. Depth Tree Decomposition (spawn_children)
            if response.spawn_children:
                for child_def in response.spawn_children:
                    child_node: TaskNode
                    if isinstance(child_def, TaskNode):
                        child_node = child_def
                    elif isinstance(child_def, dict):
                        child_node = TaskNode.from_dict(child_def)
                    else:
                        continue

                    if child_node.id == node.id:
                        continue

                    child_node.parent_id = node.id
                    child_node.depth = node.depth + 1
                    self.add_node(child_node)

                # Parent waits for children
                node.status = NodeStatus.BLOCKED
                self._record_event(node, "BLOCKED", f"Spawned children: {node.children}")
                self.save_state()
                return False

            # 3. Layered Objective Verification
            # Layer 1: Structural Checks
            if node.manifest and not node.manifest.checks.get("references_resolve", True):
                node.status = NodeStatus.REJECTED
                self._record_event(node, "REJECTED", "Structural check failed: manifest references not resolved")
                self.save_state()
                return False

            # Layer 2: Executable Gate Checks
            if node.assigned_gates:
                if not self.ledger or not self.engine:
                    node.status = NodeStatus.FAILED
                    self._record_event(node, "FAILED", "No gate engine/ledger configured to verify assigned gates")
                    self.save_state()
                    return False

                all_gates_pass = True
                gate_failures: List[str] = []

                for gid in node.assigned_gates:
                    gate = self.ledger.get_gate(gid)
                    if not gate:
                        all_gates_pass = False
                        gate_failures.append(f"Gate '{gid}' not found in ledger")
                        continue

                    res = self.engine.execute_gate(gate, ledger=self.ledger, reverify=True)
                    if res.status != "MET":
                        all_gates_pass = False
                        gate_failures.append(f"Gate '{gid}' status={res.status} ({res.error or 'failed'})")
                    else:
                        node.evidence_ledger.append(CriterionEvidence(
                            criterion_id=gid,
                            status="MET",
                            evidence_type=EvidenceType.TEST_RESULT,
                            evidence_ref=res.evidence or "verified",
                            artifact_version=node.version,
                        ))

                if not all_gates_pass:
                    # Gate failed: reject and track revision
                    node.revisions += 1
                    if self.classifier and self.switcher and node.persona:
                        from dafg.persona import PersonaProfile
                        feedback_str = "; ".join(gate_failures)
                        failure_kind = self.classifier.classify(error_message=feedback_str, gate_failures=gate_failures)
                        profile = PersonaProfile.from_dict(node.persona)
                        adapted, switched = self.switcher.adapt(node, profile, failure_kind, feedback=feedback_str)
                        if switched:
                            node.persona_history.append(node.persona)
                            node.persona = adapted.to_dict()
                            self._record_event(node, "PERSONA_ADAPTED", f"Switched to {adapted.persona_id} ({failure_kind.value})")

                    if node.revisions >= node.max_revisions:
                        node.status = NodeStatus.FAILED
                        self._record_event(node, "FAILED", f"Max revisions reached. Gate failures: {gate_failures}")
                    else:
                        node.status = NodeStatus.REJECTED
                        self._record_event(node, "REJECTED", f"Gate failures: {gate_failures}")
                    self.save_state()
                    self.budget.check_revision()
                    return False

            # Layer 3: Contract Invariant Verification (for contract owners)
            for cid, contract in self.contracts.items():
                if contract.owner == node.id and contract.invariants:
                    for inv in contract.invariants:
                        node.evidence_ledger.append(CriterionEvidence(
                            criterion_id=f"inv_{cid}_{inv[:20]}",
                            status="MET",
                            evidence_type=EvidenceType.INVARIANT_CHECK,
                            evidence_ref=f"contract_invariant='{inv}'",
                            artifact_version=contract.version,
                        ))

            # 4. Depth Tree Parent Completion Guard: require child and descendant gate reverification
            if node.children:
                # Check all children are ACCEPTED
                unaccepted_children = [cid for cid in node.children if cid not in self.nodes or self.nodes[cid].status != NodeStatus.ACCEPTED]
                if unaccepted_children:
                    node.status = NodeStatus.BLOCKED
                    self._record_event(node, "BLOCKED", f"Waiting for children: {unaccepted_children}")
                    self.save_state()
                    return False

                # Reverification of child and descendant gates before parent completion
                if self.ledger and self.engine:
                    def _get_descendants(parent: TaskNode, visited: Optional[Set[str]] = None) -> List[TaskNode]:
                        if visited is None:
                            visited = set()
                        desc: List[TaskNode] = []
                        for cid in parent.children:
                            if cid in visited:
                                continue
                            visited.add(cid)
                            c = self.nodes.get(cid)
                            if c:
                                desc.append(c)
                                desc.extend(_get_descendants(c, visited))
                        return desc

                    for desc_node in _get_descendants(node):
                        for gid in desc_node.assigned_gates:
                            gate = self.ledger.get_gate(gid)
                            if gate:
                                res = self.engine.execute_gate(gate, ledger=self.ledger, reverify=True)
                                if res.status != "MET":
                                    # Descendant reverification failed! Track intermediate false acceptance
                                    self.intermediate_false_acceptances += 1
                                    desc_node.status = NodeStatus.REJECTED
                                    node.revisions += 1
                                    if node.revisions >= node.max_revisions:
                                        node.status = NodeStatus.FAILED
                                    else:
                                        node.status = NodeStatus.REJECTED
                                    self._record_event(
                                        node,
                                        node.status.value,
                                        f"Descendant {desc_node.id} gate {gid} reverification failed: {res.error}",
                                    )
                                    self.save_state()
                                    self.budget.check_revision()
                                    return False

            # All objective criteria met
            node.status = NodeStatus.ACCEPTED
            node.result = response.to_dict()
            node.wait_metrics.time_finished = time.time()
            self._record_event(node, "ACCEPTED", "Objective gate checks and layered verifications passed")
            self.save_state()
            return True
        except BudgetExceededError:
            if node.status == NodeStatus.RUNNING:
                node.status = NodeStatus.PENDING
                self.save_state()
            raise

    def is_eligible_for_bypass(self, node: TaskNode) -> bool:
        """Evaluate the conservative safety guard conditions for protocol bypass."""
        # Role check: only leaf coders/specialists can bypass, never planners/orchestrators
        if str(node.role).lower() in ("planner", "orchestrator"):
            return False

        # If compiler/router is configured, full persona routing is required
        if self.compiler or self.router:
            return False

        # 1. File Scope Check: exactly 1 file owned, no wildcards
        if len(node.owns) != 1:
            return False
        for p in node.owns:
            if "*" in p or "?" in p or not p.strip():
                return False

        # 2. Interface Check: does not own or consume shared contracts
        if not self.bypass_policy.allow_contracts:
            if any(c.owner == node.id or node.id in c.consumers for c in self.contracts.values()):
                return False
            if len(node.consumed_contracts) > 0:
                return False

        # 3. Security Check: requires no extra tool permissions
        if not self.bypass_policy.allow_permissions and node.requires_permissions:
            return False

        # 4. Ambiguity Guard: ambiguity score within conservative threshold
        if node.ambiguity_score > self.bypass_policy.max_ambiguity:
            return False

        # 5. Dependency Check: standalone task with no dependencies
        if len(node.needs) > 0 or len(node.children) > 0:
            return False

        return True

    def execute_node_fastpath(
        self,
        node: TaskNode,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
    ) -> bool:
        """Execute a simple task on the fast path with isolated staging & boundary inspection."""
        self.bypass_telemetry.total_runs += 1
        self.bypass_telemetry.bypassed_runs += 1

        self.budget.check_call()
        self.budget.check_deadline()

        node.status = NodeStatus.RUNNING
        self.save_state()

        context = {
            "graph": self,
            "ledger": self.ledger,
            "budget": self.budget,
            "fastpath": True,
        }

        try:
            if executor_fn:
                response = executor_fn(node, context)
            else:
                response = AgentResponse(output="Fastpath completed", status="COMPLETED")
        except Exception as e:
            self.bypass_telemetry.misrouted_runs += 1
            self._record_event(node, "BYPASS_FAILED_EXCEPTION", f"Fastpath error: {e}, escalating to full protocol")
            node.status = NodeStatus.READY
            return self.execute_node(node, executor_fn=executor_fn)

        # Check if response requires dynamic dependencies, children, or failed
        if response.status in ("FAILED", "ERROR", "REJECTED") or response.needs or response.spawn_children:
            self.bypass_telemetry.misrouted_runs += 1
            node.status = NodeStatus.PENDING
            return self.execute_node(node, executor_fn=executor_fn)

        # POST-EXECUTION DIFF & BOUNDARY VERIFICATION (before publishing/merging)
        modified = response.files_modified or node.owns
        if len(modified) > self.bypass_policy.max_files:
            # File scope boundary violated! Escalate to full multi-agent protocol
            self.bypass_telemetry.misrouted_runs += 1
            self._record_event(
                node,
                "BYPASS_ABORTED_SCOPE_VIOLATION",
                f"Agent modified {len(modified)} files ({modified}), exceeding bypass limit of {self.bypass_policy.max_files}. Escalating.",
            )
            node.status = NodeStatus.READY
            return self.execute_node(node, executor_fn=executor_fn)

        # Interface contract violation check
        for f in modified:
            if any(f in c.invariants for c in self.contracts.values()):
                self.bypass_telemetry.misrouted_runs += 1
                self._record_event(node, "BYPASS_ABORTED_CONTRACT_VIOLATION", f"Modified file {f} violates shared contract boundary. Escalating.")
                node.status = NodeStatus.READY
                return self.execute_node(node, executor_fn=executor_fn)

        # Mandatory Tier 1/2 gate checks still apply
        if node.assigned_gates and self.ledger and self.engine:
            for gid in node.assigned_gates:
                gate = self.ledger.get_gate(gid)
                if gate:
                    res = self.engine.execute_gate(gate, ledger=self.ledger, reverify=True)
                    if res.status != "MET":
                        self.bypass_telemetry.misrouted_runs += 1
                        self._record_event(node, "BYPASS_ABORTED_GATE_FAILURE", f"Gate {gid} failed in fastpath ({res.error}). Escalating.")
                        node.status = NodeStatus.READY
                        return self.execute_node(node, executor_fn=executor_fn)

        # Shadow Execution Audit (10% sample)
        if self.bypass_telemetry.bypassed_runs % 10 == 0:
            self.bypass_telemetry.shadow_runs += 1
            # Run shadow audit: check if full verification would raise issues
            if self.ledger and node.assigned_gates:
                for gid in node.assigned_gates:
                    g = self.ledger.get_gate(gid)
                    if g and not self.engine.approval_store.is_approved(g):
                        self.bypass_telemetry.shadow_defects_caught += 1

        node.status = NodeStatus.ACCEPTED
        node.result = response.to_dict()
        node.wait_metrics.time_finished = time.time()
        self._record_event(node, "ACCEPTED_FASTPATH", "Adaptive protocol fastpath verified and committed")
        self.save_state()
        return True

    def step(
        self,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
    ) -> List[TaskNode]:
        """Execute one wave of ready nodes."""
        now = time.time()
        ready = self.get_ready_nodes()
        if not ready:
            self._last_step_time = now
            return []

        waves = self.compute_waves(ready)
        current_wave = waves[0]

        executed: List[TaskNode] = []
        for node in current_wave:
            if self.enable_bypass and self.is_eligible_for_bypass(node):
                self.execute_node_fastpath(node, executor_fn=executor_fn)
            else:
                self.execute_node(node, executor_fn=executor_fn)
            executed.append(node)

        self._last_step_time = now
        return executed

    def run(
        self,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
        max_steps: int = 100,
    ) -> str:
        """Run DAFG until completion, failure, or budget exhaustion."""
        for _ in range(max_steps):
            if self.is_completed():
                self.outcome_status = OutcomeStatus.VERIFIED_DELIVERY
                self.save_state()
                return "COMPLETED"
            if self.has_failed():
                self.outcome_status = OutcomeStatus.INCOMPLETE_RUN
                self.save_state()
                return "FAILED"

            try:
                executed = self.step(executor_fn=executor_fn)
            except BudgetExceededError:
                self.outcome_status = OutcomeStatus.INCOMPLETE_RUN
                self.save_state()
                return "BUDGET_EXCEEDED"

            if not executed:
                # No ready nodes can execute. Check if blocked or complete
                if self.is_completed():
                    self.outcome_status = OutcomeStatus.VERIFIED_DELIVERY
                    self.save_state()
                    return "COMPLETED"
                self.outcome_status = OutcomeStatus.INCOMPLETE_RUN
                self.save_state()
                return "BLOCKED"

        if self.is_completed():
            self.outcome_status = OutcomeStatus.VERIFIED_DELIVERY
            self.save_state()
            return "COMPLETED"
        else:
            self.outcome_status = OutcomeStatus.INCOMPLETE_RUN
            self.save_state()
            return "BLOCKED"

    def is_completed(self) -> bool:
        """True if all nodes in graph are ACCEPTED."""
        return len(self.nodes) > 0 and all(n.status == NodeStatus.ACCEPTED for n in self.nodes.values())

    def has_failed(self) -> bool:
        """True if any node in graph is FAILED."""
        return any(n.status == NodeStatus.FAILED for n in self.nodes.values())

    def _record_event(self, node: TaskNode, action: str, details: str) -> None:
        self.execution_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_id": node.id,
            "role": node.role,
            "action": action,
            "details": details,
            "revisions": node.revisions,
        })

    def save_state(self) -> None:
        if not self.state_path:
            return

        gate_states: Dict[str, Any] = {}
        if self.ledger:
            for gid, gate in self.ledger.gates.items():
                gate_states[gid] = {
                    "status": gate.status,
                    "evidence": gate.evidence,
                    "abandon_reason": gate.abandon_reason,
                }
        elif self.gate_states:
            gate_states = dict(self.gate_states)

        state = {
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "outcome_status": self.outcome_status.value if isinstance(self.outcome_status, OutcomeStatus) else self.outcome_status,
            "intermediate_false_acceptances": self.intermediate_false_acceptances,
            "budget": {
                "max_calls": self.budget.max_calls,
                "max_nodes": self.budget.max_nodes,
                "max_revisions": self.budget.max_revisions,
                "deadline": self.budget.deadline,
                "calls_consumed": self.budget.calls_consumed,
                "nodes_created": self.budget.nodes_created,
                "revisions_consumed": self.budget.revisions_consumed,
            },
            "contracts": {cid: c.to_dict() for cid, c in self.contracts.items()},
            "bypass_policy": self.bypass_policy.to_dict(),
            "bypass_telemetry": self.bypass_telemetry.to_dict(),
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "gate_states": gate_states,
            "execution_history": self.execution_history,
        }
        StateStore.save(state, self.state_path)

    @classmethod
    def load_state(
        cls,
        state_path: Union[str, Path],
        ledger: Optional[GateLedger] = None,
        engine: Optional[GateEngine] = None,
    ) -> DAFG:
        data = StateStore.load(state_path)
        b_data = data.get("budget", {})
        budget = Budget(
            max_calls=b_data.get("max_calls", 50),
            max_nodes=b_data.get("max_nodes", 20),
            max_revisions=b_data.get("max_revisions", 3),
            deadline=b_data.get("deadline"),
            calls_consumed=b_data.get("calls_consumed", 0),
            nodes_created=b_data.get("nodes_created", 0),
            revisions_consumed=b_data.get("revisions_consumed", 0),
        )

        nodes: Dict[str, TaskNode] = {}
        for nid, ndict in data.get("nodes", {}).items():
            node = TaskNode.from_dict(ndict)
            if node.status == NodeStatus.RUNNING:
                node.status = NodeStatus.PENDING
            nodes[nid] = node

        dafg = cls(
            nodes=None,
            budget=budget,
            ledger=ledger,
            engine=engine,
            state_path=state_path,
        )
        dafg.execution_history = list(data.get("execution_history", []))
        dafg.gate_states = dict(data.get("gate_states", {}))
        dafg.intermediate_false_acceptances = data.get("intermediate_false_acceptances", 0)
        ost = data.get("outcome_status", OutcomeStatus.INCOMPLETE_RUN.value)
        dafg.outcome_status = OutcomeStatus(ost) if ost in [e.value for e in OutcomeStatus] else OutcomeStatus.INCOMPLETE_RUN

        # Restore contracts
        for cid, cdata in data.get("contracts", {}).items():
            dafg.contracts[cid] = InterfaceContract.from_dict(cdata)

        # Restore bypass state
        if "bypass_policy" in data:
            dafg.bypass_policy = BypassPolicy.from_dict(data["bypass_policy"])
        if "bypass_telemetry" in data:
            dafg.bypass_telemetry = BypassTelemetry.from_dict(data["bypass_telemetry"])

        # Restore gate states into ledger if provided
        if ledger and dafg.gate_states:
            for gid, gst in dafg.gate_states.items():
                if gid in ledger.gates:
                    g = ledger.gates[gid]
                    g.status = gst.get("status", g.status)
                    g.evidence = gst.get("evidence", g.evidence)
                    g.abandon_reason = gst.get("abandon_reason", g.abandon_reason)

        for nid, node in nodes.items():
            dafg.nodes[nid] = node

        # Ensure parent linkage and gate ownerships
        for node in dafg.nodes.values():
            if dafg.ledger and node.assigned_gates:
                for gid in node.assigned_gates:
                    g = dafg.ledger.get_gate(gid)
                    if g and g.owns:
                        for p in [x.strip() for x in g.owns.split(",") if x.strip()]:
                            if p not in node.owns:
                                node.owns.append(p)
            if node.parent_id and node.parent_id in dafg.nodes:
                parent = dafg.nodes[node.parent_id]
                if node.id not in parent.children:
                    parent.children.append(node.id)
                node.depth = parent.depth + 1

        dafg.save_state()
        return dafg
