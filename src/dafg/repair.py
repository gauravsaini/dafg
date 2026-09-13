"""Closed-Loop Repair Engine.

Orchestrates verify → diagnose → patch → re-verify for failing gates.
Integrates with DAFG's existing budget, failure classification, and persona machinery.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class RepairStatus(str, Enum):
    REPAIRED = "REPAIRED"
    FAILED = "FAILED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    SKIPPED = "SKIPPED"


@dataclass
class RepairAttempt:
    attempt_num: int
    diagnosis: str         # Failure classification string
    patch_description: str # What the repair_fn reported doing
    pre_status: str        # Gate status before repair
    post_status: str       # Gate status after re-verify
    duration_ms: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RepairResult:
    gate_id: str
    final_status: RepairStatus
    attempts: int
    attempt_history: List[RepairAttempt] = field(default_factory=list)
    budget_consumed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['attempt_history'] = [a.to_dict() for a in self.attempt_history]
        return d


@dataclass
class RepairBudget:
    max_repair_attempts: int = 3
    repair_attempts_consumed: int = 0

    def can_attempt(self) -> bool:
        return self.repair_attempts_consumed < self.max_repair_attempts

    def consume(self) -> None:
        self.repair_attempts_consumed += 1
        if not self.can_attempt() and self.repair_attempts_consumed > self.max_repair_attempts:
            pass  # Just let it be checked next time


class RepairDiagnoser:
    """Classifies gate failures to guide repair strategy."""

    @staticmethod
    def diagnose(gate_result) -> str:
        """Classify a gate failure from its GateResult.
        
        Returns a diagnosis string describing the failure type.
        """
        if gate_result.status == "MET":
            return "NO_FAILURE"
        
        error = gate_result.error or ""
        
        if "timed out" in error.lower() or "timeout" in error.lower():
            return "TIMEOUT"
        if gate_result.exit_code is not None and gate_result.exit_code != 0:
            return f"EXIT_CODE_{gate_result.exit_code}"
        if "match" in error.lower() or "expect" in error.lower():
            return "OUTPUT_MISMATCH"
        if "unapproved" in error.lower():
            return "UNAPPROVED"
        if "exception" in error.lower():
            return "EXECUTION_ERROR"
        return "UNKNOWN_FAILURE"


class RepairLoop:
    """Orchestrates the verify → diagnose → patch → re-verify cycle."""

    def __init__(
        self,
        ledger,           # GateLedger
        engine,           # GateEngine  
        repair_fn: Optional[Callable[[str, str, str], str]] = None,  # (gate_id, diagnosis, gate_check) -> patch_description
        budget: Optional[RepairBudget] = None,
        max_attempts: int = 3,
        fabric: Optional[Any] = None,
    ):
        self.ledger = ledger
        self.engine = engine
        self.repair_fn = repair_fn
        self.budget = budget or RepairBudget(max_repair_attempts=max_attempts)
        self._fabric = fabric  # ObservabilityFabric, optional

    def repair_gate(self, gate_id: str) -> RepairResult:
        """Run the full repair loop on a failing gate."""
        gate = self.ledger.gates.get(gate_id)
        if not gate:
            return RepairResult(
                gate_id=gate_id,
                final_status=RepairStatus.SKIPPED,
                attempts=0,
            )

        if gate.status == "ABANDONED":
            return RepairResult(
                gate_id=gate_id,
                final_status=RepairStatus.SKIPPED,
                attempts=0,
            )

        if not gate.check:
            return RepairResult(
                gate_id=gate_id,
                final_status=RepairStatus.SKIPPED,
                attempts=0,
            )

        attempts = []
        
        while self.budget.can_attempt():
            self.budget.consume()
            attempt_num = len(attempts) + 1
            start_time = time.monotonic()

            span = None
            if self._fabric:
                span = self._fabric.start_span(
                    name="repair.attempt",
                    trace_id="repair_loop",
                    span_id=f"repair_{gate_id}_{attempt_num}",
                    attributes={"gate_id": gate_id, "attempt_num": attempt_num},
                )

            # Step 1: Verify (confirm the gate fails)
            verify_result = self.engine.execute_gate(gate, self.ledger, reverify=True)
            pre_status = verify_result.status

            # If the gate already passes, we're done
            if verify_result.status == "MET":
                duration = (time.monotonic() - start_time) * 1000
                attempts.append(RepairAttempt(
                    attempt_num=attempt_num,
                    diagnosis="NO_FAILURE",
                    patch_description="Gate already passes",
                    pre_status=pre_status,
                    post_status="MET",
                    duration_ms=duration,
                ))
                if span and self._fabric:
                    from dafg.observe import SpanStatus
                    span.attributes.update({"diagnosis": "NO_FAILURE", "post_status": "MET"})
                    self._fabric.end_span(span, SpanStatus.OK)
                return RepairResult(
                    gate_id=gate_id,
                    final_status=RepairStatus.REPAIRED,
                    attempts=len(attempts),
                    attempt_history=attempts,
                    budget_consumed=len(attempts),
                )

            # Step 2: Diagnose
            diagnosis = RepairDiagnoser.diagnose(verify_result)

            # Step 3: Patch (call repair function)
            patch_desc = "no repair function provided"
            if self.repair_fn:
                try:
                    patch_desc = self.repair_fn(gate_id, diagnosis, gate.check or "")
                except Exception as e:
                    patch_desc = f"repair error: {e}"

            # Step 4: Re-verify
            # Reload the gate from ledger in case repair_fn modified the ledger
            gate = self.ledger.gates.get(gate_id, gate)
            reverify_result = self.engine.execute_gate(gate, self.ledger, reverify=True)
            post_status = reverify_result.status

            duration = (time.monotonic() - start_time) * 1000
            attempts.append(RepairAttempt(
                attempt_num=attempt_num,
                diagnosis=diagnosis,
                patch_description=patch_desc,
                pre_status=pre_status,
                post_status=post_status,
                duration_ms=duration,
            ))

            if span and self._fabric:
                from dafg.observe import SpanStatus
                span.attributes.update({
                    "diagnosis": diagnosis,
                    "patch": patch_desc,
                    "pre_status": pre_status,
                    "post_status": post_status,
                })
                self._fabric.end_span(
                    span,
                    SpanStatus.OK if post_status == "MET" else SpanStatus.ERROR,
                )

            if post_status == "MET":
                return RepairResult(
                    gate_id=gate_id,
                    final_status=RepairStatus.REPAIRED,
                    attempts=len(attempts),
                    attempt_history=attempts,
                    budget_consumed=len(attempts),
                )

        # Budget exhausted
        return RepairResult(
            gate_id=gate_id,
            final_status=RepairStatus.BUDGET_EXHAUSTED if attempts else RepairStatus.FAILED,
            attempts=len(attempts),
            attempt_history=attempts,
            budget_consumed=len(attempts),
        )

    def repair_all_failing(self) -> Dict[str, RepairResult]:
        """Repair all failing gates in the ledger."""
        results = {}
        for gid, gate in self.ledger.gates.items():
            if gate.status == "MET" or gate.status == "ABANDONED":
                continue
            if not gate.check:
                continue
            result = self.repair_gate(gid)
            results[gid] = result
        return results
