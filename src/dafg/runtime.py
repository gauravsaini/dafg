"""DAFG Dynamic Task Graph & Depth Tree Runtime.

Executes autonomous agent workflows backed by objective gate evidence, dynamic
planning, specialist roles, dependency expansion (`needs`), depth trees,
disjoint file ownership (`OWNS:`), rolling waves, budget caps, atomic state
persistence (`state.json`), pre-dispatch manifest gating, failure-directed repair,
versioned interface contracts, and layered verification.
"""

from __future__ import annotations

import concurrent.futures
import fcntl
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from dafg.observe import ObservabilityFabric

from dafg.gates import EvidenceStrength, Gate, GateEngine, GateLedger, GateResult, classify_evidence
from dafg.protocol import (
    Action,
    AuditRecord,
    DispatchIdentity,
    DomainEvent,
    ExecutionStatus,
    IllegalTransitionError,
    ProtocolCommand,
    ProtocolEngine,
    ProtocolReducer,
    ProtocolState,
    RunSealedError,
    StaleDispatchError,
    state_projection,
)


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


class RefusalClass(str, Enum):
    """Refusal classification for pre-dispatch gating and impossible requirements."""
    MISSING_PREREQUISITE = "MISSING_PREREQUISITE"
    MISSING_AUTHORIZATION = "MISSING_AUTHORIZATION"
    CONTRADICTORY_REQUIREMENTS = "CONTRADICTORY_REQUIREMENTS"
    UNAVAILABLE_CAPABILITY = "UNAVAILABLE_CAPABILITY"
    RECOVERABLE_TOOL_FAILURE = "RECOVERABLE_TOOL_FAILURE"



class OutcomeStatus(str, Enum):
    """Outcome classification of a DAFG run or node execution."""
    VERIFIED_DELIVERY = "VERIFIED_DELIVERY"
    HANDOFF_REQUIRED = "HANDOFF_REQUIRED"
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
class ProtocolEvent:
    """Structured, replayable state machine transition event."""
    event_id: int
    timestamp: str
    node_id: str
    role: str
    from_status: Optional[str]
    to_status: str
    action: str
    epoch: int
    revisions: int
    details: str = ""
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "node_id": self.node_id,
            "role": self.role,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "action": self.action,
            "epoch": self.epoch,
            "revisions": self.revisions,
            "details": self.details or self.reason,
            "reason": self.reason or self.details,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProtocolEvent:
        return cls(
            event_id=data.get("event_id", 0),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            node_id=data.get("node_id", ""),
            role=data.get("role", "coder"),
            from_status=data.get("from_status"),
            to_status=data.get("to_status", data.get("action", "UNKNOWN")),
            action=data.get("action", ""),
            epoch=data.get("epoch", 1),
            revisions=data.get("revisions", 0),
            details=data.get("details", ""),
            reason=data.get("reason", data.get("details", "")),
            payload=data.get("payload", {}),
        )


ALLOWED_TRANSITIONS: Dict[NodeStatus, Set[NodeStatus]] = {
    NodeStatus.PENDING: {NodeStatus.READY, NodeStatus.RUNNING, NodeStatus.BLOCKED},
    NodeStatus.READY: {NodeStatus.RUNNING, NodeStatus.BLOCKED},
    NodeStatus.RUNNING: {
        NodeStatus.ACCEPTED,
        NodeStatus.REJECTED,
        NodeStatus.BLOCKED,
        NodeStatus.FAILED,
        NodeStatus.PENDING,
        NodeStatus.READY,
    },
    NodeStatus.BLOCKED: {NodeStatus.READY, NodeStatus.RUNNING, NodeStatus.PENDING, NodeStatus.FAILED},
    NodeStatus.REJECTED: {NodeStatus.READY, NodeStatus.RUNNING, NodeStatus.FAILED},
    NodeStatus.ACCEPTED: {NodeStatus.READY, NodeStatus.REJECTED, NodeStatus.BLOCKED},  # Invalidation only
    NodeStatus.FAILED: set(),  # Terminal state: cannot transition out of FAILED
}


@dataclass
class Budget:
    max_calls: int = 50
    max_nodes: int = 20
    max_revisions: int = 3
    max_adaptations: int = 15
    deadline: Optional[float] = None  # Unix timestamp

    calls_consumed: int = 0
    nodes_created: int = 0
    revisions_consumed: int = 0
    adaptations_consumed: int = 0

    # ponytail: single coarse lock for all counters; split per-counter if profiling shows contention
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    fabric: Optional[Any] = field(default=None, repr=False, compare=False)

    def check_call(self) -> None:
        with self._lock:
            if self.calls_consumed >= self.max_calls:
                if self.fabric:
                    self.fabric.emit_event("budget.exceeded", {"type": "call", "consumed": self.calls_consumed, "max": self.max_calls})
                raise BudgetExceededError(
                    f"Model call budget exceeded: {self.calls_consumed}/{self.max_calls}"
                )
            self.calls_consumed += 1
            if self.fabric:
                self.fabric.emit_metric("budget.calls_consumed", float(self.calls_consumed))

    def check_node(self) -> None:
        with self._lock:
            if self.nodes_created >= self.max_nodes:
                if self.fabric:
                    self.fabric.emit_event("budget.exceeded", {"type": "node", "consumed": self.nodes_created, "max": self.max_nodes})
                raise BudgetExceededError(
                    f"Node budget exceeded: {self.nodes_created}/{self.max_nodes}"
                )
            self.nodes_created += 1
            if self.fabric:
                self.fabric.emit_metric("budget.nodes_created", float(self.nodes_created))

    def check_deadline(self) -> None:
        if self.deadline is not None and time.time() > self.deadline:
            if self.fabric:
                self.fabric.emit_event("budget.deadline_exceeded", {"current_time": time.time(), "deadline": self.deadline})
            raise BudgetExceededError(
                f"Deadline exceeded: {time.time():.1f} > {self.deadline:.1f}"
            )

    def check_revision(self) -> None:
        with self._lock:
            if self.revisions_consumed >= self.max_revisions:
                if self.fabric:
                    self.fabric.emit_event("budget.exceeded", {"type": "revision", "consumed": self.revisions_consumed, "max": self.max_revisions})
                raise BudgetExceededError(
                    f"Revision budget exceeded: {self.revisions_consumed}/{self.max_revisions}"
                )
            self.revisions_consumed += 1
            if self.fabric:
                self.fabric.emit_metric("budget.revisions_consumed", float(self.revisions_consumed))

    def check_adaptation(self) -> None:
        with self._lock:
            if self.adaptations_consumed >= self.max_adaptations:
                if self.fabric:
                    self.fabric.emit_event("budget.exceeded", {"type": "adaptation", "consumed": self.adaptations_consumed, "max": self.max_adaptations})
                raise BudgetExceededError(
                    f"Adaptation budget exceeded: {self.adaptations_consumed}/{self.max_adaptations}"
                )
            self.adaptations_consumed += 1
            if self.fabric:
                self.fabric.emit_metric("budget.adaptations_consumed", float(self.adaptations_consumed))


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
class WaveDiagnostics:
    """Per-step wave concurrency diagnostics.

    Records the shape of each scheduler step: how many nodes were ready,
    how many could actually run in wave-0, which ``OWNS:`` paths forced
    nodes into deferred waves, and the resulting concurrency ratio.
    """
    step_index: int = 0
    timestamp: float = field(default_factory=time.time)
    total_ready: int = 0
    wave_widths: List[int] = field(default_factory=list)
    wave_0_width: int = 0
    concurrency_ratio: float = 0.0  # wave_0_width / total_ready
    conflict_reasons: List[Dict[str, Any]] = field(default_factory=list)
    parallel_dispatch: bool = False
    wall_time_seconds: float = 0.0
    serial_estimate_seconds: float = 0.0
    speedup_ratio: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WaveDiagnostics':
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
    owns: List[str] = field(default_factory=list)  # declared file paths / patterns (write ownership)
    owns_read: List[str] = field(default_factory=list)  # read-only ownership (doesn't conflict with other reads)
    parent_id: Optional[str] = None  # parent in depth tree
    children: List[str] = field(default_factory=list)  # child node IDs
    depth: int = 0
    attempts: int = 0  # physical execution count
    revisions: int = 0  # semantic specification modifications
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

    # v0.3 Refusal Dispatch
    refusal_class: Optional[RefusalClass] = None
    refusal_reason: Optional[str] = None

    # Protocol-conformance state architecture
    protocol_state: ProtocolState = ProtocolState.IDLE
    execution_status: ExecutionStatus = ExecutionStatus.READY
    active_dispatch: Optional[DispatchIdentity] = None

    def __post_init__(self):
        if self.status == NodeStatus.ACCEPTED and self.protocol_state == ProtocolState.IDLE:
            self.protocol_state = ProtocolState.ACCEPTED
            self.execution_status = ExecutionStatus.SETTLED

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, NodeStatus) else self.status
        d["protocol_state"] = self.protocol_state.value if isinstance(self.protocol_state, ProtocolState) else str(self.protocol_state)
        d["execution_status"] = self.execution_status.value if isinstance(self.execution_status, ExecutionStatus) else str(self.execution_status)
        if self.active_dispatch:
            d["active_dispatch"] = self.active_dispatch.to_dict()
        if self.refusal_class:
            d["refusal_class"] = self.refusal_class.value if isinstance(self.refusal_class, RefusalClass) else self.refusal_class
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
        if "protocol_state" in d and isinstance(d["protocol_state"], str):
            d["protocol_state"] = ProtocolState(d["protocol_state"])
        if "execution_status" in d and isinstance(d["execution_status"], str):
            d["execution_status"] = ExecutionStatus(d["execution_status"])
        if "active_dispatch" in d and isinstance(d["active_dispatch"], dict):
            d["active_dispatch"] = DispatchIdentity.from_dict(d["active_dispatch"])
        if "refusal_class" in d and isinstance(d["refusal_class"], str):
            d["refusal_class"] = RefusalClass(d["refusal_class"])
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
    epoch: Optional[int] = None
    dispatch_identity: Optional[DispatchIdentity] = None
    needs: List[Union[str, TaskNode, Dict[str, Any]]] = field(default_factory=list)
    spawn_children: List[Union[TaskNode, Dict[str, Any]]] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    revision_directive: Optional[Union[RevisionDirective, Dict[str, Any]]] = None
    published_contracts: List[Union[InterfaceContract, Dict[str, Any]]] = field(default_factory=list)
    criterion_evidence: List[Union[CriterionEvidence, Dict[str, Any]]] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.dispatch_identity, dict):
            self.dispatch_identity = DispatchIdentity.from_dict(self.dispatch_identity)
        if self.epoch is None and self.dispatch_identity is not None:
            self.epoch = getattr(self.dispatch_identity, "epoch", None)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "output": self.output,
            "status": self.status,
            "files_modified": self.files_modified,
            "metadata": self.metadata,
        }
        if self.epoch is not None:
            d["epoch"] = self.epoch
        if self.dispatch_identity is not None:
            d["dispatch_identity"] = self.dispatch_identity.to_dict() if hasattr(self.dispatch_identity, "to_dict") else self.dispatch_identity
        if self.revision_directive:
            d["revision_directive"] = self.revision_directive.to_dict() if hasattr(self.revision_directive, "to_dict") else self.revision_directive
        if self.published_contracts:
            d["published_contracts"] = [c.to_dict() if hasattr(c, "to_dict") else c for c in self.published_contracts]
        if self.criterion_evidence:
            d["criterion_evidence"] = [e.to_dict() if hasattr(e, "to_dict") else e for e in self.criterion_evidence]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentResponse":
        disp_raw = d.get("dispatch_identity")
        disp = DispatchIdentity.from_dict(disp_raw) if isinstance(disp_raw, dict) else disp_raw
        epoch = d.get("epoch")
        if epoch is None and disp:
            epoch = getattr(disp, "epoch", None)
        return cls(
            output=d.get("output", ""),
            status=d.get("status", "COMPLETED"),
            files_modified=d.get("files_modified", []),
            metadata=d.get("metadata", {}),
            epoch=epoch,
            dispatch_identity=disp,
            needs=d.get("needs", []),
            spawn_children=d.get("spawn_children", []),
            revision_directive=d.get("revision_directive"),
            published_contracts=d.get("published_contracts", []),
            criterion_evidence=d.get("criterion_evidence", []),
        )


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
    """Check if two nodes have overlapping file ownership using reader-writer semantics.

    Conflict rules (like a reader-writer lock):
      - write vs write on overlapping paths -> CONFLICT
      - write vs read  on overlapping paths -> CONFLICT
      - read  vs read  on overlapping paths -> NO CONFLICT

    ``OWNS:`` (and gate ``OWNS:``) is write ownership.
    ``owns_read`` (and gate ``OWNS_READ:``) is read-only ownership.
    """
    def get_owns_rw(n: TaskNode) -> Tuple[Set[str], Set[str]]:
        """Returns (write_paths, read_paths) for a node."""
        writes = set(n.owns)
        reads = set(n.owns_read)
        if ledger and n.assigned_gates:
            for gid in n.assigned_gates:
                g = ledger.get_gate(gid)
                if g:
                    if g.owns:
                        for p in [x.strip() for x in g.owns.split(",") if x.strip()]:
                            writes.add(p)
                    owns_read_val = getattr(g, "owns_read", None)
                    if owns_read_val:
                        for p in [x.strip() for x in owns_read_val.split(",") if x.strip()]:
                            reads.add(p)
        return writes, reads

    w1, r1 = get_owns_rw(node1)
    w2, r2 = get_owns_rw(node2)

    # Write-write conflicts
    for p1 in w1:
        for p2 in w2:
            if paths_overlap(p1, p2):
                return True
    # Write-read conflicts (either direction)
    for p1 in w1:
        for p2 in r2:
            if paths_overlap(p1, p2):
                return True
    for p1 in r1:
        for p2 in w2:
            if paths_overlap(p1, p2):
                return True
    # Read-read: NO conflict (this is the whole point)
    return False


class OptimisticConcurrencyConflictError(Exception):
    """Raised when an atomic CAS state commit detects a version conflict."""
    pass


class StateStore:
    """Handles atomic persistence of DAFG runtime state."""

    _save_lock = threading.Lock()

    @staticmethod
    def commit(
        filepath: Union[str, Path],
        new_state: Dict[str, Any],
        expected_version: Optional[int] = None,
    ) -> int:
        """Atomic Compare-And-Swap commit with advisory fcntl file locking."""
        with StateStore._save_lock:
            fp = Path(filepath)
            fp.parent.mkdir(parents=True, exist_ok=True)
            lock_file = fp.with_name(f"{fp.name}.lock")
            tmp_file = fp.with_name(f"{fp.name}.tmp.{os.getpid()}_{time.time_ns()}")
            with open(lock_file, "w") as lf:
                try:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                    current_version = 0
                    if fp.exists():
                        try:
                            content = fp.read_text(encoding="utf-8")
                            if content.strip():
                                current_data = json.loads(content)
                                current_version = int(current_data.get("state_version", 0))
                        except Exception:
                            current_version = 0

                    if expected_version is not None and expected_version != current_version:
                        raise OptimisticConcurrencyConflictError(
                            f"CAS version mismatch: expected version {expected_version}, but on-disk state is at version {current_version}"
                        )

                    next_version = current_version + 1
                    new_state["state_version"] = next_version
                    tmp_file.write_text(json.dumps(new_state, indent=2), encoding="utf-8")
                    os.replace(tmp_file, fp)
                    return next_version
                finally:
                    try:
                        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass

    @staticmethod
    def save(state: Dict[str, Any], filepath: Union[str, Path]) -> None:
        StateStore.commit(filepath, state, expected_version=None)

    @staticmethod
    def load(filepath: Union[str, Path]) -> Dict[str, Any]:
        fp = Path(filepath)
        lock_file = fp.with_name(f"{fp.name}.lock")
        if lock_file.exists():
            with open(lock_file, "w") as lf:
                try:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_SH)
                    return json.loads(fp.read_text(encoding="utf-8"))
                finally:
                    try:
                        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
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
        probes: Optional[list] = None,
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
        self._step_counter: int = 0

        # Wave concurrency diagnostics
        self.wave_diagnostics: List[WaveDiagnostics] = []
        self.max_parallel_workers: int = 4  # 0 = serial (legacy), >0 = ThreadPoolExecutor

        # ponytail: coarse lock for node state mutations under parallel dispatch
        self._state_lock = threading.Lock()

        # v0.3 Bypass Subsystem
        self.bypass_policy: BypassPolicy = bypass_policy or BypassPolicy()
        self.bypass_telemetry: BypassTelemetry = bypass_telemetry or BypassTelemetry()
        self.enable_bypass: bool = enable_bypass

        # Protocol Engine Subsystem
        self.run_id: str = f"run_{int(time.time()*1000)}_{os.getpid()}"
        self.run_epoch: int = 1
        self.state_version: int = 0
        self.is_sealed: bool = False
        self.sealed_at: Optional[str] = None
        self.processed_idempotency_keys: Set[str] = set()
        self.domain_events: List[Dict[str, Any]] = []
        self.audit_log: List[Dict[str, Any]] = []
        self.seq_counter: int = 0

        # v0.4 Distributed Observability Fabric (DOF)
        self._fabric = ObservabilityFabric(probes)
        if self.budget and getattr(self.budget, "fabric", None) is None:
            self.budget.fabric = self._fabric
        if self.engine and getattr(self.engine, "_fabric", None) is None:
            self.engine._fabric = self._fabric

        if nodes:
            for node in nodes.values():
                self.add_node(node, track_budget=False)

    def next_seq(self) -> int:
        self.seq_counter += 1
        return self.seq_counter

    def submit_command(self, cmd: ProtocolCommand) -> Tuple[List[DomainEvent], Optional[AuditRecord]]:
        """Submit a formal protocol command through ProtocolEngine and ProtocolReducer."""
        if self.is_sealed and cmd.action != Action.SEAL_RUN:
            record = AuditRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                idempotency_key=cmd.idempotency_key,
                action=cmd.action.value,
                node_id=cmd.node_id,
                reason=f"Run is sealed; all state transitions are strictly prohibited.",
            )
            self.audit_log.append(record.to_dict())
            self.save_state()
            raise RunSealedError(record.reason)

        if cmd.idempotency_key in self.processed_idempotency_keys:
            return [], None

        events, audit = ProtocolEngine.decide(self, cmd, self.next_seq)
        if audit:
            self.audit_log.append(audit.to_dict())
            self._fabric.emit_event("audit.rejected", audit.to_dict())
            self.save_state()
            if "sealed" in audit.reason.lower():
                raise RunSealedError(audit.reason)
            if "stale" in audit.reason.lower() or "mismatch" in audit.reason.lower():
                raise StaleDispatchError(audit.reason)
            raise IllegalTransitionError(audit.reason)

        for ev in events:
            ProtocolReducer.apply(self, ev)
            self.domain_events.append(ev.to_dict())
            self.processed_idempotency_keys.add(ev.idempotency_key)
            self._fabric.emit_event(ev.event_type, ev.to_dict())

        self.save_state()
        return events, None

    def seal_run(self) -> bool:
        """Atomically seal the graph run against completion integrity."""
        if self.is_sealed:
            return True
        cmd = ProtocolCommand(
            idempotency_key=f"seal_{self.run_id}_{self.next_seq()}",
            action=Action.SEAL_RUN,
            node_id="",
            run_id=self.run_id,
            reason="Graph completion integrity verified and sealed",
        )
        try:
            events, audit = self.submit_command(cmd)
            return self.is_sealed
        except IllegalTransitionError:
            return False

    def add_node(self, node: TaskNode, track_budget: bool = True) -> TaskNode:
        if self.is_sealed:
            raise RunSealedError(f"Cannot add node '{node.id}' to sealed run '{self.run_id}'")
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

    def validate_transition(
        self,
        node: TaskNode,
        target_status: NodeStatus,
        epoch_bump: bool = False,
        response: Optional[AgentResponse] = None,
        **kwargs,
    ) -> Tuple[bool, Optional[str]]:
        """Validate whether a proposed state transition satisfies protocol guards."""
        current_status = node.status if isinstance(node.status, NodeStatus) else NodeStatus(node.status)

        # 1. State machine transition graph check
        if current_status != target_status:
            allowed = ALLOWED_TRANSITIONS.get(current_status, set())
            if target_status not in allowed:
                return False, f"Prohibited transition: {current_status.value} -> {target_status.value}"

        # 2. Guard for RUNNING: all declared prerequisites must be in ACCEPTED
        if target_status == NodeStatus.RUNNING:
            for dep_id in node.needs:
                dep = self.nodes.get(dep_id)
                if not dep or dep.status != NodeStatus.ACCEPTED:
                    return False, f"Prerequisite '{dep_id}' is not ACCEPTED (status={dep.status.value if dep else 'None'})"

        # 3. Guard for ACCEPTED: evidence, manifests, and epoch fencing
        if target_status == NodeStatus.ACCEPTED:
            # Epoch fencing: reject stale response
            if response and response.epoch is not None and response.epoch < node.epoch:
                return False, f"Stale epoch verdict: response epoch {response.epoch} < current node epoch {node.epoch}"

            # Evidence ledger epoch integrity
            for ev in node.evidence_ledger:
                if ev.artifact_version < node.epoch:
                    return False, f"Stale criterion evidence '{ev.criterion_id}': version {ev.artifact_version} < node epoch {node.epoch}"

            # Gate ledger evidence check (if assigned gates exist)
            if node.assigned_gates and self.ledger:
                for gid in node.assigned_gates:
                    gate = self.ledger.get_gate(gid)
                    if not gate:
                        return False, f"Assigned gate '{gid}' not found in ledger"
                    if gate.status == "ABANDONED":
                        if not getattr(gate, 'abandon_reason', None) or not gate.abandon_reason.strip():
                            return False, f"Assigned gate '{gid}' is ABANDONED without justification"
                        continue  # Valid abandonment — skip evidence check
                    if gate.status != "MET":
                        return False, f"Assigned gate '{gid}' is not MET in ledger"
                    if not gate.evidence or "exit_code=0" not in gate.evidence:
                        return False, f"Assigned gate '{gid}' lacks valid execution evidence"

            # Manifest integrity check
            if node.manifest:
                ok, errs = self.check_input_manifest(node)
                if not ok:
                    return False, f"Manifest validation failed: {errs}"

        # 4. Guard for invalidation from ACCEPTED to READY, REJECTED, or BLOCKED
        if current_status == NodeStatus.ACCEPTED and target_status in (NodeStatus.READY, NodeStatus.REJECTED, NodeStatus.BLOCKED):
            if not epoch_bump:
                return False, "Transitioning from ACCEPTED requires explicit epoch bump (invalidation)"

        return True, None

    def commit_transition(
        self,
        node: TaskNode,
        target_status: Union[NodeStatus, str],
        action: str,
        reason: str = "",
        payload: Optional[Dict[str, Any]] = None,
        epoch_bump: bool = False,
        response: Optional[AgentResponse] = None,
        **kwargs,
    ) -> ProtocolEvent:
        """Bridge to ProtocolEngine: maps legacy (NodeStatus, action) to a ProtocolCommand
        and delegates to submit_command() for unified state authority."""
        with self._state_lock:
            if self.is_sealed:
                raise RunSealedError(f"Cannot commit transition on sealed run '{self.run_id}'")
            if isinstance(target_status, str):
                target_status = NodeStatus(target_status)
            from_status = node.status if isinstance(node.status, NodeStatus) else NodeStatus(node.status)

            # --- Map legacy action string to protocol Action ---
            protocol_action = self._map_legacy_action(target_status, action, from_status, epoch_bump)

            if protocol_action is not None:
                # Route through ProtocolEngine (the unified authority)
                dispatch_ident = (
                    getattr(response, "dispatch_identity", None)
                    or getattr(node, "active_dispatch", None)
                    or kwargs.get("dispatch_identity")
                )
                cmd_payload = dict(payload or {})
                if response and "result" not in cmd_payload:
                    cmd_payload["result"] = response.to_dict()
                if dispatch_ident and "dispatch_identity" not in cmd_payload:
                    cmd_payload["dispatch_identity"] = (
                        dispatch_ident.to_dict() if hasattr(dispatch_ident, "to_dict") else dispatch_ident
                    )
                if "revisions" not in cmd_payload:
                    cmd_payload["revisions"] = node.revisions

                # If accepting from PROVING, transition to VERIFYING first via SUBMIT_PROPOSAL
                current_p_state = getattr(node, "protocol_state", ProtocolState.IDLE)
                if isinstance(current_p_state, str):
                    current_p_state = ProtocolState(current_p_state)
                if protocol_action == Action.ACCEPT_VERDICT and current_p_state == ProtocolState.PROVING:
                    prop_cmd = ProtocolCommand(
                        idempotency_key=f"prop_{node.id}_{self.next_seq()}",
                        action=Action.SUBMIT_PROPOSAL,
                        node_id=node.id,
                        run_id=self.run_id,
                        dispatch_identity=dispatch_ident,
                        reason="Submitting proposal for objective verification",
                        payload=cmd_payload,
                    )
                    try:
                        self.submit_command(prop_cmd)
                    except IllegalTransitionError as e:
                        self._record_event(
                            node,
                            "ILLEGAL_TRANSITION_ATTEMPT",
                            f"Prohibited transition {from_status.value} -> VERIFYING: {e}",
                        )
                        raise

                cmd = ProtocolCommand(
                    idempotency_key=f"ct_{node.id}_{self.next_seq()}",
                    action=protocol_action,
                    node_id=node.id,
                    run_id=self.run_id,
                    dispatch_identity=dispatch_ident,
                    reason=reason,
                    payload=cmd_payload,
                )
                if epoch_bump:
                    cmd.payload["epoch_bump"] = True

                try:
                    events, audit = self.submit_command(cmd)
                except IllegalTransitionError as e:
                    self._record_event(
                        node,
                        "ILLEGAL_TRANSITION_ATTEMPT",
                        f"Prohibited transition {from_status.value} -> {target_status.value}: {e}",
                    )
                    raise

                # Build legacy ProtocolEvent for callers that depend on the return value
                event_id = len(self.execution_history) + 1
                event = ProtocolEvent(
                    event_id=event_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    node_id=node.id,
                    role=node.role,
                    from_status=from_status.value,
                    to_status=target_status.value,
                    action=action,
                    epoch=node.epoch,
                    revisions=node.revisions,
                    details=reason,
                    reason=reason,
                    payload=payload or {},
                )
                self.execution_history.append(event.to_dict())

                # Ensure NodeStatus is in sync (reducer sets it via ProtocolState mapping,
                # but some transitions need exact NodeStatus like BLOCKED/FAILED/PENDING)
                if node.status != target_status:
                    node.status = target_status
                if target_status == NodeStatus.BLOCKED:
                    node.execution_status = ExecutionStatus.BLOCKED
                elif target_status == NodeStatus.FAILED:
                    node.execution_status = ExecutionStatus.SETTLED

                self.save_state()
                return event

            # --- Fallback: legacy path for unmapped transitions ---
            valid, err = self.validate_transition(
                node,
                target_status,
                epoch_bump=epoch_bump,
                response=response,
                **kwargs,
            )
            if not valid:
                self._record_event(
                    node,
                    "ILLEGAL_TRANSITION_ATTEMPT",
                    f"Prohibited transition {from_status.value} -> {target_status.value}: {err}",
                )
                raise IllegalTransitionError(f"Protocol violation for node '{node.id}': {err}")

            if epoch_bump:
                node.epoch += 1

            node.status = target_status
            if target_status == NodeStatus.READY:
                if from_status == NodeStatus.ACCEPTED or action in ("INVALIDATED", "INVALIDATE"):
                    node.protocol_state = ProtocolState.STALE
                else:
                    node.protocol_state = ProtocolState.IDLE
                node.execution_status = ExecutionStatus.READY
            elif target_status == NodeStatus.ACCEPTED:
                node.protocol_state = ProtocolState.ACCEPTED
                node.execution_status = ExecutionStatus.SETTLED
            elif target_status == NodeStatus.REJECTED:
                node.protocol_state = ProtocolState.REJECTED
                node.execution_status = ExecutionStatus.SETTLED
            elif target_status == NodeStatus.BLOCKED:
                node.execution_status = ExecutionStatus.BLOCKED
            elif target_status == NodeStatus.RUNNING:
                node.execution_status = ExecutionStatus.RUNNING
            event_id = len(self.execution_history) + 1
            event = ProtocolEvent(
                event_id=event_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                node_id=node.id,
                role=node.role,
                from_status=from_status.value,
                to_status=target_status.value,
                action=action,
                epoch=node.epoch,
                revisions=node.revisions,
                details=reason,
                reason=reason,
                payload=payload or {},
            )
            self.execution_history.append(event.to_dict())
            self.save_state()
            return event

    @staticmethod
    def _map_legacy_action(
        target: NodeStatus,
        action_str: str,
        from_status: NodeStatus,
        epoch_bump: bool,
    ) -> Optional[Action]:
        """Map a legacy (NodeStatus, action_string) pair to a protocol Action.
        Returns None if no mapping exists (triggers fallback path)."""
        # Dispatch actions
        if action_str == "DISPATCHED":
            return Action.DISPATCH_PROVE
        if action_str == "DISPATCH_FASTPATH":
            return Action.DISPATCH_FASTPATH

        # Acceptance actions
        if target == NodeStatus.ACCEPTED and action_str in ("ACCEPTED", "ACCEPTED_FASTPATH"):
            return Action.ACCEPT_VERDICT

        # Rejection actions
        if target == NodeStatus.REJECTED and action_str == "REJECTED":
            return Action.REJECT

        # Invalidation
        if action_str in ("INVALIDATED", "INVALIDATE", "REVISE_SUPERSEDES") and epoch_bump:
            return Action.INVALIDATE

        # Blocking actions
        if target == NodeStatus.BLOCKED:
            return Action.BLOCK

        # Ready (non-invalidation) — return to idle
        if target == NodeStatus.READY and action_str in ("READY", "BYPASS_ESCALATED"):
            return Action.REVISE  # Revise covers "go back and try differently"

        # Failure (terminal)
        if target == NodeStatus.FAILED:
            return Action.FAIL

        # Budget halt (back to pending/idle)
        if action_str == "BUDGET_HALTED":
            return Action.HALT

        # Worker refused (blocked)
        if action_str == "WORKER_REFUSED":
            return Action.BLOCK

        return None  # Unmapped: use fallback


    def verify_completion_integrity(self) -> Tuple[bool, List[str]]:
        """Verifies that graph completion is backed by current, contract-bound evidence."""
        if not self.nodes:
            return False, ["Graph has no nodes"]

        errors: List[str] = []
        for nid, node in self.nodes.items():
            if node.status != NodeStatus.ACCEPTED:
                errors.append(f"Node '{nid}' is not ACCEPTED (status={node.status.value})")

            # 1. Gate evidence integrity
            if node.assigned_gates and self.ledger:
                for gid in node.assigned_gates:
                    gate = self.ledger.get_gate(gid)
                    if not gate:
                        errors.append(f"Node '{nid}' references missing gate '{gid}'")
                    elif gate.status == "ABANDONED":
                        if not getattr(gate, 'abandon_reason', None) or not gate.abandon_reason.strip():
                            errors.append(f"Node '{nid}' assigned gate '{gid}' is ABANDONED without justification")
                    elif gate.status != "MET":
                        errors.append(f"Node '{nid}' assigned gate '{gid}' is {gate.status}, not MET")
                    elif not gate.evidence or "exit_code=0" not in gate.evidence:
                        errors.append(f"Node '{nid}' assigned gate '{gid}' lacks verified execution evidence")

            # 2. Manifest integrity
            if node.manifest:
                ok, manifest_errs = self.check_input_manifest(node)
                if not ok:
                    errors.extend([f"Node '{nid}' manifest error: {e}" for e in manifest_errs])

            # 3. Contract integrity
            for cid, req_ver in node.consumed_contracts.items():
                if cid not in self.contracts:
                    errors.append(f"Node '{nid}' consumes missing contract '{cid}'")
                elif self.contracts[cid].version < req_ver:
                    errors.append(f"Node '{nid}' consumes stale contract '{cid}' (has v{self.contracts[cid].version}, requires v{req_ver})")

            # 4. Evidence ledger epoch integrity
            for ev in node.evidence_ledger:
                if ev.artifact_version < node.epoch:
                    errors.append(f"Node '{nid}' contains stale evidence '{ev.criterion_id}' (version {ev.artifact_version} < node epoch {node.epoch})")

        return len(errors) == 0, errors

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

    def invalidate_dependents(
        self,
        root_node_id: str,
        reason: str = "",
        epoch_bump: bool = True,
        exclude: Optional[Set[str]] = None,
    ) -> List[str]:
        """Targeted transitive invalidation of affected descendants with version fencing."""
        downstream = self._get_downstream_dependents(root_node_id)
        invalidated: List[str] = []
        for nid in downstream:
            if exclude and nid in exclude:
                continue
            node = self.nodes.get(nid)
            if not node:
                continue
            if node.status in (NodeStatus.ACCEPTED, NodeStatus.RUNNING, NodeStatus.BLOCKED, NodeStatus.PENDING):
                # Mandatory invalidation bookkeeping is unconstrained by budget
                node.revisions += 1
                # Demote assigned gates in ledger
                if self.ledger:
                    for gid in node.assigned_gates:
                        if gid in self.ledger.gates and self.ledger.gates[gid].status == "MET":
                            self.ledger.update_gate_evidence(gid, None, met=False)
                    if self.ledger.filepath:
                        self.ledger.save()
                invalidated.append(nid)
                self.commit_transition(
                    node,
                    NodeStatus.READY,
                    action="INVALIDATED",
                    reason=f"Targeted invalidation triggered by '{root_node_id}': {reason}",
                    epoch_bump=epoch_bump,
                )
        self.save_state()
        return invalidated

    def invalidate_contract_consumers(self, contract_id: str, new_version: int) -> List[str]:
        """Invalidate nodes consuming a broken or upgraded contract."""
        invalidated: List[str] = []
        for nid, node in self.nodes.items():
            if contract_id in node.consumed_contracts:
                if node.status in (NodeStatus.ACCEPTED, NodeStatus.RUNNING, NodeStatus.BLOCKED):
                    # Mandatory invalidation bookkeeping is unconstrained by budget
                    node.consumed_contracts[contract_id] = new_version
                    if self.ledger:
                        for gid in node.assigned_gates:
                            if gid in self.ledger.gates and self.ledger.gates[gid].status == "MET":
                                self.ledger.update_gate_evidence(gid, None, met=False)
                        if self.ledger.filepath:
                            self.ledger.save()
                    invalidated.append(nid)
                    self.commit_transition(
                        node,
                        NodeStatus.READY,
                        action="INVALIDATED",
                        reason=f"Contract '{contract_id}' breaking update to v{new_version}",
                        epoch_bump=True,
                    )
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
            self.budget.check_revision()
            self.commit_transition(
                node,
                NodeStatus.REJECTED,
                action="REJECTED",
                reason=f"Local defect: {directive.feedback}",
                epoch_bump=(node.status == NodeStatus.ACCEPTED),
            )
            return True

        elif f_class == FailureClass.MISSING_PREREQUISITE:
            self.budget.check_adaptation()
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
            self.commit_transition(
                node,
                NodeStatus.BLOCKED,
                action="BLOCKED",
                reason=f"Missing prerequisite: {dep_id}",
                epoch_bump=(node.status == NodeStatus.ACCEPTED),
            )
            return True

        elif f_class == FailureClass.STALE_DEPENDENCY:
            node.revisions += 1
            self.budget.check_revision()
            if directive.affected_dependency:
                # Targeted transitive invalidation of affected dependency and its descendants, excluding this node
                self.invalidate_dependents(directive.affected_dependency, reason=directive.feedback, exclude={node.id})
                if directive.required_version:
                    node.consumed_contracts[directive.affected_dependency] = directive.required_version
            self.commit_transition(
                node,
                NodeStatus.REJECTED,
                action="REJECTED",
                reason=f"Stale dependency: {directive.feedback}",
                epoch_bump=(node.status == NodeStatus.ACCEPTED),
            )
            return True

        elif f_class == FailureClass.INTERFACE_MISMATCH:
            node.revisions += 1
            self.budget.check_revision()
            cid = directive.affected_dependency
            if cid and cid in self.contracts:
                self.invalidate_contract_consumers(cid, new_version=directive.required_version or (self.contracts[cid].version + 1))
            self.commit_transition(
                node,
                NodeStatus.BLOCKED,
                action="BLOCKED",
                reason=f"Interface mismatch: {cid}",
                epoch_bump=(node.status == NodeStatus.ACCEPTED),
            )
            return True

        elif f_class == FailureClass.INSUFFICIENT_EVIDENCE:
            self.budget.check_adaptation()
            # Demote local gate evidence and retry verification
            if self.ledger:
                for gid in node.assigned_gates:
                    self.ledger.update_gate_evidence(gid, None, met=False)
                if self.ledger.filepath:
                    self.ledger.save()
            self.commit_transition(node, NodeStatus.READY, action="READY", reason="Insufficient evidence: demoted for reverification")
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
                # Permanent refusal check: if node was blocked due to missing authorization,
                # contradictory requirements, or unavailable capability, do not re-dispatch.
                if node.status == NodeStatus.BLOCKED and node.refusal_class in (
                    RefusalClass.MISSING_AUTHORIZATION,
                    RefusalClass.CONTRADICTORY_REQUIREMENTS,
                    RefusalClass.UNAVAILABLE_CAPABILITY,
                ):
                    continue

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
        conflict_reasons: List[Dict[str, Any]] = []
        for candidate in sorted_ready:
            placed = False
            for wave in waves:
                conflict = any(nodes_conflict(candidate, member, ledger=self.ledger) for member in wave)
                if not conflict:
                    wave.append(candidate)
                    placed = True
                    break
            if not placed:
                # Record why this node couldn't join any existing wave
                if waves:
                    for member in waves[-1]:
                        if nodes_conflict(candidate, member, ledger=self.ledger):
                            conflict_reasons.append({
                                "deferred_node": candidate.id,
                                "conflicting_node": member.id,
                                "deferred_owns": list(candidate.owns),
                                "conflicting_owns": list(member.owns),
                            })
                            break
                waves.append([candidate])

        # Record wave diagnostics
        self._step_counter += 1
        total_ready = len(ready_nodes)
        wave_0_width = len(waves[0]) if waves else 0
        diag = WaveDiagnostics(
            step_index=self._step_counter,
            timestamp=now,
            total_ready=total_ready,
            wave_widths=[len(w) for w in waves],
            wave_0_width=wave_0_width,
            concurrency_ratio=wave_0_width / total_ready if total_ready > 0 else 0.0,
            conflict_reasons=conflict_reasons,
            parallel_dispatch=self.max_parallel_workers > 0,
        )
        self.wave_diagnostics.append(diag)

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

        # 0. Pre-Dispatch Manifest Validation Gate (Missing Prerequisite)
        manifest_ok, manifest_errors = self.check_input_manifest(node)
        if not manifest_ok:
            node.refusal_class = RefusalClass.MISSING_PREREQUISITE
            node.refusal_reason = f"Manifest incomplete; dispatch gated to prevent false premises: {manifest_errors}"
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
                        self.budget.check_adaptation()
            self.commit_transition(node, NodeStatus.BLOCKED, action="PRE_DISPATCH_BLOCKED", reason=node.refusal_reason)
            return False

        # 1. Pre-Dispatch Authorization Gate (Missing Authorization)
        if node.requires_permissions:
            is_authorized = node.metadata.get("authorized", False)
            if not is_authorized:
                node.refusal_class = RefusalClass.MISSING_AUTHORIZATION
                node.refusal_reason = "Operation requires elevated permissions or authorization; paused for approval"
                self.commit_transition(node, NodeStatus.BLOCKED, action="PRE_DISPATCH_BLOCKED_UNAUTHORIZED", reason=node.refusal_reason)
                return False

        # 2. Pre-Dispatch Contradiction Gate (Contradictory Requirements)
        has_contradiction = False
        contradiction_reason = ""
        if hasattr(node, "consumed_contracts"):
            for cid in node.consumed_contracts:
                if cid in self.contracts:
                    invs = self.contracts[cid].invariants
                    for inv in invs:
                        if ("not " + inv in invs) or ("assert False" in inv):
                            has_contradiction = True
                            contradiction_reason = f"Contract '{cid}' contains contradictory invariants: {inv}"
                            break
        if node.metadata.get("has_contradiction"):
            has_contradiction = True
            contradiction_reason = str(node.metadata.get("contradiction_reason", "Contradictory requirements"))
        if has_contradiction:
            node.refusal_class = RefusalClass.CONTRADICTORY_REQUIREMENTS
            node.refusal_reason = f"Contradictory requirements: {contradiction_reason}"
            self.commit_transition(node, NodeStatus.BLOCKED, action="PRE_DISPATCH_BLOCKED_CONTRADICTORY", reason=node.refusal_reason)
            return False

        # 3. Pre-Dispatch Capability Gate (Unavailable Capability / Impossible Requirement)
        is_impossible = False
        impossible_reason = ""
        # Protocol constraint: check required capabilities against runtime boundaries (never node title keywords)
        req_caps = node.metadata.get("required_capabilities", [])
        if isinstance(req_caps, str):
            req_caps = [req_caps]
        unsupported = [c for c in req_caps if c in ("uncomputable", "hypercomputation", "oracle", "quantum_oracle")]
        if unsupported:
            is_impossible = True
            impossible_reason = f"Required capability not supported by runtime: {', '.join(unsupported)}"
        elif node.metadata.get("is_impossible"):
            is_impossible = True
            impossible_reason = str(node.metadata.get("impossible_reason", "Task marked as impossible capability"))

        if is_impossible:
            node.refusal_class = RefusalClass.UNAVAILABLE_CAPABILITY
            node.refusal_reason = f"Unavailable capability: {impossible_reason}"
            self.commit_transition(node, NodeStatus.BLOCKED, action="PRE_DISPATCH_BLOCKED_IMPOSSIBLE", reason=node.refusal_reason)
            return False

        # Form immutable dispatch identity
        snapshot_id = hashlib.sha256(f"{self.run_id}:{node.id}:{node.epoch}:{self.seq_counter}".encode()).hexdigest()[:16]
        max_c_ver = max([c.version for c in self.contracts.values()], default=1)
        dispatch_identity = DispatchIdentity(
            run_id=self.run_id,
            node_id=node.id,
            epoch=node.epoch,
            attempt_id=node.revisions + 1,
            context_snapshot_id=snapshot_id,
            contract_version=max_c_ver,
        )
        node.active_dispatch = dispatch_identity

        self.commit_transition(
            node,
            NodeStatus.RUNNING,
            action="DISPATCHED",
            reason="Node dispatched for execution",
            payload={"dispatch_identity": dispatch_identity.to_dict()},
        )

        # Run agent executor
        context = {
            "graph": self,
            "ledger": self.ledger,
            "budget": self.budget,
            "depth": node.depth,
            "contracts": self.contracts,
            "dispatch_identity": dispatch_identity.to_dict(),
            "epoch": node.epoch,
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
        _triad_timings: Dict[str, float] = {}  # stage -> milliseconds
        try:
            _t_prover_start = time.time()
            try:
                if executor_fn:
                    raw_response = executor_fn(node, context)
                else:
                    # Default executor: self-declares completed
                    raw_response = AgentResponse(output="Default execution completed")

                if isinstance(raw_response, AgentResponse):
                    response = raw_response
                elif isinstance(raw_response, dict):
                    response = AgentResponse.from_dict(raw_response)
                elif raw_response is None:
                    raise ValueError(f"Executor returned None for node '{node.id}'")
                else:
                    raise TypeError(f"Executor returned invalid response type '{type(raw_response).__name__}' for node '{node.id}'")
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
                    tgt = NodeStatus.FAILED
                else:
                    tgt = NodeStatus.REJECTED
                self.commit_transition(node, tgt, action=tgt.value, reason=f"Agent execution error: {e}")
                self.budget.check_revision()
                return False

            _triad_timings["prover_ms"] = round((time.time() - _t_prover_start) * 1000, 1)

            # Check explicit worker refusal / honest block
            if response.status in ("BLOCKED", "REFUSED"):
                r_cls = response.metadata.get("refusal_class")
                if r_cls and isinstance(r_cls, str) and r_cls in [e.value for e in RefusalClass]:
                    node.refusal_class = RefusalClass(r_cls)
                else:
                    node.refusal_class = RefusalClass.UNAVAILABLE_CAPABILITY
                node.refusal_reason = response.output or "Worker honestly declared refusal on task"
                self.commit_transition(node, NodeStatus.BLOCKED, action="WORKER_REFUSED", reason=node.refusal_reason)
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
                        self.budget.check_adaptation()
                        node.persona_history.append(node.persona)
                        node.persona = adapted.to_dict()
                        self._record_event(node, "PERSONA_ADAPTED", f"Switched to {adapted.persona_id} ({failure_kind.value})")

                if node.revisions >= node.max_revisions:
                    tgt = NodeStatus.FAILED
                else:
                    tgt = NodeStatus.REJECTED
                self.commit_transition(node, tgt, action=tgt.value, reason=f"Agent returned failure status '{response.status}': {response.output}")
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
                self.budget.check_adaptation()
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
                    self.commit_transition(node, NodeStatus.BLOCKED, action="BLOCKED", reason=f"Dynamic dependencies added: {unmet_deps}")
                    return False

            # 2. Depth Tree Decomposition (spawn_children)
            if response.spawn_children:
                self.budget.check_adaptation()
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
                self.commit_transition(node, NodeStatus.BLOCKED, action="BLOCKED", reason=f"Spawned children: {node.children}")
                return False

            # 3. Layered Objective Verification
            # Layer 1: Structural Checks
            if node.manifest and not node.manifest.checks.get("references_resolve", True):
                self.commit_transition(node, NodeStatus.REJECTED, action="REJECTED", reason="Structural check failed: manifest references not resolved")
                return False

            # Layer 2: Executable Gate Checks
            _t_verifier_start = time.time()
            if node.assigned_gates:
                if not self.ledger or not self.engine:
                    self.commit_transition(node, NodeStatus.FAILED, action="FAILED", reason="No gate engine/ledger configured to verify assigned gates")
                    return False

                all_gates_pass = True
                gate_failures: List[str] = []

                for gid in node.assigned_gates:
                    gate = self.ledger.get_gate(gid)
                    if not gate:
                        all_gates_pass = False
                        gate_failures.append(f"Gate '{gid}' not found in ledger")
                        continue

                    res = self.engine.execute_gate(
                        gate,
                        ledger=self.ledger,
                        reverify=True,
                        context={
                            "run_id": self.run_id,
                            "run_epoch": self.run_epoch,
                            "node_id": node.id,
                            "attempt_id": node.attempts,
                        },
                    )
                    if res.status != "MET":
                        all_gates_pass = False
                        gate_failures.append(f"Gate '{gid}' status={res.status} ({res.error or 'failed'})")
                    else:
                        node.evidence_ledger.append(CriterionEvidence(
                            criterion_id=gid,
                            status="MET",
                            evidence_type=EvidenceType.TEST_RESULT,
                            evidence_ref=res.evidence or "verified",
                            artifact_version=max(node.version, node.epoch),
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
                            self.budget.check_adaptation()
                            node.persona_history.append(node.persona)
                            node.persona = adapted.to_dict()
                            self._record_event(node, "PERSONA_ADAPTED", f"Switched to {adapted.persona_id} ({failure_kind.value})")

                    tgt = NodeStatus.FAILED if node.revisions >= node.max_revisions else NodeStatus.REJECTED
                    self.commit_transition(node, tgt, action=tgt.value, reason=f"Gate failures: {gate_failures}")
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
                            artifact_version=max(contract.version, node.epoch),
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        ))

            # 4. Depth Tree Parent Completion Guard: require child and descendant gate reverification
            if node.children:
                # Check all children are ACCEPTED
                unaccepted_children = [cid for cid in node.children if cid not in self.nodes or self.nodes[cid].status != NodeStatus.ACCEPTED]
                if unaccepted_children:
                    self.commit_transition(node, NodeStatus.BLOCKED, action="BLOCKED", reason=f"Waiting for children: {unaccepted_children}")
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
                                res = self.engine.execute_gate(
                                    gate,
                                    ledger=self.ledger,
                                    reverify=True,
                                    context={
                                        "run_id": self.run_id,
                                        "run_epoch": self.run_epoch,
                                        "node_id": desc_node.id,
                                        "attempt_id": desc_node.attempts,
                                    },
                                )
                                if res.status != "MET":
                                    # Descendant reverification failed! Track intermediate false acceptance
                                    self.intermediate_false_acceptances += 1
                                    self.commit_transition(
                                        desc_node,
                                        NodeStatus.REJECTED,
                                        action="REJECTED",
                                        reason=f"Reverification failed under parent {node.id}",
                                        epoch_bump=True,
                                    )
                                    node.revisions += 1
                                    tgt = NodeStatus.FAILED if node.revisions >= node.max_revisions else NodeStatus.REJECTED
                                    self.commit_transition(node, tgt, action=tgt.value, reason=f"Descendant {desc_node.id} gate {gid} reverification failed: {res.error}")
                                    self.budget.check_revision()
                                    return False

            # All objective criteria met
            _triad_timings["verifier_ms"] = round((time.time() - _t_verifier_start) * 1000, 1)
            _triad_timings["total_ms"] = round((time.time() - _t_prover_start) * 1000, 1)
            node.metadata["_triad_timings"] = _triad_timings
            node.metadata["_revision_triggers"] = node.revisions
            node.result = response.to_dict()
            node.wait_metrics.time_finished = time.time()

            self.commit_transition(
                node,
                NodeStatus.ACCEPTED,
                action="ACCEPTED",
                reason="Objective gate checks and layered verifications passed",
                response=response,
                payload={"result": response.to_dict()},
            )
            return True
        except BudgetExceededError:
            if node.status == NodeStatus.RUNNING:
                self.commit_transition(node, NodeStatus.PENDING, action="BUDGET_HALTED", reason="Budget exceeded")
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

        # 6. Safety Gate Check: contradictions or impossible requirements cannot bypass protocol guards
        if (
            node.metadata.get("has_contradiction")
            or node.metadata.get("is_impossible")
            or node.metadata.get("required_capabilities")
        ):
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

        # Form immutable dispatch identity for fastpath
        snapshot_id = hashlib.sha256(f"{self.run_id}:{node.id}:{node.epoch}:{self.seq_counter}:fastpath".encode()).hexdigest()[:16]
        max_c_ver = max([c.version for c in self.contracts.values()], default=1)
        dispatch_identity = DispatchIdentity(
            run_id=self.run_id,
            node_id=node.id,
            epoch=node.epoch,
            attempt_id=node.revisions + 1,
            context_snapshot_id=snapshot_id,
            contract_version=max_c_ver,
        )
        node.active_dispatch = dispatch_identity

        self.commit_transition(
            node,
            NodeStatus.RUNNING,
            action="DISPATCH_FASTPATH",
            reason="Dispatched via fastpath branch",
            payload={"dispatch_identity": dispatch_identity.to_dict()},
        )

        context = {
            "graph": self,
            "ledger": self.ledger,
            "budget": self.budget,
            "fastpath": True,
            "dispatch_identity": dispatch_identity.to_dict(),
            "epoch": node.epoch,
        }

        try:
            if executor_fn:
                raw_response = executor_fn(node, context)
            else:
                raw_response = AgentResponse(output="Fastpath completed", status="COMPLETED")

            if isinstance(raw_response, AgentResponse):
                response = raw_response
            elif isinstance(raw_response, dict):
                response = AgentResponse.from_dict(raw_response)
            elif raw_response is None:
                raise ValueError(f"Executor returned None for node '{node.id}'")
            else:
                raise TypeError(f"Executor returned invalid response type '{type(raw_response).__name__}' for node '{node.id}'")
        except Exception as e:
            self.bypass_telemetry.misrouted_runs += 1
            self.commit_transition(node, NodeStatus.READY, action="BYPASS_ESCALATED", reason=f"Fastpath error: {e}, escalating to full protocol")
            return self.execute_node(node, executor_fn=executor_fn)

        # Check if response requires dynamic dependencies, children, or failed
        if response.status in ("FAILED", "ERROR", "REJECTED") or response.needs or response.spawn_children:
            self.bypass_telemetry.misrouted_runs += 1
            self.commit_transition(node, NodeStatus.READY, action="BYPASS_ESCALATED", reason="Fastpath requires dynamic dependencies or decomposition")
            return self.execute_node(node, executor_fn=executor_fn)

        # POST-EXECUTION DIFF & BOUNDARY VERIFICATION (before publishing/merging)
        modified = response.files_modified or node.owns
        if len(modified) > self.bypass_policy.max_files:
            # File scope boundary violated! Escalate to full multi-agent protocol
            self.bypass_telemetry.misrouted_runs += 1
            self.commit_transition(
                node,
                NodeStatus.READY,
                action="BYPASS_ESCALATED",
                reason=f"Agent modified {len(modified)} files ({modified}), exceeding bypass limit of {self.bypass_policy.max_files}. Escalating.",
            )
            return self.execute_node(node, executor_fn=executor_fn)

        # Interface contract violation check
        for f in modified:
            if any(f in c.invariants for c in self.contracts.values()):
                self.bypass_telemetry.misrouted_runs += 1
                self.commit_transition(node, NodeStatus.READY, action="BYPASS_ESCALATED", reason=f"Modified file {f} violates shared contract boundary. Escalating.")
                return self.execute_node(node, executor_fn=executor_fn)

        # Mandatory Tier 1/2 gate checks still apply
        if node.assigned_gates and self.ledger and self.engine:
            for gid in node.assigned_gates:
                gate = self.ledger.get_gate(gid)
                if gate:
                    res = self.engine.execute_gate(
                        gate,
                        ledger=self.ledger,
                        reverify=True,
                        context={
                            "run_id": self.run_id,
                            "run_epoch": self.run_epoch,
                            "node_id": node.id,
                            "attempt_id": node.attempts,
                        },
                    )
                    if res.status != "MET":
                        self.bypass_telemetry.misrouted_runs += 1
                        self.commit_transition(node, NodeStatus.READY, action="BYPASS_ESCALATED", reason=f"Gate {gid} failed in fastpath ({res.error}). Escalating.")
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

        node.result = response.to_dict()
        node.wait_metrics.time_finished = time.time()

        self.commit_transition(
            node,
            NodeStatus.ACCEPTED,
            action="ACCEPTED_FASTPATH",
            reason="Adaptive protocol fastpath verified and committed",
            response=response,
            payload={"result": response.to_dict()},
        )
        return True

    def _execute_single_node(
        self,
        node: TaskNode,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
    ) -> TaskNode:
        """Execute one node (fastpath or full protocol). Returns the node."""
        if self.enable_bypass and self.is_eligible_for_bypass(node):
            self.execute_node_fastpath(node, executor_fn=executor_fn)
        else:
            self.execute_node(node, executor_fn=executor_fn)
        return node

    def step(
        self,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
    ) -> List[TaskNode]:
        """Execute one wave of ready nodes.

        When ``max_parallel_workers > 0`` and the wave contains multiple
        nodes, dispatch them concurrently via ``ThreadPoolExecutor``.
        Otherwise fall back to sequential execution (safe default).
        """
        from dafg.observe import SpanStatus

        now = time.time()
        ready = self.get_ready_nodes()
        if not ready:
            self._last_step_time = now
            return []

        # DOF: emit ready-set signal for parallelization debugging
        self._step_counter += 1
        self._fabric.emit_event("graph.ready_nodes", {
            "count": len(ready),
            "node_ids": [n.id for n in ready],
            "step_index": self._step_counter,
        })

        waves = self.compute_waves(ready)
        current_wave = waves[0]

        executed: List[TaskNode] = []
        use_parallel = (
            self.max_parallel_workers > 0
            and len(current_wave) > 1
            and executor_fn is not None
        )

        # DOF: span around entire wave dispatch
        wave_span = self._fabric.start_span(
            name="wave.dispatch",
            trace_id=self.run_id,
            attributes={
                "step_index": self._step_counter,
                "wave_width": len(current_wave),
                "parallel": use_parallel,
                "node_ids": [n.id for n in current_wave],
            },
        )

        step_start = time.time()

        if use_parallel:
            workers = min(self.max_parallel_workers, len(current_wave))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(self._execute_single_node, node, executor_fn): node
                    for node in current_wave
                }
                for future in concurrent.futures.as_completed(futures):
                    executed.append(future.result())
        else:
            for node in current_wave:
                self._execute_single_node(node, executor_fn=executor_fn)
                executed.append(node)

        step_elapsed = time.time() - step_start

        # Update the diagnostics entry created by compute_waves
        if self.wave_diagnostics:
            diag = self.wave_diagnostics[-1]
            diag.wall_time_seconds = step_elapsed
            # Estimate serial time from individual node durations
            serial_est = sum(
                (n.wait_metrics.time_finished or 0.0) - (n.wait_metrics.time_dispatched or 0.0)
                for n in executed
                if n.wait_metrics.time_dispatched and n.wait_metrics.time_finished
            )
            diag.serial_estimate_seconds = serial_est
            diag.speedup_ratio = serial_est / step_elapsed if step_elapsed > 0 else 1.0
            diag.parallel_dispatch = use_parallel

        # DOF: close wave span + emit concurrency metric
        self._fabric.end_span(wave_span, SpanStatus.OK)
        self._fabric.emit_metric("wave.concurrency_ratio", diag.concurrency_ratio if self.wave_diagnostics else 0.0,
                                  tags={"step": str(self._step_counter)})

        self._last_step_time = now
        return executed

    def run(
        self,
        executor_fn: Optional[Callable[[TaskNode, Dict[str, Any]], AgentResponse]] = None,
        max_steps: int = 100,
    ) -> str:
        """Run DAFG until completion, failure, or budget exhaustion."""
        def _resolve_completed_status() -> OutcomeStatus:
            has_abandoned = bool(self.ledger and any(g.status == "ABANDONED" for g in self.ledger.gates.values()))
            return OutcomeStatus.HANDOFF_REQUIRED if has_abandoned else OutcomeStatus.VERIFIED_DELIVERY

        for _ in range(max_steps):
            if self.is_completed():
                self.seal_run()
                self.outcome_status = _resolve_completed_status()
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
                    self.seal_run()
                    self.outcome_status = _resolve_completed_status()
                    self.save_state()
                    return "COMPLETED"
                self.outcome_status = OutcomeStatus.INCOMPLETE_RUN
                self.save_state()
                return "BLOCKED"

        if self.is_completed():
            self.seal_run()
            self.outcome_status = _resolve_completed_status()
            self.save_state()
            return "COMPLETED"
        else:
            self.outcome_status = OutcomeStatus.INCOMPLETE_RUN
            self.save_state()
            return "BLOCKED"

    def prepare_next_generation(self, gen_number: int) -> None:
        """Reset execution state for next evolutionary generation under evolved topology."""
        from dafg.protocol import ProtocolState
        self.run_id = f"run_gen_{gen_number}_{int(time.time()*1000)}"
        self.is_sealed = False
        self.sealed_at = None
        self.run_epoch += 1
        self.processed_idempotency_keys.clear()
        self.wave_diagnostics.clear()
        self.execution_history.clear()
        self.budget.calls_consumed = 0
        self.budget.revisions_consumed = 0
        for node in self.nodes.values():
            node.status = NodeStatus.READY
            node.protocol_state = ProtocolState.IDLE
            node.active_dispatch = None
            node.epoch = self.run_epoch
            node.version = self.run_epoch
            node.attempts = 0
            node.revisions = 0
            node.evidence_ledger.clear()

    def is_completed(self) -> bool:
        """True if all nodes in graph are ACCEPTED and completion integrity holds."""
        if len(self.nodes) == 0:
            return False
        if not all(n.status == NodeStatus.ACCEPTED for n in self.nodes.values()):
            return False
        ok, _ = self.verify_completion_integrity()
        return ok

    def has_failed(self) -> bool:
        """True if any node in graph is FAILED."""
        return any(n.status == NodeStatus.FAILED for n in self.nodes.values())

    def concurrency_report(self) -> Dict[str, Any]:
        """Aggregate wave diagnostics into a concurrency health report.

        Returns a dict with:
        - avg/min/max wave-0 width
        - overall concurrency ratio
        - top OWNS: conflict pairs causing serialization
        - parallel dispatch stats (wall time vs serial estimate)
        """
        if not self.wave_diagnostics:
            return {"status": "no_data", "steps_recorded": 0}

        widths = [d.wave_0_width for d in self.wave_diagnostics]
        ratios = [d.concurrency_ratio for d in self.wave_diagnostics]
        speedups = [d.speedup_ratio for d in self.wave_diagnostics if d.speedup_ratio > 0]

        # Aggregate conflict reasons across all steps
        conflict_pairs: Dict[str, int] = {}
        for d in self.wave_diagnostics:
            for cr in d.conflict_reasons:
                key = f"{cr['deferred_node']} ↔ {cr['conflicting_node']}"
                conflict_pairs[key] = conflict_pairs.get(key, 0) + 1
        top_conflicts = sorted(conflict_pairs.items(), key=lambda x: x[1], reverse=True)[:5]

        total_wall = sum(d.wall_time_seconds for d in self.wave_diagnostics)
        total_serial = sum(d.serial_estimate_seconds for d in self.wave_diagnostics)
        parallel_steps = sum(1 for d in self.wave_diagnostics if d.parallel_dispatch)

        return {
            "steps_recorded": len(self.wave_diagnostics),
            "wave_0_width": {
                "avg": round(sum(widths) / len(widths), 2),
                "min": min(widths),
                "max": max(widths),
                "histogram": {w: widths.count(w) for w in sorted(set(widths))},
            },
            "concurrency_ratio": {
                "avg": round(sum(ratios) / len(ratios), 3),
                "min": round(min(ratios), 3),
                "max": round(max(ratios), 3),
            },
            "speedup": {
                "avg": round(sum(speedups) / len(speedups), 2) if speedups else 1.0,
                "total_wall_seconds": round(total_wall, 3),
                "total_serial_estimate_seconds": round(total_serial, 3),
                "effective_speedup": round(total_serial / total_wall, 2) if total_wall > 0 else 1.0,
            },
            "parallel_dispatch": {
                "enabled": self.max_parallel_workers > 0,
                "max_workers": self.max_parallel_workers,
                "steps_dispatched_parallel": parallel_steps,
                "steps_dispatched_serial": len(self.wave_diagnostics) - parallel_steps,
            },
            "top_serialization_conflicts": [
                {"pair": pair, "occurrences": count} for pair, count in top_conflicts
            ],
        }


    def _record_event(self, node: TaskNode, action: str, details: str) -> None:
        event_dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_id": node.id,
            "role": node.role,
            "action": action,
            "details": details,
            "revisions": node.revisions,
        }
        self.execution_history.append(event_dict)
        self._fabric.emit_event(f"node.{action.lower()}", event_dict)

    def get_wave_report(self) -> Dict[str, Any]:
        """Aggregated wave concurrency report for the current run."""
        from collections import Counter

        if not self.wave_diagnostics:
            return {"steps": 0, "avg_concurrency_ratio": 0.0, "wave_width_histogram": {},
                    "total_conflict_deferrals": 0, "top_conflict_paths": [], "avg_speedup_ratio": 1.0}

        n = len(self.wave_diagnostics)
        avg_cr = sum(d.concurrency_ratio for d in self.wave_diagnostics) / n
        avg_sr = sum(d.speedup_ratio for d in self.wave_diagnostics) / n
        histogram = dict(Counter(w for d in self.wave_diagnostics for w in d.wave_widths))

        # Top conflicting OWNS: paths across all steps
        path_counts: Dict[str, int] = {}
        all_owns = set(f for node in self.nodes.values() for f in node.owns)
        barrier_threshold = max(3, int(len(all_owns) * 0.6))

        domain_deferrals = 0
        barrier_deferrals = 0

        for d in self.wave_diagnostics:
            for cr in d.conflict_reasons:
                for p in cr.get("deferred_owns", []) + cr.get("conflicting_owns", []):
                    path_counts[p] = path_counts.get(p, 0) + 1
                def_node = self.nodes.get(cr.get("deferred_node"))
                if def_node and len(def_node.owns) >= barrier_threshold:
                    barrier_deferrals += 1
                else:
                    domain_deferrals += 1

        top_paths = sorted(path_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "steps": n,
            "avg_concurrency_ratio": round(avg_cr, 3),
            "wave_width_histogram": histogram,
            "total_conflict_deferrals": domain_deferrals + barrier_deferrals,
            "domain_deferrals": domain_deferrals,
            "barrier_deferrals": barrier_deferrals,
            "top_conflict_paths": top_paths,
            "avg_speedup_ratio": round(avg_sr, 3),
        }

    def critical_path(self) -> List[str]:
        """Longest-latency dependency chain through the executed graph.

        Uses node wall-clock duration as edge weight. Returns node IDs
        in execution order (root → leaf of the longest chain).
        """
        # Build cost per node: time_finished - time_dispatched, or 0
        cost: Dict[str, float] = {}
        for nid, node in self.nodes.items():
            wm = node.wait_metrics
            if wm.time_dispatched and wm.time_finished:
                cost[nid] = wm.time_finished - wm.time_dispatched
            else:
                cost[nid] = 0.0

        # Longest path via topological DP (O(V+E))
        dist: Dict[str, float] = {}
        pred: Dict[str, Optional[str]] = {}

        def _longest(nid: str) -> float:
            if nid in dist:
                return dist[nid]
            node = self.nodes.get(nid)
            if not node or not node.needs:
                dist[nid] = cost.get(nid, 0.0)
                pred[nid] = None
                return dist[nid]
            best_parent: Optional[str] = None
            best_val = 0.0
            for dep_id in node.needs:
                v = _longest(dep_id)
                if v >= best_val:
                    best_val = v
                    best_parent = dep_id
            dist[nid] = best_val + cost.get(nid, 0.0)
            pred[nid] = best_parent
            return dist[nid]

        for nid in self.nodes:
            _longest(nid)

        if not dist:
            return []

        # Trace back from the node with the longest distance.
        # Break ties by chain length so zero-cost chains pick the deepest leaf.
        def _chain_len(nid: str) -> int:
            length, cur = 0, nid
            while cur is not None:
                length += 1
                cur = pred.get(cur)
            return length

        end = max(dist, key=lambda nid: (dist[nid], _chain_len(nid)))  # type: ignore[arg-type]
        path: List[str] = []
        cur: Optional[str] = end
        while cur is not None:
            path.append(cur)
            cur = pred.get(cur)
        path.reverse()
        return path

    def get_run_analytics(self) -> Dict[str, Any]:
        """Comprehensive end-of-run analytics combining funnel convergence,
        wave concurrency, triad stage latencies, critical path, and budget utilization.
        """
        total_nodes = len(self.nodes)
        accepted = sum(1 for n in self.nodes.values() if n.status == NodeStatus.ACCEPTED)
        failed = sum(1 for n in self.nodes.values() if n.status == NodeStatus.FAILED)
        blocked = sum(1 for n in self.nodes.values() if n.status == NodeStatus.BLOCKED)
        pending = sum(1 for n in self.nodes.values() if n.status in (NodeStatus.PENDING, NodeStatus.READY, NodeStatus.RUNNING))
        total_revisions = sum(n.revisions for n in self.nodes.values())

        # Funnel metrics
        funnel = {
            "total_nodes": total_nodes,
            "accepted_nodes": accepted,
            "failed_nodes": failed,
            "blocked_nodes": blocked,
            "pending_nodes": pending,
            "convergence_rate": round(accepted / total_nodes, 4) if total_nodes > 0 else 0.0,
            "total_revisions": total_revisions,
            "revision_rate": round(total_revisions / total_nodes, 2) if total_nodes > 0 else 0.0,
            "outcome_status": self.outcome_status.value if isinstance(self.outcome_status, OutcomeStatus) else str(self.outcome_status),
            "is_sealed": self.is_sealed,
        }

        # Concurrency & wave metrics
        wave_rpt = self.get_wave_report()
        concurrency = {
            "steps": wave_rpt.get("steps", 0),
            "avg_concurrency_ratio": wave_rpt.get("avg_concurrency_ratio", 0.0),
            "avg_speedup_ratio": wave_rpt.get("avg_speedup_ratio", 1.0),
            "wave_width_histogram": wave_rpt.get("wave_width_histogram", {}),
            "total_conflict_deferrals": wave_rpt.get("total_conflict_deferrals", 0),
            "domain_deferrals": wave_rpt.get("domain_deferrals", 0),
            "barrier_deferrals": wave_rpt.get("barrier_deferrals", 0),
            "top_conflict_paths": wave_rpt.get("top_conflict_paths", []),
            "parallel_dispatch_enabled": self.max_parallel_workers > 0,
            "max_workers": self.max_parallel_workers,
        }

        # Triad latency telemetry
        prover_ms_total = 0.0
        verifier_ms_total = 0.0
        nodes_with_timings = 0
        for node in self.nodes.values():
            timings = node.metadata.get("_triad_timings", {})
            if timings:
                nodes_with_timings += 1
                prover_ms_total += timings.get("prover_ms", 0.0)
                verifier_ms_total += timings.get("verifier_ms", 0.0)

        total_triad_ms = prover_ms_total + verifier_ms_total
        triad = {
            "nodes_instrumented": nodes_with_timings,
            "prover_ms_total": round(prover_ms_total, 1),
            "verifier_ms_total": round(verifier_ms_total, 1),
            "total_ms": round(total_triad_ms, 1),
            "prover_share_pct": round((prover_ms_total / total_triad_ms) * 100, 1) if total_triad_ms > 0 else 0.0,
            "verifier_share_pct": round((verifier_ms_total / total_triad_ms) * 100, 1) if total_triad_ms > 0 else 0.0,
            "avg_prover_ms": round(prover_ms_total / nodes_with_timings, 1) if nodes_with_timings > 0 else 0.0,
            "avg_verifier_ms": round(verifier_ms_total / nodes_with_timings, 1) if nodes_with_timings > 0 else 0.0,
        }

        # Critical path
        crit_nodes = self.critical_path()
        crit_duration = sum(
            (self.nodes[nid].wait_metrics.time_finished or 0.0) - (self.nodes[nid].wait_metrics.time_dispatched or 0.0)
            for nid in crit_nodes
            if nid in self.nodes and self.nodes[nid].wait_metrics.time_dispatched and self.nodes[nid].wait_metrics.time_finished
        )
        critical_path_info = {
            "chain": crit_nodes,
            "length": len(crit_nodes),
            "duration_seconds": round(crit_duration, 3),
        }

        # Budget utilization
        budget = {
            "calls": f"{self.budget.calls_consumed}/{self.budget.max_calls}",
            "nodes": f"{self.budget.nodes_created}/{self.budget.max_nodes}",
            "revisions": f"{self.budget.revisions_consumed}/{self.budget.max_revisions}",
            "adaptations": f"{self.budget.adaptations_consumed}/{self.budget.max_adaptations}",
            "calls_pct": round((self.budget.calls_consumed / self.budget.max_calls) * 100, 1) if self.budget.max_calls else 0.0,
            "nodes_pct": round((self.budget.nodes_created / self.budget.max_nodes) * 100, 1) if self.budget.max_nodes else 0.0,
        }

        # Gates
        gates_info: Dict[str, Any] = {"available": False}
        if self.ledger:
            g_total = len(self.ledger.gates)
            g_met = sum(1 for g in self.ledger.gates.values() if g.status == "MET")
            g_pending = sum(1 for g in self.ledger.gates.values() if g.status == "PENDING")
            g_abandoned = sum(1 for g in self.ledger.gates.values() if g.status == "ABANDONED")
            r_proof = sum(
                1 for g in self.ledger.gates.values()
                if classify_evidence(g) in (EvidenceStrength.EXECUTABLE_PROOF, EvidenceStrength.STRING_MATCH)
            )
            cov_pct = round((r_proof / g_total) * 100.0, 1) if g_total > 0 else 0.0
            gates_info = {
                "available": True,
                "total": g_total,
                "met": g_met,
                "pending": g_pending,
                "abandoned": g_abandoned,
                "pass_rate": round(g_met / g_total, 4) if g_total > 0 else 0.0,
                "evidence_coverage": cov_pct,
                "coverage_pct": cov_pct,
            }
        elif self.gate_states:
            g_total = len(self.gate_states)
            g_met = sum(1 for g in self.gate_states.values() if g.get("status") == "MET")
            r_proof = sum(
                1 for g in self.gate_states.values()
                if "exit_code=0" in str(g.get("evidence") or "")
            )
            cov_pct = round((r_proof / g_total) * 100.0, 1) if g_total > 0 else 0.0
            gates_info = {
                "available": True,
                "total": g_total,
                "met": g_met,
                "pass_rate": round(g_met / g_total, 4) if g_total > 0 else 0.0,
                "evidence_coverage": cov_pct,
                "coverage_pct": cov_pct,
            }


        base_analytics = {
            "run_id": self.run_id,
            "funnel": funnel,
            "concurrency": concurrency,
            "triad": triad,
            "critical_path": critical_path_info,
            "budget": budget,
            "gates": gates_info,
        }
        from dafg.judge import RunJudge
        base_analytics["quality"] = RunJudge.evaluate_from_analytics(base_analytics, raw_graph=self).to_dict()
        return base_analytics

    def format_analytics_report(self) -> str:
        """Render a clean, human-readable terminal report of run analytics."""
        a = self.get_run_analytics()
        f = a["funnel"]
        c = a["concurrency"]
        t = a["triad"]
        cp = a["critical_path"]
        b = a["budget"]
        g = a["gates"]

        lines = [
            "=" * 70,
            "                     DAFG RUN ANALYTICS & FUNNEL",
            "=" * 70,
            f"  Run ID: {a['run_id']} | Outcome: {f['outcome_status']} | Sealed: {f['is_sealed']}",
            "-" * 70,
            "  FUNNEL CONVERGENCE",
            f"    Nodes: {f['total_nodes']} total | {f['accepted_nodes']} accepted ({f['convergence_rate']*100:.1f}%) | {f['failed_nodes']} failed | {f['blocked_nodes']} blocked",
        ]
        if g.get("available"):
            lines.append(f"    Gates: {g['total']} total | {g['met']} MET ({g.get('pass_rate', 0.0)*100:.1f}%) | {g.get('pending', 0)} pending | {g.get('abandoned', 0)} abandoned")
        lines.append(f"    Revisions: {f['total_revisions']} across {f['total_nodes']} nodes ({f['revision_rate']:.2f} rev/node)")

        lines.extend([
            "-" * 70,
            "  CONCURRENCY & THROUGHPUT",
            f"    Steps: {c['steps']} | Concurrency Ratio: {c['avg_concurrency_ratio']:.3f} | Speedup: {c['avg_speedup_ratio']:.2f}x",
            f"    Wave Widths: {c['wave_width_histogram']} | Workers: {c['max_workers']} (Parallel: {c['parallel_dispatch_enabled']})",
            f"    Serialization Conflicts: {c['total_conflict_deferrals']}",
        ])
        if c.get("top_conflict_paths"):
            top_strs = [f"{p} ({cnt}x)" for p, cnt in c["top_conflict_paths"][:3]]
            lines.append(f"    Top Conflicting Paths: {', '.join(top_strs)}")

        if t["nodes_instrumented"] > 0:
            lines.extend([
                "-" * 70,
                "  TRIAD LATENCIES",
                f"    Prover (Synthesis): {t['prover_ms_total']:.1f}ms ({t['prover_share_pct']:.1f}%) | Avg: {t['avg_prover_ms']:.1f}ms",
                f"    Verifier (Gates):   {t['verifier_ms_total']:.1f}ms ({t['verifier_share_pct']:.1f}%) | Avg: {t['avg_verifier_ms']:.1f}ms",
                f"    Total Triad Time:   {t['total_ms']:.1f}ms across {t['nodes_instrumented']} nodes",
            ])

        if cp["length"] > 0:
            chain_str = " -> ".join(cp["chain"])
            lines.extend([
                "-" * 70,
                "  CRITICAL PATH",
                f"    Chain ({cp['length']} nodes): {chain_str}",
                f"    Total Chain Duration: {cp['duration_seconds']:.2f}s",
            ])

        lines.extend([
            "-" * 70,
            "  BUDGET UTILIZATION",
            f"    Calls: {b['calls']} ({b['calls_pct']}%) | Nodes: {b['nodes']} ({b['nodes_pct']}%) | Revisions: {b['revisions']}",
            "=" * 70,
        ])
        if "quality" in a:
            from dafg.judge import RunJudge
            report = RunJudge.evaluate_from_analytics(a, raw_graph=self)
            lines.append("")
            lines.append(report.format_report())
        return "\n".join(lines)

    def _reconcile_state(self, canonical: Dict[str, Any]) -> None:
        """Reconcile local mutations with canonical on-disk state on CAS conflict."""
        self.state_version = int(canonical.get("state_version", self.state_version))
        self.is_sealed = bool(canonical.get("is_sealed", self.is_sealed))
        if canonical.get("sealed_at"):
            self.sealed_at = canonical.get("sealed_at")

        # Merge budget consumption (monotonic maximums)
        canon_budget = canonical.get("budget", {})
        self.budget.calls_consumed = max(self.budget.calls_consumed, canon_budget.get("calls_consumed", 0))
        self.budget.nodes_created = max(self.budget.nodes_created, canon_budget.get("nodes_created", 0))
        self.budget.revisions_consumed = max(self.budget.revisions_consumed, canon_budget.get("revisions_consumed", 0))
        self.budget.adaptations_consumed = max(self.budget.adaptations_consumed, canon_budget.get("adaptations_consumed", 0))

        # Merge idempotency keys, domain events, and audit log
        self.processed_idempotency_keys.update(canonical.get("processed_idempotency_keys", []))
        for item in canonical.get("audit_log", []):
            if item not in self.audit_log:
                self.audit_log.append(item)
        for item in canonical.get("domain_events", []):
            if item not in self.domain_events:
                self.domain_events.append(item)

        # Merge nodes
        for nid, n_data in canonical.get("nodes", {}).items():
            if nid not in self.nodes:
                self.nodes[nid] = TaskNode.from_dict(n_data)
            else:
                local_node = self.nodes[nid]
                canon_node = TaskNode.from_dict(n_data)
                # If canonical node has made further progress or is terminal, adopt it
                if canon_node.attempts > local_node.attempts or canon_node.revisions > local_node.revisions:
                    self.nodes[nid] = canon_node
                elif canon_node.status in (NodeStatus.ACCEPTED, NodeStatus.FAILED) and local_node.status not in (NodeStatus.ACCEPTED, NodeStatus.FAILED):
                    self.nodes[nid] = canon_node

        # Merge gate states
        canon_gates = canonical.get("gate_states", {})
        for gid, g_state in canon_gates.items():
            if gid not in self.gate_states:
                self.gate_states[gid] = g_state
            elif isinstance(g_state, dict) and g_state.get("status") == "MET":
                self.gate_states[gid] = g_state
            if self.ledger and gid in self.ledger.gates:
                if isinstance(g_state, dict) and g_state.get("status") == "MET" and self.ledger.gates[gid].status != "MET":
                    self.ledger.gates[gid].status = "MET"
                    self.ledger.gates[gid].evidence = g_state.get("evidence")

    def save_state(self, expected_version: Optional[int] = None, max_retries: int = 10) -> None:
        if not self.state_path:
            return

        is_auto_cas = expected_version is None
        target_version = self.state_version if is_auto_cas else expected_version

        for attempt in range(max_retries + 1):
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
                "state_version": self.state_version,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": self.run_id,
                "run_epoch": self.run_epoch,
                "is_sealed": self.is_sealed,
                "sealed_at": self.sealed_at,
                "outcome_status": self.outcome_status.value if isinstance(self.outcome_status, OutcomeStatus) else self.outcome_status,
                "intermediate_false_acceptances": self.intermediate_false_acceptances,
                "budget": {
                    "max_calls": self.budget.max_calls,
                    "max_nodes": self.budget.max_nodes,
                    "max_revisions": self.budget.max_revisions,
                    "max_adaptations": self.budget.max_adaptations,
                    "deadline": self.budget.deadline,
                    "calls_consumed": self.budget.calls_consumed,
                    "nodes_created": self.budget.nodes_created,
                    "revisions_consumed": self.budget.revisions_consumed,
                    "adaptations_consumed": self.budget.adaptations_consumed,
                },
                "contracts": {cid: c.to_dict() for cid, c in self.contracts.items()},
                "bypass_policy": self.bypass_policy.to_dict(),
                "bypass_telemetry": self.bypass_telemetry.to_dict(),
                "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
                "gate_states": gate_states,
                "wave_diagnostics": [d.to_dict() for d in self.wave_diagnostics],
                "analytics": self.get_run_analytics(),
                "execution_history": self.execution_history,
                "domain_events": self.domain_events,
                "audit_log": self.audit_log,
                "processed_idempotency_keys": list(self.processed_idempotency_keys),
            }
            try:
                self.state_version = StateStore.commit(
                    self.state_path,
                    state,
                    expected_version=target_version,
                )
                self._fabric.emit_metric("state.persisted", 1.0)
                return
            except OptimisticConcurrencyConflictError as e:
                if not is_auto_cas or attempt >= max_retries:
                    raise e
                # Jittered backoff to alleviate thundering herd across OS processes
                import random
                time.sleep((0.005 + random.uniform(0.001, 0.01)) * (1.5 ** min(attempt, 4)))
                canonical = StateStore.load(self.state_path)
                self._reconcile_state(canonical)
                target_version = self.state_version

    @classmethod
    def load_state(
        cls,
        state_path: Union[str, Path],
        ledger: Optional[GateLedger] = None,
        engine: Optional[GateEngine] = None,
        probes: Optional[list] = None,
    ) -> DAFG:
        data = StateStore.load(state_path)
        b_data = data.get("budget", {})
        budget = Budget(
            max_calls=b_data.get("max_calls", 50),
            max_nodes=b_data.get("max_nodes", 20),
            max_revisions=b_data.get("max_revisions", 3),
            max_adaptations=b_data.get("max_adaptations", 15),
            deadline=b_data.get("deadline"),
            calls_consumed=b_data.get("calls_consumed", 0),
            nodes_created=b_data.get("nodes_created", 0),
            revisions_consumed=b_data.get("revisions_consumed", 0),
            adaptations_consumed=b_data.get("adaptations_consumed", 0),
        )

        had_interrupted_nodes = False
        nodes: Dict[str, TaskNode] = {}
        for nid, ndict in data.get("nodes", {}).items():
            node = TaskNode.from_dict(ndict)
            if node.status == NodeStatus.RUNNING:
                had_interrupted_nodes = True
                node.status = NodeStatus.PENDING
                node.active_dispatch = None
                node.attempts += 1
            nodes[nid] = node

        dafg = cls(
            nodes=None,
            budget=budget,
            ledger=ledger,
            engine=engine,
            state_path=state_path,
            probes=probes,
        )
        dafg.is_sealed = data.get("is_sealed", False)
        dafg.state_version = int(data.get("state_version", 0))
        dafg.sealed_at = data.get("sealed_at")
        dafg.processed_idempotency_keys = set(data.get("processed_idempotency_keys", []))
        dafg.domain_events = list(data.get("domain_events", []))
        dafg.audit_log = list(data.get("audit_log", []))
        dafg.execution_history = list(data.get("execution_history", []))
        dafg.gate_states = dict(data.get("gate_states", {}))
        dafg.intermediate_false_acceptances = data.get("intermediate_false_acceptances", 0)
        ost = data.get("outcome_status", OutcomeStatus.INCOMPLETE_RUN.value)
        dafg.outcome_status = OutcomeStatus(ost) if ost in [e.value for e in OutcomeStatus] else OutcomeStatus.INCOMPLETE_RUN

        saved_epoch = data.get("run_epoch", 1)
        if had_interrupted_nodes:
            dafg.run_epoch = saved_epoch + 1
            for n in nodes.values():
                if n.status == NodeStatus.PENDING and n.active_dispatch is None:
                    n.epoch = dafg.run_epoch
            dafg.domain_events.append({
                "type": "RECOVERED_FROM_INTERRUPTION",
                "previous_epoch": saved_epoch,
                "new_epoch": dafg.run_epoch,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            dafg.run_epoch = saved_epoch

        # Restore contracts
        for cid, cdata in data.get("contracts", {}).items():
            dafg.contracts[cid] = InterfaceContract.from_dict(cdata)

        # Restore bypass state
        if "bypass_policy" in data:
            dafg.bypass_policy = BypassPolicy.from_dict(data["bypass_policy"])
        if "bypass_telemetry" in data:
            dafg.bypass_telemetry = BypassTelemetry.from_dict(data["bypass_telemetry"])

        # Restore wave diagnostics
        if "wave_diagnostics" in data:
            dafg.wave_diagnostics = [WaveDiagnostics.from_dict(d) for d in data["wave_diagnostics"]]

        # Restore gate states into ledger if provided
        if ledger and dafg.gate_states:
            for gid, gst in dafg.gate_states.items():
                if gid in ledger.gates:
                    g = ledger.gates[gid]
                    if g.status not in ("MET", "ABANDONED"):
                        g.status = gst.get("status", g.status)
                    if not g.evidence and gst.get("evidence"):
                        g.evidence = gst.get("evidence")
                    if not g.abandon_reason and gst.get("abandon_reason"):
                        g.abandon_reason = gst.get("abandon_reason")

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

        if had_interrupted_nodes:
            dafg.save_state()
        return dafg

    @classmethod
    def replay(
        cls,
        events: List[Union[DomainEvent, Dict[str, Any]]],
        initial_checkpoint: Optional[Dict[str, Any]] = None,
        ledger: Optional[GateLedger] = None,
        engine: Optional[GateEngine] = None,
    ) -> DAFG:
        """Reconstruct exact canonical protocol state deterministically via ProtocolReducer.
        
        Purely applies domain events without live agent calls, tools, or side effects.
        """
        if initial_checkpoint:
            import tempfile
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
                json.dump(initial_checkpoint, f)
                tmp_path = f.name
            try:
                graph = cls.load_state(tmp_path, ledger=ledger, engine=engine)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        else:
            graph = cls(ledger=ledger, engine=engine)

        for ev_raw in events:
            ev = ev_raw if isinstance(ev_raw, DomainEvent) else DomainEvent.from_dict(ev_raw)
            nid = ev.node_id
            if nid and nid not in graph.nodes:
                graph.nodes[nid] = TaskNode(
                    id=nid,
                    title=ev.payload.get("title", f"Node {nid}"),
                    role=ev.payload.get("role", "coder"),
                )
            ProtocolReducer.apply(graph, ev)
            graph.domain_events.append(ev.to_dict())

        return graph
