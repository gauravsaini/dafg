"""DAFG Formal Protocol Engine & Reducer.

Implements the two-dimensional state machine:
- ProtocolState: Authoritative reasoning and evidence lifecycle
- ExecutionStatus: Scheduler and worker execution projection

Pure transition decision logic (decide) and deterministic event reducer (apply).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


class ProtocolState(str, Enum):
    """Authoritative reasoning, verification, and artifact lifecycle state."""
    IDLE = "IDLE"
    CONTEXT_LOADED = "CONTEXT_LOADED"
    PROVING = "PROVING"
    CHALLENGING = "CHALLENGING"
    VERIFYING = "VERIFYING"
    REVISING = "REVISING"
    STALE = "STALE"
    ACCEPTED = "ACCEPTED"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"


class ExecutionStatus(str, Enum):
    """Scheduler and dispatch lifecycle projection."""
    READY = "READY"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_IO = "WAITING_IO"
    BLOCKED = "BLOCKED"
    SETTLED = "SETTLED"


class Action(str, Enum):
    """Action selecting an allowed protocol transition."""
    LOAD_CONTEXT = "LOAD_CONTEXT"
    DISPATCH_PROVE = "DISPATCH_PROVE"
    DISPATCH_FASTPATH = "DISPATCH_FASTPATH"
    SUBMIT_PROPOSAL = "SUBMIT_PROPOSAL"
    CHALLENGE = "CHALLENGE"
    SUBMIT_EVIDENCE = "SUBMIT_EVIDENCE"
    ACCEPT_VERDICT = "ACCEPT_VERDICT"
    REVISE = "REVISE"
    INVALIDATE = "INVALIDATE"
    REJECT = "REJECT"
    DEGRADE = "DEGRADE"
    REFUSE = "REFUSE"
    SEAL_RUN = "SEAL_RUN"
    BLOCK = "BLOCK"
    FAIL = "FAIL"
    HALT = "HALT"
    REOPEN = "REOPEN"


class IllegalTransitionError(Exception):
    """Raised when an illegal or guard-violating node transition is attempted."""
    pass


class StaleDispatchError(IllegalTransitionError):
    """Raised when an action carries an obsolete, mismatched, or future dispatch identity."""
    pass


class RunSealedError(IllegalTransitionError):
    """Raised when attempting a state-modifying action on a sealed graph run."""
    pass


@dataclass(frozen=True)
class DispatchIdentity:
    """Immutable dispatch token binding an execution attempt to its exact context snapshot."""
    run_id: str
    node_id: str
    epoch: int
    attempt_id: int
    context_snapshot_id: str
    contract_version: int
    artifact_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DispatchIdentity:
        return cls(**data)


@dataclass
class DomainEvent:
    """Canonical domain event emitted on valid state transitions."""
    event_id: int
    seq: int
    timestamp: str
    event_type: str
    run_id: str
    node_id: Optional[str]
    from_state: Optional[str]
    to_state: Optional[str]
    epoch: int
    action: str
    idempotency_key: str
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DomainEvent:
        return cls(**data)


@dataclass
class AuditRecord:
    """Record of rejected, prohibited, or warning transitions."""
    timestamp: str
    idempotency_key: str
    action: str
    node_id: Optional[str]
    reason: str
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProtocolCommand:
    """Proposed transition command submitted to ProtocolEngine."""
    idempotency_key: str
    action: Action
    node_id: str
    run_id: str
    dispatch_identity: Optional[DispatchIdentity] = None
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.dispatch_identity, dict):
            self.dispatch_identity = DispatchIdentity.from_dict(self.dispatch_identity)


def state_projection(p_state: ProtocolState) -> ExecutionStatus:
    """Map authoritative ProtocolState to scheduler ExecutionStatus."""
    if p_state == ProtocolState.IDLE:
        return ExecutionStatus.READY
    elif p_state == ProtocolState.CONTEXT_LOADED:
        return ExecutionStatus.READY
    elif p_state in (ProtocolState.PROVING, ProtocolState.CHALLENGING):
        return ExecutionStatus.RUNNING
    elif p_state == ProtocolState.VERIFYING:
        return ExecutionStatus.WAITING_IO
    elif p_state in (ProtocolState.REVISING, ProtocolState.STALE):
        return ExecutionStatus.BLOCKED
    elif p_state in (ProtocolState.ACCEPTED, ProtocolState.DEGRADED, ProtocolState.REJECTED):
        return ExecutionStatus.SETTLED
    return ExecutionStatus.BLOCKED


class ProtocolEngine:
    """Pure decision engine for validating commands against rules and guards."""

    # Map of (source_state, action) -> target_state
    TRANSITION_MAP: Dict[Tuple[ProtocolState, Action], ProtocolState] = {
        # --- Original reasoning lifecycle ---
        (ProtocolState.IDLE, Action.LOAD_CONTEXT): ProtocolState.CONTEXT_LOADED,
        (ProtocolState.IDLE, Action.DISPATCH_PROVE): ProtocolState.PROVING,
        (ProtocolState.IDLE, Action.DISPATCH_FASTPATH): ProtocolState.PROVING,
        (ProtocolState.IDLE, Action.BLOCK): ProtocolState.IDLE,
        (ProtocolState.CONTEXT_LOADED, Action.DISPATCH_PROVE): ProtocolState.PROVING,
        (ProtocolState.CONTEXT_LOADED, Action.DISPATCH_FASTPATH): ProtocolState.PROVING,
        (ProtocolState.CONTEXT_LOADED, Action.REFUSE): ProtocolState.REJECTED,
        (ProtocolState.CONTEXT_LOADED, Action.DEGRADE): ProtocolState.DEGRADED,
        (ProtocolState.CONTEXT_LOADED, Action.BLOCK): ProtocolState.IDLE,
        (ProtocolState.PROVING, Action.SUBMIT_PROPOSAL): ProtocolState.VERIFYING,
        (ProtocolState.PROVING, Action.CHALLENGE): ProtocolState.CHALLENGING,
        (ProtocolState.PROVING, Action.REJECT): ProtocolState.REJECTED,
        (ProtocolState.PROVING, Action.REVISE): ProtocolState.REVISING,
        (ProtocolState.PROVING, Action.ACCEPT_VERDICT): ProtocolState.ACCEPTED,
        (ProtocolState.PROVING, Action.BLOCK): ProtocolState.IDLE,
        (ProtocolState.PROVING, Action.FAIL): ProtocolState.REJECTED,
        (ProtocolState.PROVING, Action.HALT): ProtocolState.IDLE,
        (ProtocolState.PROVING, Action.DISPATCH_PROVE): ProtocolState.PROVING,
        (ProtocolState.PROVING, Action.DISPATCH_FASTPATH): ProtocolState.PROVING,
        (ProtocolState.CHALLENGING, Action.SUBMIT_EVIDENCE): ProtocolState.VERIFYING,
        (ProtocolState.CHALLENGING, Action.REVISE): ProtocolState.REVISING,
        (ProtocolState.CHALLENGING, Action.BLOCK): ProtocolState.IDLE,
        (ProtocolState.VERIFYING, Action.ACCEPT_VERDICT): ProtocolState.ACCEPTED,
        (ProtocolState.VERIFYING, Action.REVISE): ProtocolState.REVISING,
        (ProtocolState.VERIFYING, Action.REJECT): ProtocolState.REJECTED,
        (ProtocolState.VERIFYING, Action.BLOCK): ProtocolState.IDLE,
        (ProtocolState.REVISING, Action.LOAD_CONTEXT): ProtocolState.CONTEXT_LOADED,
        (ProtocolState.REVISING, Action.DISPATCH_PROVE): ProtocolState.PROVING,
        (ProtocolState.REVISING, Action.REJECT): ProtocolState.REJECTED,
        (ProtocolState.STALE, Action.LOAD_CONTEXT): ProtocolState.CONTEXT_LOADED,
        (ProtocolState.STALE, Action.DISPATCH_PROVE): ProtocolState.PROVING,

        # --- Gap #1: Active-state invalidation (upstream cascade) ---
        (ProtocolState.ACCEPTED, Action.INVALIDATE): ProtocolState.STALE,
        (ProtocolState.DEGRADED, Action.INVALIDATE): ProtocolState.STALE,
        (ProtocolState.PROVING, Action.INVALIDATE): ProtocolState.STALE,
        (ProtocolState.CHALLENGING, Action.INVALIDATE): ProtocolState.STALE,
        (ProtocolState.VERIFYING, Action.INVALIDATE): ProtocolState.STALE,

        # --- ACCEPTED repair transitions (epoch bump required) ---
        (ProtocolState.ACCEPTED, Action.REJECT): ProtocolState.REJECTED,
        (ProtocolState.ACCEPTED, Action.BLOCK): ProtocolState.IDLE,
        (ProtocolState.ACCEPTED, Action.REVISE): ProtocolState.REVISING,

        # --- Gap #2: REJECTED reopening (repair path) ---
        (ProtocolState.REJECTED, Action.REOPEN): ProtocolState.IDLE,
        (ProtocolState.REJECTED, Action.LOAD_CONTEXT): ProtocolState.CONTEXT_LOADED,
        (ProtocolState.REJECTED, Action.DISPATCH_PROVE): ProtocolState.PROVING,
        (ProtocolState.REJECTED, Action.FAIL): ProtocolState.REJECTED,
        (ProtocolState.REJECTED, Action.REVISE): ProtocolState.REVISING,
    }

    @classmethod
    def decide(
        cls,
        graph_snapshot: Any,
        cmd: ProtocolCommand,
        seq_generator: Callable[[], int],
    ) -> Tuple[List[DomainEvent], Optional[AuditRecord]]:
        """Pure evaluation function generating domain events or audit rejections."""
        # 1. Sealed run invariant
        if getattr(graph_snapshot, "is_sealed", False):
            record = AuditRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                idempotency_key=cmd.idempotency_key,
                action=cmd.action.value,
                node_id=cmd.node_id,
                reason="Run is sealed; all state transitions are strictly prohibited.",
            )
            return [], record

        # 2. Graph seal action
        if cmd.action == Action.SEAL_RUN:
            ok, errors = graph_snapshot.verify_completion_integrity()
            if not ok:
                record = AuditRecord(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    idempotency_key=cmd.idempotency_key,
                    action=cmd.action.value,
                    node_id=None,
                    reason=f"Cannot seal run: completion integrity check failed ({errors})",
                )
                return [], record

            event = DomainEvent(
                event_id=seq_generator(),
                seq=seq_generator(),
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="RUN_SEALED",
                run_id=cmd.run_id,
                node_id=None,
                from_state=None,
                to_state="SEALED",
                epoch=getattr(graph_snapshot, "run_epoch", 1),
                action=cmd.action.value,
                idempotency_key=cmd.idempotency_key,
                reason=cmd.reason or "Graph completion integrity verified and sealed",
                payload=cmd.payload,
            )
            return [event], None

        node = graph_snapshot.nodes.get(cmd.node_id)
        if not node:
            record = AuditRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                idempotency_key=cmd.idempotency_key,
                action=cmd.action.value,
                node_id=cmd.node_id,
                reason=f"Node '{cmd.node_id}' does not exist in graph",
            )
            return [], record

        current_p_state = getattr(node, "protocol_state", ProtocolState.IDLE)
        if isinstance(current_p_state, str):
            current_p_state = ProtocolState(current_p_state)

        # 3. Transition rule lookup
        rule_key = (current_p_state, cmd.action)
        if rule_key not in cls.TRANSITION_MAP:
            record = AuditRecord(
                timestamp=datetime.now(timezone.utc).isoformat(),
                idempotency_key=cmd.idempotency_key,
                action=cmd.action.value,
                node_id=cmd.node_id,
                reason=f"Prohibited transition rule: ({current_p_state.value}, {cmd.action.value}) has no valid target",
            )
            return [], record

        target_p_state = cls.TRANSITION_MAP[rule_key]

        # 4. Dispatch Identity Fencing for verdict actions
        if cmd.action == Action.ACCEPT_VERDICT:
            active_dispatch_raw = getattr(node, "active_dispatch", None)
            active_dispatch: Optional[DispatchIdentity] = (
                DispatchIdentity.from_dict(active_dispatch_raw)
                if isinstance(active_dispatch_raw, dict)
                else active_dispatch_raw
            )
            # If both sides carry dispatch identity, enforce exact fencing.
            # If neither side has one (legacy path), skip fencing.
            if active_dispatch and cmd.dispatch_identity:
                if (
                    cmd.dispatch_identity.run_id != active_dispatch.run_id
                    or cmd.dispatch_identity.node_id != active_dispatch.node_id
                    or cmd.dispatch_identity.epoch != active_dispatch.epoch
                    or cmd.dispatch_identity.attempt_id != active_dispatch.attempt_id
                    or cmd.dispatch_identity.context_snapshot_id != active_dispatch.context_snapshot_id
                    or cmd.dispatch_identity.contract_version != active_dispatch.contract_version
                ):
                    record = AuditRecord(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        idempotency_key=cmd.idempotency_key,
                        action=cmd.action.value,
                        node_id=cmd.node_id,
                        reason=(
                            f"Dispatch identity mismatch: proposal={cmd.dispatch_identity} "
                            f"!= active={active_dispatch}"
                        ),
                    )
                    return [], record

        # 5. Guard evaluation for ACCEPT_VERDICT
        if cmd.action == Action.ACCEPT_VERDICT:
            # Check gate evidence
            if node.assigned_gates and getattr(graph_snapshot, "ledger", None):
                for gid in node.assigned_gates:
                    g = graph_snapshot.ledger.get_gate(gid)
                    if not g:
                        record = AuditRecord(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            idempotency_key=cmd.idempotency_key,
                            action=cmd.action.value,
                            node_id=cmd.node_id,
                            reason=f"Gate '{gid}' not found in ledger",
                        )
                        return [], record
                    if g.status == "ABANDONED":
                        if not getattr(g, 'abandon_reason', None) or not g.abandon_reason.strip():
                            record = AuditRecord(
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                idempotency_key=cmd.idempotency_key,
                                action=cmd.action.value,
                                node_id=cmd.node_id,
                                reason=f"Gate '{gid}' is ABANDONED without justification",
                            )
                            return [], record
                        continue  # Valid abandonment — skip evidence check
                    if g.status != "MET":
                        record = AuditRecord(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            idempotency_key=cmd.idempotency_key,
                            action=cmd.action.value,
                            node_id=cmd.node_id,
                            reason=f"Gate '{gid}' is not MET in ledger",
                        )
                        return [], record
                    if not g.evidence or "exit_code=0" not in g.evidence:
                        record = AuditRecord(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            idempotency_key=cmd.idempotency_key,
                            action=cmd.action.value,
                            node_id=cmd.node_id,
                            reason=f"Gate '{gid}' has no verified exit_code=0 evidence",
                        )
                        return [], record

        # 6. Guard evaluation for INVALIDATE
        # Invalidation is ALWAYS allowed and never blocked by budget
        epoch_to_record = node.epoch + 1 if cmd.action == Action.INVALIDATE else node.epoch

        event = DomainEvent(
            event_id=seq_generator(),
            seq=seq_generator(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=f"NODE_{cmd.action.value}",
            run_id=cmd.run_id,
            node_id=cmd.node_id,
            from_state=current_p_state.value,
            to_state=target_p_state.value,
            epoch=epoch_to_record,
            action=cmd.action.value,
            idempotency_key=cmd.idempotency_key,
            reason=cmd.reason,
            payload=cmd.payload,
        )
        return [event], None


class ProtocolReducer:
    """Pure state reducer applying domain events to update graph state deterministically."""

    @staticmethod
    def apply(graph: Any, event: DomainEvent) -> None:
        """Apply a single domain event to graph state."""
        if event.event_type == "RUN_SEALED":
            graph.is_sealed = True
            graph.sealed_at = event.timestamp
            graph.outcome_status = "VERIFIED_DELIVERY"
            return

        if not event.node_id:
            return

        node = graph.nodes.get(event.node_id)
        if not node:
            return

        if event.to_state:
            node.protocol_state = ProtocolState(event.to_state)
            node.execution_status = state_projection(node.protocol_state)
            node.epoch = event.epoch

        if event.action == Action.INVALIDATE.value:
            # Preserve history, mark stale
            node.epoch = event.epoch
            node.revisions += 1
            node.active_dispatch = None

        elif event.action in (Action.DISPATCH_PROVE.value, Action.DISPATCH_FASTPATH.value):
            if "dispatch_identity" in event.payload:
                node.active_dispatch = DispatchIdentity.from_dict(event.payload["dispatch_identity"])
            if hasattr(node, "wait_metrics"):
                node.wait_metrics.time_dispatched = datetime.now(timezone.utc).timestamp()

        elif event.action == Action.ACCEPT_VERDICT.value:
            node.active_dispatch = None
            if hasattr(node, "wait_metrics"):
                node.wait_metrics.time_finished = datetime.now(timezone.utc).timestamp()
            if "result" in event.payload:
                node.result = event.payload["result"]

        elif event.action in (Action.REVISE.value, Action.REJECT.value):
            node.revisions += 1
            node.active_dispatch = None

        elif event.action == Action.BLOCK.value:
            node.active_dispatch = None

        elif event.action == Action.FAIL.value:
            node.revisions += 1
            node.active_dispatch = None

        elif event.action == Action.HALT.value:
            node.active_dispatch = None

        elif event.action == Action.REOPEN.value:
            node.revisions += 1
            node.active_dispatch = None

        # Synchronize legacy NodeStatus if the node carries it
        if hasattr(node, "status"):
            _PROTOCOL_TO_NODE_STATUS = {
                ProtocolState.IDLE: "PENDING",
                ProtocolState.CONTEXT_LOADED: "READY",
                ProtocolState.PROVING: "RUNNING",
                ProtocolState.CHALLENGING: "RUNNING",
                ProtocolState.VERIFYING: "RUNNING",
                ProtocolState.REVISING: "REJECTED",
                ProtocolState.STALE: "READY",
                ProtocolState.ACCEPTED: "ACCEPTED",
                ProtocolState.DEGRADED: "ACCEPTED",
                ProtocolState.REJECTED: "REJECTED",
            }
            p_state = node.protocol_state
            if isinstance(p_state, str):
                try:
                    p_state = ProtocolState(p_state)
                except ValueError:
                    p_state = None
            if p_state and p_state in _PROTOCOL_TO_NODE_STATUS:
                node_status_str = _PROTOCOL_TO_NODE_STATUS[p_state]
                # Import NodeStatus dynamically to avoid circular imports
                status_type = type(node.status)
                try:
                    node.status = status_type(node_status_str)
                except (ValueError, KeyError):
                    pass  # Leave as-is if enum doesn't have this value

        # Track processed idempotency keys
        if hasattr(graph, "processed_idempotency_keys"):
            graph.processed_idempotency_keys.add(event.idempotency_key)
