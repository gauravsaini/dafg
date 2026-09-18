"""Agent Stop Hook & Completion Guard.

Intercepts agent completion attempts and evaluates active ledger state.
Blocks premature completion if any runnable gate remains unmet, unverified,
or unapproved. Allows completion only when all gates are met with recorded
evidence or explicitly marked with `ABANDON: <id> <reason>`.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Union

from dafg.gates import ApprovalStore, EvidenceStrength, Gate, GateLedger, GateLinter, classify_evidence


@dataclass
class EvidenceCoverage:
    total: int = 0
    executable_proof: int = 0
    string_match: int = 0
    model_judgment: int = 0
    pending: int = 0
    none: int = 0
    coverage_pct: float = 0.0
    percentage: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StopDecision:
    allowed: bool
    decision: str  # "allow" or "block"
    reason: str
    pending_gates: List[str] = field(default_factory=list)
    unapproved_gates: List[str] = field(default_factory=list)
    unverified_gates: List[str] = field(default_factory=list)
    abandoned_gates: List[str] = field(default_factory=list)
    progress_guard_released: bool = False
    outcome_status: str = "INCOMPLETE_RUN"
    coverage: Optional[EvidenceCoverage] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)



class CompletionGuard:
    """Evaluates whether an agent can stop based on gate ledger evidence."""

    def __init__(
        self,
        ledger: Optional[GateLedger] = None,
        ledger_path: Optional[Union[str, Path]] = None,
        approval_store: Optional[ApprovalStore] = None,
        state_file: Optional[Union[str, Path]] = None,
        max_stagnant_blocks: int = 6,
        fabric: Optional[Any] = None,
    ):
        self.ledger_path = Path(ledger_path) if ledger_path else None
        if ledger:
            self.ledger = ledger
        elif self.ledger_path and self.ledger_path.exists():
            self.ledger = GateLedger.load(self.ledger_path)
        else:
            self.ledger = None

        self.approval_store = approval_store
        self.state_file = Path(state_file) if state_file else None
        self.max_stagnant_blocks = max_stagnant_blocks
        self._fabric = fabric  # ObservabilityFabric, optional

    def evaluate(self) -> StopDecision:
        if not self.ledger:
            if self.ledger_path and self.ledger_path.exists():
                self.ledger = GateLedger.load(self.ledger_path)
            else:
                return StopDecision(
                    allowed=False,
                    decision="block",
                    reason="No active gate ledger found or ledger file missing.",
                    coverage=EvidenceCoverage(),
                )

        if not self.ledger.gates:
            return StopDecision(
                allowed=False,
                decision="block",
                reason="Gate ledger contains no defined acceptance gates.",
                coverage=EvidenceCoverage(),
            )

        # Compute EvidenceCoverage rollup across all gates
        total_gates = len(self.ledger.gates)
        c_exec = 0
        c_str = 0
        c_model = 0
        c_pend = 0
        c_none = 0

        for g in self.ledger.gates.values():
            strength = classify_evidence(g)
            if strength == EvidenceStrength.EXECUTABLE_PROOF:
                c_exec += 1
            elif strength == EvidenceStrength.STRING_MATCH:
                c_str += 1
            elif strength == EvidenceStrength.MODEL_JUDGMENT:
                c_model += 1
            elif strength == EvidenceStrength.PENDING:
                c_pend += 1
            else:
                c_none += 1

        runnable_proof = c_exec + c_str
        cov_pct = round((runnable_proof / total_gates) * 100.0, 1) if total_gates > 0 else 0.0

        coverage = EvidenceCoverage(
            total=total_gates,
            executable_proof=c_exec,
            string_match=c_str,
            model_judgment=c_model,
            pending=c_pend,
            none=c_none,
            coverage_pct=cov_pct,
            percentage=cov_pct,
        )

        # Check structural and lint errors from ledger parsing & linting
        structural_errors: List[str] = []
        if self.ledger.duplicate_ids:
            dup_list = [d[0] for d in self.ledger.duplicate_ids]
            structural_errors.append(f"duplicate gate IDs detected ({', '.join(dup_list)})")
        if getattr(self.ledger, "syntax_errors", None):
            structural_errors.append(f"syntax errors in gate ledger ({len(self.ledger.syntax_errors)} errors)")

        lint_issues = GateLinter.lint(self.ledger)
        for issue in lint_issues:
            if issue.severity == "ERROR":
                if issue.gate_id and "Duplicate gate ID" in issue.message:
                    continue
                if "Malformed gate header" in issue.message or "Orphaned gate property" in issue.message:
                    continue
                # Authorship issues handled by dedicated implementer blocker
                if "AUTHOR: implementer" in issue.message or "missing AUTHOR:" in issue.message:
                    continue
                if issue.message not in structural_errors:
                    structural_errors.append(issue.message)

        pending_gates: List[str] = []
        unapproved_gates: List[str] = []
        unverified_gates: List[str] = []
        abandoned_gates: List[str] = []
        invalid_abandonments: List[str] = []

        if self.approval_store and self.ledger and hasattr(self.approval_store, "mode"):
            if getattr(self.ledger, "mode", None):
                self.approval_store.mode = self.ledger.mode

        for gid, gate in self.ledger.gates.items():
            # If approval store is configured and gate has a check command, verify approval
            if self.approval_store and gate.check and not self.approval_store.is_approved(gate):
                unapproved_gates.append(gid)

            if gate.status == "ABANDONED":
                reason = (gate.abandon_reason or "").strip()
                words = [w for w in reason.split() if w]
                trivial_tokens = {"done", "skip", "skipped", "ok", "n/a", "na", "todo", "none", "test", "fixed", "ignore", "pass", "no"}
                is_trivial = (len(words) < 4 or len(reason) < 20 or all(w.lower().strip(".,:;!-") in trivial_tokens for w in words))
                if not reason or is_trivial:
                    invalid_abandonments.append(gid)
                else:
                    abandoned_gates.append(gid)
                continue

            elif gate.status == "MET":
                # Must have recorded decisive evidence
                # If runnable gate with CHECK, must contain exit_code=0
                if (
                    not gate.evidence
                    or not gate.evidence.strip()
                    or gate.evidence.strip().lower() == "pending"
                    or (gate.check and "exit_code=0" not in gate.evidence)
                ):
                    unverified_gates.append(gid)

            else:
                # UNMET or any other non-MET status
                pending_gates.append(gid)

        # Check excessive abandonment
        total_abandoned = len(abandoned_gates) + len(invalid_abandonments)
        abandon_rate = total_abandoned / total_gates if total_gates > 0 else 0.0
        threshold = getattr(self.ledger, "abandon_threshold", 0.5)

        if total_gates > 0 and abandon_rate > threshold:
            reason = (
                f"EXCESSIVE_ABANDONMENT: {total_abandoned}/{total_gates} gates abandoned "
                f"({abandon_rate*100:.1f}%) exceeds threshold of {threshold*100:.1f}%."
            )
            if invalid_abandonments:
                reason += f" {len(invalid_abandonments)} gates abandoned without reason ({', '.join(invalid_abandonments)})."

            decision = StopDecision(
                allowed=False,
                decision="block",
                reason=reason,
                pending_gates=pending_gates,
                unapproved_gates=unapproved_gates,
                unverified_gates=unverified_gates,
                abandoned_gates=abandoned_gates,
                outcome_status="EXCESSIVE_ABANDONMENT",
                coverage=coverage,
            )
            self._emit_stop_decision(decision)
            return decision

        has_blocks = bool(
            pending_gates
            or unverified_gates
            or unapproved_gates
            or invalid_abandonments
            or structural_errors
        )

        if not has_blocks:
            ledger_mode = getattr(self.ledger, "mode", "standard")

            # Block AUTHOR:implementer gates in strict mode (ledger-level or per-gate)
            implementer_gates = []
            for gid, gate in self.ledger.gates.items():
                if gate.status == "ABANDONED":
                    continue
                effective_mode = getattr(gate, "gate_mode", None) or ledger_mode
                if effective_mode == "strict" and gate.author and gate.author.lower() == "implementer":
                    implementer_gates.append(gid)
            if implementer_gates:
                decision = StopDecision(
                    allowed=False,
                    decision="block",
                    reason=f"STRICT_MODE: AUTHOR: implementer gates blocked in strict mode ({', '.join(implementer_gates)}). Reassign authorship to human, planner, or external.",
                    pending_gates=pending_gates,
                    unapproved_gates=unapproved_gates,
                    unverified_gates=implementer_gates,
                    abandoned_gates=abandoned_gates,
                    outcome_status="IMPLEMENTER_AUTHORSHIP_BLOCKED",
                    coverage=coverage,
                )
                self._emit_stop_decision(decision)
                return decision

            # Collect gates requiring EXECUTABLE_PROOF (ledger-level strict or per-gate GATE_MODE: strict)
            strict_unproven = []
            for gid, gate in self.ledger.gates.items():
                if not gate.check or gate.status == "ABANDONED":
                    continue
                effective_mode = getattr(gate, "gate_mode", None) or ledger_mode
                if effective_mode == "strict" and classify_evidence(gate) != EvidenceStrength.EXECUTABLE_PROOF:
                    strict_unproven.append(gid)

            if strict_unproven:
                decision = StopDecision(
                    allowed=False,
                    decision="block",
                    reason="STRICT_MODE: All runnable gates must achieve EXECUTABLE_PROOF via mutation testing.",
                    pending_gates=pending_gates,
                    unapproved_gates=unapproved_gates,
                    unverified_gates=strict_unproven,
                    abandoned_gates=abandoned_gates,
                    outcome_status="INCOMPLETE_RUN",
                    coverage=coverage,
                )
                self._emit_stop_decision(decision)
                return decision

            # All satisfied
            self._reset_progress_state()
            outcome = "HANDOFF_REQUIRED" if abandoned_gates else "VERIFIED_DELIVERY"
            reason_msg = (
                f"Completed with {len(abandoned_gates)} abandoned gate(s); handoff required. "
                f"{runnable_proof}/{total_gates} gates have runnable proof ({cov_pct:.1f}%), {c_model} rely on MODEL_JUDGMENT."
                if abandoned_gates
                else (
                    f"All acceptance gates are met with evidence or validly abandoned. "
                    f"{runnable_proof}/{total_gates} gates have runnable proof ({cov_pct:.1f}%), {c_model} rely on MODEL_JUDGMENT."
                )
            )
            decision = StopDecision(
                allowed=True,
                decision="allow",
                reason=reason_msg,
                abandoned_gates=abandoned_gates,
                outcome_status=outcome,
                coverage=coverage,
            )
            self._emit_stop_decision(decision)
            return decision

        # Build detailed blocking reason
        reasons: List[str] = list(structural_errors)
        if pending_gates:
            reasons.append(f"{len(pending_gates)} unmet gates ({', '.join(pending_gates)})")
        if unverified_gates:
            reasons.append(f"{len(unverified_gates)} unverified gates missing evidence ({', '.join(unverified_gates)})")
        if unapproved_gates:
            reasons.append(f"{len(unapproved_gates)} unapproved command checks ({', '.join(unapproved_gates)})")
        if invalid_abandonments:
            reasons.append(f"{len(invalid_abandonments)} gates abandoned without reason ({', '.join(invalid_abandonments)})")

        block_reason = "Completion blocked: " + "; ".join(reasons)

        # Check progress guard
        state_sig = hashlib.sha256(
            f"{sorted(pending_gates)}|{sorted(unverified_gates)}|{sorted(unapproved_gates)}|{sorted(invalid_abandonments)}|{sorted(structural_errors)}".encode()
        ).hexdigest()

        stagnant_count = self._update_progress_state(state_sig)
        if self.max_stagnant_blocks > 0 and stagnant_count >= self.max_stagnant_blocks:
            decision = StopDecision(
                allowed=True,
                decision="allow",
                reason=f"Progress guard released after {stagnant_count} consecutive stagnant blocks: {block_reason}",
                pending_gates=pending_gates,
                unapproved_gates=unapproved_gates,
                unverified_gates=unverified_gates,
                abandoned_gates=abandoned_gates,
                progress_guard_released=True,
                outcome_status="INCOMPLETE_RUN",
                coverage=coverage,
            )
            self._emit_stop_decision(decision)
            return decision

        decision = StopDecision(
            allowed=False,
            decision="block",
            reason=block_reason,
            pending_gates=pending_gates,
            unapproved_gates=unapproved_gates,
            unverified_gates=unverified_gates,
            abandoned_gates=abandoned_gates,
            outcome_status="INCOMPLETE_RUN",
            coverage=coverage,
        )
        self._emit_stop_decision(decision)
        return decision


    def _emit_stop_decision(self, decision: StopDecision) -> None:
        """DOF: emit stop_hook.evaluated event if fabric is attached."""
        if self._fabric:
            payload = {
                "decision": decision.decision,
                "allowed": decision.allowed,
                "pending_count": len(decision.pending_gates),
                "unverified_count": len(decision.unverified_gates),
                "unapproved_count": len(decision.unapproved_gates),
                "abandoned_count": len(decision.abandoned_gates),
                "outcome_status": decision.outcome_status,
            }
            if decision.coverage:
                payload["coverage"] = decision.coverage.to_dict()
            self._fabric.emit_event("stop_hook.evaluated", payload)


    def _update_progress_state(self, current_sig: str) -> int:
        if not self.state_file:
            return 0
        count = 0
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                prev_sig = data.get("sig")
                prev_count = data.get("count", 0)
                if prev_sig == current_sig:
                    count = prev_count + 1
                else:
                    count = 1
            else:
                count = 1

            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_f = self.state_file.with_name(f"{self.state_file.name}.tmp.{os.getpid()}")
            tmp_f.write_text(json.dumps({"sig": current_sig, "count": count}), encoding="utf-8")
            os.replace(tmp_f, self.state_file)
        except Exception:
            count = 1
        return count

    def _reset_progress_state(self) -> None:
        if self.state_file and self.state_file.exists():
            try:
                self.state_file.unlink()
            except Exception:
                pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Stop Hook & Completion Guard")
    parser.add_argument("file", nargs="?", default="GATES.md", help="Path to GATES.md")
    parser.add_argument("--approvals-file", default=".approved_gates.json", help="Path to approvals file")
    parser.add_argument("--state-file", default=None, help="Path to progress hook state file")
    parser.add_argument("--json", action="store_true", help="Output JSON decision")
    parser.add_argument("--max-stagnant-blocks", type=int, default=6, help="Progress guard stagnant threshold")
    args = parser.parse_args(argv)

    ledger_path = Path(args.file)
    state_file = Path(args.state_file) if args.state_file else (ledger_path.parent / ".dafg_hook_state.json")
    appr_path = Path(args.approvals_file)
    if args.approvals_file == ".approved_gates.json" and (ledger_path.parent / ".approved_gates.json").exists():
        appr_path = ledger_path.parent / ".approved_gates.json"
    appr_store = ApprovalStore(filepath=appr_path)

    guard = CompletionGuard(
        ledger_path=ledger_path,
        approval_store=appr_store,
        state_file=state_file,
        max_stagnant_blocks=args.max_stagnant_blocks,
    )

    decision = guard.evaluate()

    if args.json:
        print(decision.to_json())
    else:
        if decision.allowed:
            print(f"✓ STOP ALLOWED: {decision.reason}")
        else:
            print(f"✗ STOP BLOCKED: {decision.reason}")
        if decision.coverage:
            cov = decision.coverage
            runnable = cov.executable_proof + cov.string_match
            print(f"Evidence Coverage: {runnable}/{cov.total} gates have runnable proof ({cov.coverage_pct:.1f}%), {cov.model_judgment} rely on MODEL_JUDGMENT")

    return 0 if decision.allowed else 1



if __name__ == "__main__":
    sys.exit(main())
