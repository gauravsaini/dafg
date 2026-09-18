"""Runnable Gate Ledger Engine (`gates`).

Parses, lints, and executes markdown gate ledgers (`GATES.md`), enforcing an
approval security boundary and recording decisive evidence directly into the
ledger.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

GATE_HEADER_RE = re.compile(
    r"^[ \t]*-\s*\[(?P<status>[ xX\-])\]\s*(?P<id>[A-Za-z0-9_.:-]+):\s*(?P<title>.*)$"
)
MALFORMED_HEADER_RE = re.compile(r"^[ \t]*-\s*\[.*\]")
PROPERTY_RE = re.compile(
    r"^[ \t]*(?P<key>CHECK|EXPECT|CWD|EVIDENCE|OWNS_READ|OWNS|ABANDON|TIMEOUT|VISUAL_REF|VISUAL_DIFF|VISUAL_RETRIES|VISUAL_ASSERTIONS|DETERMINISM|ADVERSARIAL|ADVERSARIAL_BUDGET|AUTHOR|GATE_MODE):\s*(?P<value>.*)$",
    re.IGNORECASE,
)
TOP_ABANDON_RE = re.compile(
    r"^ABANDON:\s*(?P<id>[A-Za-z0-9_.:-]+)(?:\s+(?P<reason>.*))?$"
)
MODE_HEADER_RE = re.compile(
    r"^[ \t]*(?:<!--[ \t]*)?(?:#\s*)?MODE:\s*(?P<mode>[A-Za-z]+)(?:[ \t]*-->)?",
    re.IGNORECASE,
)
ABANDON_THRESHOLD_RE = re.compile(
    r"^[ \t]*(?:<!--[ \t]*)?(?:#\s*)?ABANDON_THRESHOLD:\s*(?P<val>[0-9.]+%?)(?:[ \t]*-->)?",
    re.IGNORECASE,
)


TAUTOLOGICAL_PATTERNS = {
    ".*",
    "^.*$",
    ".+",
    "^.+$",
    "^.*",
    ".*$",
    ".*?",
    "^.*?$",
    "",
    "(.*)",
    "^(.*)$",
    "(?:.*)",
    "^(?:.*)$",
    "(.+)",
    "^(.+)$",
    "(?:.+)",
    ".{0,}",
    ".{1,}",
    r"(?s).*",
    r"[\s\S]*",
    r"^[\s\S]*$",
    r"[\s\S]+",
    r"^[\s\S]+$",
    r"[\d\D]*",
    r"^[\d\D]*$",
    r"[\d\D]+",
    r"^[\d\D]+$",
    r"[\w\W]*",
    r"^[\w\W]*$",
    r"[\w\W]+",
    r"^[\w\W]+$",
}
TAUTOLOGICAL_COMMANDS = {"true", ":", "exit 0", "pass"}


from enum import Enum

class EvidenceStrength(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    MODEL_JUDGMENT = "MODEL_JUDGMENT"
    STRING_MATCH = "STRING_MATCH"
    EXECUTABLE_PROOF = "EXECUTABLE_PROOF"


@dataclass
class Gate:
    id: str
    title: str
    status: str = "UNMET"  # UNMET, MET, ABANDONED
    mutation_tested: bool = False
    check: Optional[str] = None
    expect: Optional[str] = None
    cwd: Optional[str] = None
    evidence: Optional[str] = None
    owns: Optional[str] = None
    owns_read: Optional[str] = None  # read-only ownership (doesn't conflict with other reads)
    abandon_reason: Optional[str] = None
    timeout: Optional[float] = None
    visual_ref: Optional[str] = None
    visual_diff: Optional[float] = None
    visual_retries: Optional[int] = None
    visual_assertions: Optional[str] = None
    determinism: Optional[str] = None
    adversarial: Optional[str] = None
    adversarial_budget: Optional[int] = None
    author: Optional[str] = None  # human, planner, implementer, external
    gate_mode: Optional[str] = None  # per-gate mode override: quick, standard, strict
    header_index: int = -1
    evidence_index: Optional[int] = None
    abandon_index: Optional[int] = None
    end_index: int = -1
    line_number: int = 0


@dataclass
class LintIssue:
    severity: str  # ERROR, WARNING
    gate_id: Optional[str]
    message: str
    line_number: int = 0


def classify_evidence(gate: Gate) -> EvidenceStrength:
    if gate.status == "ABANDONED":
        return EvidenceStrength.NONE
    if not gate.evidence or gate.evidence.strip().lower() == "pending":
        if not gate.evidence:
            return EvidenceStrength.NONE
        return EvidenceStrength.PENDING
    if not gate.check:
        # Manual gate with evidence but no CHECK command
        return EvidenceStrength.MODEL_JUDGMENT
    if "exit_code=0" in gate.evidence:
        has_mutation_proof = False
        if getattr(gate, "mutation_tested", False):
            has_mutation_proof = True
        elif re.search(r"\bmutation_tested=(?:true|1)\b", gate.evidence, re.IGNORECASE):
            has_mutation_proof = True
        if re.search(r"\bmutation_tested=(?:false|0)\b", gate.evidence, re.IGNORECASE):
            has_mutation_proof = False
        if has_mutation_proof:
            return EvidenceStrength.EXECUTABLE_PROOF
        return EvidenceStrength.STRING_MATCH
    return EvidenceStrength.PENDING


@dataclass
class EvidenceRecord:
    """Attributable execution evidence record binding run, epoch, and digests."""
    run_id: str
    run_epoch: int
    gate_id: str
    gate_signature: str
    command_digest: str
    environment_digest: str
    timestamp: str
    node_id: Optional[str] = None
    attempt_id: Optional[int] = None
    match_preview: Optional[str] = None

    def serialize(self) -> str:
        data = {
            "run_id": self.run_id,
            "run_epoch": self.run_epoch,
            "gate_id": self.gate_id,
            "gate_signature": self.gate_signature,
            "command_digest": self.command_digest,
            "environment_digest": self.environment_digest,
            "timestamp": self.timestamp,
        }
        if self.node_id is not None:
            data["node_id"] = self.node_id
        if self.attempt_id is not None:
            data["attempt_id"] = self.attempt_id
        if self.match_preview is not None:
            data["match_preview"] = self.match_preview
        return json.dumps(data, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceRecord:
        return cls(
            run_id=str(data.get("run_id", "unknown")),
            run_epoch=int(data.get("run_epoch", 1)),
            gate_id=str(data.get("gate_id", "")),
            gate_signature=str(data.get("gate_signature", "")),
            command_digest=str(data.get("command_digest", "")),
            environment_digest=str(data.get("environment_digest", "")),
            timestamp=str(data.get("timestamp", "")),
            node_id=str(data["node_id"]) if data.get("node_id") is not None else None,
            attempt_id=int(data["attempt_id"]) if data.get("attempt_id") is not None else None,
            match_preview=str(data["match_preview"]) if data.get("match_preview") is not None else None,
        )

    @classmethod
    def parse_evidence_string(cls, evidence_str: str) -> Optional[EvidenceRecord]:
        if not evidence_str:
            return None
        m = re.search(r"record=(\{.*?\})", evidence_str)
        if m:
            try:
                data = json.loads(m.group(1))
                return cls.from_dict(data)
            except Exception:
                return None
        return None


@dataclass
class GateResult:
    gate_id: str
    status: str  # MET, FAILED, UNAPPROVED, ABANDONED, SKIPPED
    exit_code: Optional[int] = None
    output: Optional[str] = None
    evidence: Optional[str] = None
    error: Optional[str] = None


class GateLedger:
    def __init__(
        self,
        raw_lines: Optional[List[str]] = None,
        filepath: Optional[Path] = None,
        read_only: bool = False,
        work_dir: Optional[Path] = None,
    ):
        self.raw_lines: List[str] = raw_lines or []
        self.filepath: Optional[Path] = filepath
        self.read_only: bool = read_only
        self.work_dir: Optional[Path] = work_dir or (filepath.parent.resolve() if filepath else None)
        self.gates: Dict[str, Gate] = {}
        self.abandonments: Dict[str, str] = {}
        self.duplicate_ids: List[Tuple[str, int]] = []
        self.syntax_errors: List[LintIssue] = []
        self.mode: str = "standard"  # quick, standard, strict
        self.abandon_threshold: float = 0.5  # block if abandon rate exceeds this

    @classmethod
    def parse(
        cls,
        text: str,
        filepath: Optional[Union[str, Path]] = None,
        read_only: bool = False,
        work_dir: Optional[Union[str, Path]] = None,
    ) -> GateLedger:
        fp = Path(filepath) if filepath else None
        wd = Path(work_dir).resolve() if work_dir else (fp.parent.resolve() if fp else None)
        lines = text.splitlines()
        ledger = cls(raw_lines=lines, filepath=fp, read_only=read_only, work_dir=wd)

        current_gate: Optional[Gate] = None
        seen_ids: Set[str] = set()

        for idx, line in enumerate(lines):
            line_no = idx + 1
            # Check top-level MODE header: MODE: quick / standard / strict
            mode_match = MODE_HEADER_RE.match(line)
            if mode_match:
                parsed_mode = mode_match.group("mode").strip().lower()
                if parsed_mode in ("quick", "standard", "strict"):
                    ledger.mode = parsed_mode
                else:
                    ledger.syntax_errors.append(LintIssue(
                        severity="ERROR",
                        gate_id=None,
                        message=f"Invalid MODE: '{parsed_mode}' (must be quick, standard, or strict)",
                        line_number=line_no,
                    ))
                continue

            # Check top-level ABANDON_THRESHOLD header: ABANDON_THRESHOLD: 0.5 / 50%
            thresh_match = ABANDON_THRESHOLD_RE.match(line)
            if thresh_match:
                raw_v = thresh_match.group("val").strip()
                try:
                    ledger.abandon_threshold = float(raw_v[:-1]) / 100.0 if raw_v.endswith("%") else float(raw_v)
                except ValueError:
                    ledger.syntax_errors.append(LintIssue(
                        severity="ERROR", gate_id=None,
                        message=f"Invalid ABANDON_THRESHOLD value: '{raw_v}'", line_number=line_no,
                    ))
                continue


            # Check top-level ABANDON line: ABANDON: <id> <reason>
            abandon_match = TOP_ABANDON_RE.match(line)
            if abandon_match:
                gid = abandon_match.group("id")
                reason = (abandon_match.group("reason") or "").strip()
                ledger.abandonments[gid] = reason
                if gid in ledger.gates:
                    ledger.gates[gid].status = "ABANDONED"
                    ledger.gates[gid].abandon_reason = reason
                continue

            # Check gate header line: - [ ] G1: Title
            header_match = GATE_HEADER_RE.match(line)
            if header_match:
                raw_status = header_match.group("status")
                gid = header_match.group("id")
                title = header_match.group("title").strip()

                if gid in seen_ids:
                    ledger.duplicate_ids.append((gid, line_no))
                else:
                    seen_ids.add(gid)

                status = "MET" if raw_status in ("x", "X") else ("ABANDONED" if raw_status == "-" else "UNMET")
                current_gate = Gate(
                    id=gid,
                    title=title,
                    status=status,
                    header_index=idx,
                    end_index=idx,
                    line_number=line_no,
                )
                ledger.gates[gid] = current_gate
                continue

            # Check malformed gate header line: e.g. - [] G1 or - [?] G1
            if MALFORMED_HEADER_RE.match(line):
                current_gate = None
                ledger.syntax_errors.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=None,
                        message=f"Malformed gate header syntax: '{line.strip()}'",
                        line_number=line_no,
                    )
                )
                continue

            # Check indented properties
            prop_match = PROPERTY_RE.match(line)
            if prop_match:
                if current_gate is None:
                    ledger.syntax_errors.append(
                        LintIssue(
                            severity="ERROR",
                            gate_id=None,
                            message=f"Orphaned gate property '{prop_match.group('key')}' outside of any gate",
                            line_number=line_no,
                        )
                    )
                else:
                    key = prop_match.group("key")
                    val = prop_match.group("value").strip()
                    current_gate.end_index = idx
                    key_upper = key.upper()
                    if key_upper == "CHECK":
                        current_gate.check = val
                    elif key_upper == "EXPECT":
                        current_gate.expect = val
                    elif key_upper == "CWD":
                        current_gate.cwd = val
                    elif key_upper == "EVIDENCE":
                        current_gate.evidence = val
                        current_gate.evidence_index = idx
                    elif key_upper == "OWNS":
                        current_gate.owns = val
                    elif key_upper == "OWNS_READ":
                        current_gate.owns_read = val
                    elif key_upper == "ABANDON":
                        current_gate.status = "ABANDONED"
                        current_gate.abandon_reason = val
                        current_gate.abandon_index = idx
                    elif key_upper == "TIMEOUT":
                        try:
                            current_gate.timeout = float(val)
                        except ValueError:
                            pass
                    elif key_upper == "VISUAL_REF":
                        current_gate.visual_ref = val
                    elif key_upper == "VISUAL_DIFF":
                        try:
                            current_gate.visual_diff = float(val)
                        except ValueError:
                            pass
                    elif key_upper == "VISUAL_RETRIES":
                        try:
                            current_gate.visual_retries = int(val)
                        except ValueError:
                            pass
                    elif key_upper == "VISUAL_ASSERTIONS":
                        current_gate.visual_assertions = val
                    elif key_upper == "DETERMINISM":
                        current_gate.determinism = val
                    elif key_upper == "ADVERSARIAL":
                        current_gate.adversarial = val
                    elif key_upper == "ADVERSARIAL_BUDGET":
                        try:
                            current_gate.adversarial_budget = int(val)
                        except ValueError:
                            pass
                    elif key_upper == "AUTHOR":
                        current_gate.author = val.strip().lower()
                    elif key_upper == "GATE_MODE":
                        mode_val = val.strip().lower()
                        if mode_val in ("quick", "standard", "strict"):
                            current_gate.gate_mode = mode_val
                continue

            if current_gate is not None:
                if line.startswith(" ") or line.startswith("\t"):
                    current_gate.end_index = idx
                elif line.strip() == "":
                    # Empty line between or within gates: keep end_index on last non-empty line
                    pass
                else:
                    if (
                        not GATE_HEADER_RE.match(line)
                        and not MALFORMED_HEADER_RE.match(line)
                        and not PROPERTY_RE.match(line)
                    ):
                        current_gate = None

        # Apply any top-level abandonments to parsed gates
        for gid, reason in ledger.abandonments.items():
            if gid in ledger.gates:
                ledger.gates[gid].status = "ABANDONED"
                ledger.gates[gid].abandon_reason = reason

        return ledger

    @classmethod
    def load(cls, filepath: Union[str, Path], read_only: bool = False) -> GateLedger:
        fp = Path(filepath)
        text = fp.read_text(encoding="utf-8")
        return cls.parse(text, filepath=fp, read_only=read_only)

    def get_gate(self, gate_id: str) -> Optional[Gate]:
        return self.gates.get(gate_id)

    def update_gate_evidence(self, gate_id: str, evidence: Optional[str], met: bool = True) -> None:
        gate = self.gates.get(gate_id)
        if not gate:
            raise KeyError(f"Gate {gate_id} not found in ledger")

        gate.status = "MET" if met else "UNMET"
        gate.evidence = evidence if met else None

        # 1. Update header checkbox
        if 0 <= gate.header_index < len(self.raw_lines):
            header_line = self.raw_lines[gate.header_index]
            mark = "x" if met else " "
            new_header = re.sub(r"-\s*\[[ xX\-]\]", f"- [{mark}]", header_line, count=1)
            self.raw_lines[gate.header_index] = new_header

        # 2. Update or insert EVIDENCE line
        if met and evidence and len(self.raw_lines) > 0:
            ev_line = f"  EVIDENCE: {evidence}"
            if gate.evidence_index is not None and 0 <= gate.evidence_index < len(self.raw_lines):
                self.raw_lines[gate.evidence_index] = ev_line
            else:
                # Insert immediately after the last property of this gate
                insert_pos = min(max(0, gate.end_index + 1), len(self.raw_lines))
                self.raw_lines.insert(insert_pos, ev_line)
                gate.evidence_index = insert_pos
                gate.end_index = max(gate.end_index, insert_pos)
                # Adjust line indices for subsequent gates
                for other in self.gates.values():
                    if other.header_index > gate.header_index:
                        other.header_index += 1
                        other.end_index += 1
                        if other.evidence_index is not None:
                            other.evidence_index += 1
                        if other.abandon_index is not None:
                            other.abandon_index += 1
        elif not met and gate.evidence_index is not None and len(self.raw_lines) > 0:
            # Clear or remove evidence line if demoted
            if 0 <= gate.evidence_index < len(self.raw_lines) and "EVIDENCE:" in self.raw_lines[gate.evidence_index]:
                del self.raw_lines[gate.evidence_index]
                gate.evidence_index = None
                gate.end_index = max(gate.header_index, gate.end_index - 1)
                # Adjust line indices for subsequent gates
                for other in self.gates.values():
                    if other.header_index > gate.header_index:
                        other.header_index -= 1
                        other.end_index -= 1
                        if other.evidence_index is not None:
                            other.evidence_index -= 1
                        if other.abandon_index is not None:
                            other.abandon_index -= 1

    def abandon_gate(self, gate_id: str, reason: str) -> None:
        gate = self.gates.get(gate_id)
        if not gate:
            raise KeyError(f"Gate {gate_id} not found in ledger")

        # Clear any prior evidence when abandoning
        if gate.evidence_index is not None or gate.evidence:
            self.update_gate_evidence(gate_id, None, met=False)

        gate.status = "ABANDONED"
        gate.abandon_reason = reason
        self.abandonments[gate_id] = reason

        # Update header line to - [-]
        header_line = self.raw_lines[gate.header_index]
        new_header = re.sub(r"-\s*\[[ xX\-]\]", "- [-]", header_line, count=1)
        self.raw_lines[gate.header_index] = new_header

        # Add or update ABANDON property
        ab_line = f"  ABANDON: {reason}"
        if gate.abandon_index is not None and gate.abandon_index < len(self.raw_lines):
            self.raw_lines[gate.abandon_index] = ab_line
        else:
            insert_pos = gate.end_index + 1
            self.raw_lines.insert(insert_pos, ab_line)
            gate.abandon_index = insert_pos
            gate.end_index += 1
            for other in self.gates.values():
                if other.header_index > gate.header_index:
                    other.header_index += 1
                    other.end_index += 1
                    if other.evidence_index is not None:
                        other.evidence_index += 1
                    if other.abandon_index is not None:
                        other.abandon_index += 1

    def serialize(self) -> str:
        return "\n".join(self.raw_lines) + ("\n" if self.raw_lines and not self.raw_lines[-1].endswith("\n") else "")

    def save(self, filepath: Optional[Union[str, Path]] = None) -> None:
        if getattr(self, "read_only", False):
            return
        target = Path(filepath) if filepath else self.filepath
        if not target:
            raise ValueError("No filepath specified to save GateLedger")
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_file = target.with_name(f"{target.name}.lock")
        tmp_file = target.with_name(f"{target.name}.tmp.{os.getpid()}_{time.time_ns()}")
        with open(lock_file, "w") as lf:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                tmp_file.write_text(self.serialize(), encoding="utf-8")
                os.replace(tmp_file, target)
            finally:
                try:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


class ApprovalStore:
    """Security boundary for gate command checks.
    
    Commands must be explicitly approved before execution. Approvals bind
    gate ID, command, cwd, and expect pattern.
    """

    DANGEROUS_METACHARACTERS = ("|", "&&", ";", ">", "`")
    DANGEROUS_COMMANDS_RE = re.compile(r"\b(curl|wget|rm|chmod)\b", re.IGNORECASE)

    def __init__(
        self,
        filepath: Optional[Union[str, Path]] = None,
        auto_approve: bool = False,
        mode: str = "standard",
    ):
        self.filepath = Path(filepath) if filepath else None
        self.auto_approve = auto_approve
        self.mode = (mode or "standard").lower()
        self.approved_signatures: Set[str] = set()
        self.approved_patterns: Set[str] = set()
        if self.filepath and self.filepath.exists():
            self.load()

    @staticmethod
    def signature(gate: Gate) -> str:
        key = f"{gate.id}|{gate.check or ''}|{gate.cwd or ''}|{gate.expect or ''}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @classmethod
    def is_safe_for_pattern(cls, text: str) -> bool:
        """Check if command or pattern text is safe for pattern-based evaluation."""
        if not text:
            return False
        if any(meta in text for meta in cls.DANGEROUS_METACHARACTERS):
            return False
        if cls.DANGEROUS_COMMANDS_RE.search(text):
            return False
        return True

    def approve_pattern(self, pattern: str) -> None:
        """Approve a regex pattern for safe command classes."""
        if not self.is_safe_for_pattern(pattern):
            raise ValueError(
                "Pattern contains dangerous metacharacters or operations barred from pattern approvals"
            )
        try:
            re.compile(pattern)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{pattern}': {e}")
        if self.filepath and self.filepath.exists():
            self.load()
        self.approved_patterns.add(pattern)
        self.save()

    def is_approved(self, gate: Gate) -> bool:
        if self.auto_approve:
            return True
        if not gate.check:
            return False
        # 1. Exact SHA-256 signature always satisfies approval
        if self.signature(gate) in self.approved_signatures:
            return True
        # 2. In quick mode, safe commands are automatically approved
        if self.mode == "quick" and self.is_safe_for_pattern(gate.check):
            return True
        # 3. Check approved regex patterns (only if command is safe)
        if self.approved_patterns and self.is_safe_for_pattern(gate.check):
            for pat in self.approved_patterns:
                try:
                    if re.search(pat, gate.check):
                        return True
                except re.error:
                    continue
        return False

    def approve(self, gate: Gate) -> None:
        if gate.check:
            if self.filepath and self.filepath.exists():
                self.load()
            self.approved_signatures.add(self.signature(gate))
            self.save()

    def approve_all(self, ledger: GateLedger) -> None:
        if self.filepath and self.filepath.exists():
            self.load()
        for gate in ledger.gates.values():
            if gate.check:
                self.approved_signatures.add(self.signature(gate))
        self.save()

    def revoke(self, gate: Gate) -> None:
        sig = self.signature(gate)
        self.approved_signatures.discard(sig)
        self.save()

    def save(self) -> None:
        if self.filepath:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            lock_file = self.filepath.with_name(f"{self.filepath.name}.lock")
            tmp_file = self.filepath.with_name(f"{self.filepath.name}.tmp.{os.getpid()}_{time.time_ns()}")
            with open(lock_file, "w") as lf:
                try:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                    if self.approved_patterns:
                        payload: Union[Dict[str, List[str]], List[str]] = {
                            "approved_signatures": sorted(list(self.approved_signatures)),
                            "approved_patterns": sorted(list(self.approved_patterns)),
                        }
                    else:
                        payload = sorted(list(self.approved_signatures))
                    tmp_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                    os.replace(tmp_file, self.filepath)
                finally:
                    try:
                        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass

    def load(self) -> None:
        if self.filepath and self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.approved_signatures.update(data)
                elif isinstance(data, dict):
                    self.approved_signatures.update(
                        data.get("approved_signatures", data.get("signatures", []))
                    )
                    self.approved_patterns.update(
                        data.get("approved_patterns", data.get("patterns", []))
                    )
            except Exception:
                pass


class GateLinter:
    """Lints gate ledgers for syntax errors, duplicate IDs, missing tokens,
    and tautological / unfalsifiable checks.
    """

    @staticmethod
    def lint(ledger: GateLedger) -> List[LintIssue]:
        issues: List[LintIssue] = []

        # 0. Syntax errors from parsing
        issues.extend(ledger.syntax_errors)

        # 1. Duplicate IDs
        for gid, line_no in ledger.duplicate_ids:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    gate_id=gid,
                    message=f"Duplicate gate ID '{gid}' detected",
                    line_number=line_no,
                )
            )

        # 2. Check each gate
        if not ledger.gates and not ledger.syntax_errors:
            issues.append(
                LintIssue(
                    severity="ERROR",
                    gate_id=None,
                    message="Ledger contains no gates",
                    line_number=1,
                )
            )

        for gid, gate in ledger.gates.items():
            # Empty title
            if not gate.title or not gate.title.strip():
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Gate '{gid}' has an empty title",
                        line_number=gate.line_number,
                    )
                )

            # Abandonment validation
            if gate.status == "ABANDONED":
                if not gate.abandon_reason or not gate.abandon_reason.strip():
                    issues.append(
                        LintIssue(
                            severity="ERROR",
                            gate_id=gid,
                            message=f"Gate '{gid}' is marked abandoned without a non-empty reason",
                            line_number=gate.line_number,
                        )
                    )
                continue

            # Runnable vs Manual checks
            if gate.check is None and gate.expect is None:
                if not gate.evidence:
                    issues.append(
                        LintIssue(
                            severity="ERROR",
                            gate_id=gid,
                            message=f"Gate '{gid}' is empty: missing CHECK command",
                            line_number=gate.line_number,
                        )
                    )
                continue

            if gate.check is not None and not gate.check.strip():
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Gate '{gid}' has empty CHECK command",
                        line_number=gate.line_number,
                    )
                )

            if gate.check is not None and gate.expect is None:
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Gate '{gid}' has CHECK command but missing EXPECT pattern",
                        line_number=gate.line_number,
                    )
                )

            if gate.expect is not None and gate.check is None:
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Gate '{gid}' has EXPECT pattern but missing CHECK command",
                        line_number=gate.line_number,
                    )
                )

            if gate.expect is not None:
                if not gate.expect.strip():
                    issues.append(
                        LintIssue(
                            severity="ERROR",
                            gate_id=gid,
                            message=f"Gate '{gid}' has empty EXPECT pattern",
                            line_number=gate.line_number,
                        )
                    )
                else:
                    # Validate regex compilation
                    try:
                        re.compile(gate.expect)
                    except re.error as e:
                        issues.append(
                            LintIssue(
                                severity="ERROR",
                                gate_id=gid,
                                message=f"Gate '{gid}' has invalid regex pattern in EXPECT: {e}",
                                line_number=gate.line_number,
                            )
                        )

                    # Tautological expectation check
                    cleaned = gate.expect.strip()
                    stripped_flags = re.sub(r"^\(\?[a-zA-Z]+\)", "", cleaned)
                    stripped_parens = re.sub(r"^\((?:\?:)?(.*)\)$", r"\1", stripped_flags).strip()
                    if (
                        cleaned in TAUTOLOGICAL_PATTERNS
                        or stripped_flags in TAUTOLOGICAL_PATTERNS
                        or stripped_parens in TAUTOLOGICAL_PATTERNS
                        or stripped_flags in {".*?", "^.*?$", "^.*$", ".*", ".+", "^.+$"}
                        or stripped_parens in {".*?", "^.*?$", "^.*$", ".*", ".+", "^.+$"}
                    ):
                        issues.append(
                            LintIssue(
                                severity="ERROR",
                                gate_id=gid,
                                message=f"Gate '{gid}' has tautological EXPECT pattern '{gate.expect}' which matches anything",
                                line_number=gate.line_number,
                            )
                        )

            # Check timeout value
            if gate.timeout is not None and gate.timeout <= 0:
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Gate '{gid}' has invalid non-positive TIMEOUT: {gate.timeout}",
                        line_number=gate.line_number,
                    )
                )

            # Check CWD value
            if gate.cwd is not None and not gate.cwd.strip():
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Gate '{gid}' has empty CWD",
                        line_number=gate.line_number,
                    )
                )

            # Check unfalsifiable command
            if gate.check and gate.check.strip() in TAUTOLOGICAL_COMMANDS:
                issues.append(
                    LintIssue(
                        severity="WARNING",
                        gate_id=gid,
                        message=f"Gate '{gid}' has trivial command '{gate.check}' which may be unfalsifiable",
                        line_number=gate.line_number,
                    )
                )

            # Low-specificity EXPECT token check (R2)
            if gate.expect is not None and gate.check is not None:
                token = gate.expect.strip()
                if token and (len(token) <= 3 or token.lower() in {"ok", "0", "1", "true", "yes", "pass"}):
                    issues.append(
                        LintIssue(
                            severity="WARNING",
                            gate_id=gid,
                            message=f"Gate '{gid}' has low-specificity EXPECT token '{gate.expect}': bare tokens ≤3 chars trivially match incidental output",
                            line_number=gate.line_number,
                        )
                    )

            # Patterns matching empty/trivial output (R2)
            if gate.expect is not None and gate.expect.strip():
                try:
                    rx = re.compile(gate.expect)
                    if rx.search("") is not None:
                        issues.append(
                            LintIssue(
                                severity="WARNING",
                                gate_id=gid,
                                message=f"Gate '{gid}' has EXPECT pattern '{gate.expect}' which matches empty/trivial output",
                                line_number=gate.line_number,
                            )
                        )
                except re.error:
                    pass

            # Runnable check missing OWNS: check (R2)
            if gate.check is not None and gate.check.strip() and gate.status != "ABANDONED":
                if not gate.owns or not gate.owns.strip():
                    issues.append(
                        LintIssue(
                            severity="WARNING",
                            gate_id=gid,
                            message=f"Gate '{gid}' is a runnable check but declares no OWNS: files",
                            line_number=gate.line_number,
                        )
                    )

            # Authorship separation check (R4, R6)
            # Effective mode: per-gate GATE_MODE override takes precedence over ledger mode
            effective_mode = getattr(gate, "gate_mode", None) or getattr(ledger, "mode", "standard")
            if gate.author and gate.author.lower() == "implementer":
                issues.append(
                    LintIssue(
                        severity="ERROR" if effective_mode == "strict" else "WARNING",
                        gate_id=gid,
                        message=f"Gate '{gid}' has AUTHOR: implementer on deliverable (violates authorship separation)",
                        line_number=gate.line_number,
                    )
                )
            elif effective_mode == "strict" and gate.status != "ABANDONED":
                if not gate.author or not gate.author.strip():
                    issues.append(
                        LintIssue(
                            severity="ERROR",
                            gate_id=gid,
                            message=f"Gate '{gid}' missing AUTHOR: in strict mode (independent authorship required)",
                            line_number=gate.line_number,
                        )
                    )

        # 3. Top-level abandonments referencing unknown IDs
        for gid, reason in ledger.abandonments.items():
            if gid not in ledger.gates:
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Top-level ABANDON directive references unknown gate ID '{gid}'",
                        line_number=1,
                    )
                )
            elif not reason.strip():
                issues.append(
                    LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Top-level ABANDON for '{gid}' missing non-empty reason",
                        line_number=1,
                    )
                )

        # --- Structural dependency analysis ---
        graph = GateLinter.build_dependency_graph(ledger)

        # Self-reference deadlock detection
        for gid, gate in ledger.gates.items():
            if gate.status == "ABANDONED" or not gate.check:
                continue
            if GateLinter.detect_self_reference(gate, ledger):
                issues.append(LintIssue(
                    severity="ERROR",
                    gate_id=gid,
                    message=f"Gate '{gid}' CHECK depends on its own evidence (self-reference deadlock)",
                    line_number=gate.line_number,
                ))

        # Cycle detection
        cycles = GateLinter.detect_cycles(graph)
        for cycle in cycles:
            cycle_str = " → ".join(cycle + [cycle[0]])
            issues.append(LintIssue(
                severity="ERROR",
                gate_id=cycle[0],
                message=f"Circular dependency detected: {cycle_str}",
                line_number=ledger.gates[cycle[0]].line_number if cycle[0] in ledger.gates else 0,
            ))

        # Ledger-state coupling warnings
        for gid, gate in ledger.gates.items():
            if gate.status == "ABANDONED" or not gate.check:
                continue
            if any(ref in gate.check for ref in ["GATES.md", "gates.md", str(getattr(ledger, 'filepath', ''))]) and not GateLinter.detect_self_reference(gate, ledger):
                if "--lint" in gate.check:
                    continue
                issues.append(LintIssue(
                    severity="WARNING",
                    gate_id=gid,
                    message=f"Gate '{gid}' CHECK reads the ledger file — potential ledger-state coupling",
                    line_number=gate.line_number,
                ))

        # Quick mode filter: errors only
        if getattr(ledger, "mode", "standard") == "quick":
            issues = [i for i in issues if i.severity == "ERROR"]

        return issues

    @staticmethod
    def detect_regressions(old: GateLedger, new: GateLedger) -> List[LintIssue]:
        """Detect regressions between two ledger versions.

        Flags:
        - Weakened EXPECT patterns (longer pattern replaced by shorter/weaker one)
        - Removed OWNS declarations
        - Downgraded GATE_MODE (strict -> standard -> quick)
        - Removed gates (without ABANDON)
        """
        issues: List[LintIssue] = []
        mode_rank = {"strict": 3, "standard": 2, "quick": 1}

        for gid, old_gate in old.gates.items():
            if gid not in new.gates:
                # Gate removed entirely — regression unless abandoned in old
                if old_gate.status != "ABANDONED":
                    issues.append(LintIssue(
                        severity="ERROR",
                        gate_id=gid,
                        message=f"Gate '{gid}' was removed without ABANDON (gate deletion regression)",
                        line_number=old_gate.line_number,
                    ))
                continue

            new_gate = new.gates[gid]

            # Weakened EXPECT pattern
            if old_gate.expect and new_gate.expect:
                old_exp = old_gate.expect.strip()
                new_exp = new_gate.expect.strip()
                if old_exp != new_exp and len(new_exp) < len(old_exp):
                    # Shorter pattern is suspicious — could be weakening
                    issues.append(LintIssue(
                        severity="WARNING",
                        gate_id=gid,
                        message=f"Gate '{gid}' EXPECT pattern shortened from '{old_exp}' to '{new_exp}' (possible weakening)",
                        line_number=new_gate.line_number,
                    ))
            elif old_gate.expect and not new_gate.expect:
                issues.append(LintIssue(
                    severity="ERROR",
                    gate_id=gid,
                    message=f"Gate '{gid}' EXPECT pattern removed (was '{old_gate.expect.strip()}')",
                    line_number=new_gate.line_number,
                ))

            # Removed OWNS declaration
            if old_gate.owns and old_gate.owns.strip():
                if not new_gate.owns or not new_gate.owns.strip():
                    issues.append(LintIssue(
                        severity="WARNING",
                        gate_id=gid,
                        message=f"Gate '{gid}' OWNS declaration removed (was '{old_gate.owns.strip()}')",
                        line_number=new_gate.line_number,
                    ))

            # Downgraded per-gate mode
            old_mode = getattr(old_gate, 'gate_mode', None)
            new_mode = getattr(new_gate, 'gate_mode', None)
            if old_mode and new_mode:
                if mode_rank.get(new_mode, 2) < mode_rank.get(old_mode, 2):
                    issues.append(LintIssue(
                        severity="WARNING",
                        gate_id=gid,
                        message=f"Gate '{gid}' GATE_MODE downgraded from '{old_mode}' to '{new_mode}'",
                        line_number=new_gate.line_number,
                    ))
            elif old_mode and not new_mode:
                issues.append(LintIssue(
                    severity="WARNING",
                    gate_id=gid,
                    message=f"Gate '{gid}' GATE_MODE removed (was '{old_mode}')",
                    line_number=new_gate.line_number,
                ))

            # Removed CHECK command
            if old_gate.check and old_gate.check.strip() and (not new_gate.check or not new_gate.check.strip()):
                issues.append(LintIssue(
                    severity="ERROR",
                    gate_id=gid,
                    message=f"Gate '{gid}' CHECK command removed (was runnable, now manual)",
                    line_number=new_gate.line_number,
                ))

        return issues

    @staticmethod
    def build_dependency_graph(ledger: GateLedger) -> Dict[str, Set[str]]:
        graph = {gid: set() for gid in ledger.gates}
        valid_gids = [g for g in ledger.gates.keys() if g]
        if not valid_gids:
            return graph
            
        gate_id_pattern = r'\b(' + '|'.join(re.escape(gid) for gid in valid_gids) + r')\b'
        
        ledger_names = ["GATES.md", "gates.md", "state.json"]
        if hasattr(ledger, 'filepath') and ledger.filepath:
            ledger_names.append(str(ledger.filepath))
            ledger_names.append(ledger.filepath.name)
            
        for gid, gate in ledger.gates.items():
            if not gate.check:
                continue
                
            matches = re.findall(gate_id_pattern, gate.check)
            for m in matches:
                if m != gid:
                    graph[gid].add(m)
                    
            has_ledger_ref = any(name in gate.check if name else False for name in ledger_names)
            if has_ledger_ref and re.search(rf'\b{re.escape(gid)}\b', gate.check):
                graph[gid].add(gid)
                
        return graph

    @staticmethod
    def detect_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
        cycles = []
        visited = set()
        stack = []
        in_stack = set()
        
        def dfs(node: str) -> None:
            visited.add(node)
            stack.append(node)
            in_stack.add(node)
            
            # Sort neighbors to ensure deterministic order for cycles
            for neighbor in sorted(graph.get(node, [])):
                if neighbor in in_stack:
                    idx = stack.index(neighbor)
                    cycles.append(stack[idx:].copy())
                elif neighbor not in visited:
                    dfs(neighbor)
                    
            stack.pop()
            in_stack.remove(node)
            
        # Sort nodes to ensure deterministic behavior
        for node in sorted(graph.keys()):
            if node not in visited:
                dfs(node)
                
        return cycles

    @staticmethod
    def detect_self_reference(gate: Gate, ledger: GateLedger) -> bool:
        if not gate.check:
            return False
            
        ledger_names = ["GATES.md", "gates.md"]
        if hasattr(ledger, 'filepath') and ledger.filepath:
            ledger_names.append(str(ledger.filepath))
            ledger_names.append(ledger.filepath.name)
            
        has_ledger = any(name in gate.check if name else False for name in ledger_names)
        has_status = "gates --status" in gate.check
        has_evidence = "EVIDENCE" in gate.check
        
        has_own_id = bool(re.search(rf'\b{re.escape(gate.id)}\b', gate.check))
        
        if has_own_id and (has_ledger or has_status or has_evidence):
            return True
            
        return False

class GateEngine:
    """Executes gate checks, verifying exit codes and expected pattern output."""

    def __init__(
        self,
        approval_store: Optional[ApprovalStore] = None,
        timeout: float = 30.0,
        auto_approve: bool = False,
        fabric: Optional[Any] = None,
        allow_regression: bool = True,
        enforce_safe_policy: bool = False,
    ):
        self.approval_store = approval_store
        self.timeout = timeout
        self.auto_approve = auto_approve
        self._fabric = fabric  # ObservabilityFabric, optional
        self.allow_regression = allow_regression
        self.enforce_safe_policy = enforce_safe_policy

    def execute_gate(
        self,
        gate: Gate,
        ledger: Optional[GateLedger] = None,
        reverify: bool = False,
        cwd_override: Optional[Union[str, Path]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        if gate.status == "ABANDONED":
            return GateResult(
                gate_id=gate.id,
                status="ABANDONED",
                evidence=f"abandoned: {gate.abandon_reason or 'no reason'}",
            )

        if not gate.check:
            return GateResult(
                gate_id=gate.id,
                status="FAILED",
                error=f"Gate '{gate.id}' has no runnable CHECK command",
            )

        # Security sandbox enforcement
        if self.enforce_safe_policy and gate.check:
            try:
                from dafg.organism import SafeCommandPolicy
                SafeCommandPolicy.validate_command(gate.check)
            except Exception as e:
                return GateResult(
                    gate_id=gate.id,
                    status="FAILED",
                    error=f"Security violation: {e}",
                )

        # Security boundary enforcement: unapproved checks are refused
        if self.approval_store and not self.auto_approve:
            if not self.approval_store.is_approved(gate):
                return GateResult(
                    gate_id=gate.id,
                    status="UNAPPROVED",
                    error=(
                        f"Execution refused: check command '{gate.check}' for gate '{gate.id}' "
                        f"is not approved in security approval boundary."
                    ),
                )

        if (
            gate.status == "MET"
            and not reverify
            and gate.evidence
            and "exit_code=0" in gate.evidence
            and gate.evidence.strip().lower() != "pending"
        ):
            # Evidence Integrity check: reject stale/altered cached evidence (Invariant I8)
            is_valid_evidence = True
            rec = EvidenceRecord.parse_evidence_string(gate.evidence)
            if not rec:
                is_valid_evidence = False  # Legacy/unstructured evidence without record token is rejected
            else:
                current_sig = ApprovalStore.signature(gate)
                if not rec.gate_signature or rec.gate_signature != current_sig:
                    is_valid_evidence = False  # Gate was altered after evidence was recorded
                expected_cmd_digest = hashlib.sha256((gate.check or "").encode("utf-8")).hexdigest()
                if not rec.command_digest or rec.command_digest != expected_cmd_digest:
                    is_valid_evidence = False  # Command digest mismatch
                if context and "run_epoch" in context:
                    if rec.run_epoch != context["run_epoch"]:
                        is_valid_evidence = False  # Evidence does not match current run epoch
                if context and "run_id" in context and rec.run_id and rec.run_id != context["run_id"]:
                    is_valid_evidence = False  # Evidence belongs to a different run

            if is_valid_evidence:
                return GateResult(
                    gate_id=gate.id,
                    status="MET",
                    exit_code=0,
                    evidence=gate.evidence,
                )
            else:
                if ledger and self.allow_regression:
                    ledger.update_gate_evidence(gate.id, None, met=False)

        # Resolve working directory
        if cwd_override:
            work_dir = Path(cwd_override).resolve()
        elif gate.cwd:
            base_dir = getattr(ledger, "work_dir", None) or (ledger.filepath.parent if (ledger and ledger.filepath) else Path.cwd())
            work_dir = (Path(base_dir) / gate.cwd).resolve()
        elif ledger and getattr(ledger, "work_dir", None):
            work_dir = Path(ledger.work_dir).resolve()
        elif ledger and ledger.filepath:
            work_dir = ledger.filepath.parent.resolve()
        else:
            work_dir = Path.cwd()

        timeout_val = gate.timeout or self.timeout

        # Visual gate delegation
        if gate.visual_ref:
            from dafg.visual import VisualGateConfig, VisualGateEngine, VisualAssertion
            assertions = []
            if gate.visual_assertions:
                for a in gate.visual_assertions.split(','):
                    a = a.strip().upper()
                    try:
                        assertions.append(VisualAssertion(a))
                    except ValueError:
                        pass
            if not assertions:
                assertions = [VisualAssertion.PERCEPTUAL_DIFF]
            
            det_env = {}
            if gate.determinism:
                for pair in gate.determinism.split(','):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        det_env[k.strip()] = v.strip()
            
            import tempfile
            output_path = tempfile.mktemp(suffix='.png')
            
            config = VisualGateConfig(
                reference_image=gate.visual_ref,
                capture_command=gate.check or '',
                output_path=output_path,
                assertions=assertions,
                diff_threshold=gate.visual_diff if gate.visual_diff is not None else 0.05,
                retries=gate.visual_retries if gate.visual_retries is not None else 2,
                determinism_env=det_env,
                timeout=timeout_val,
            )
            
            vge = VisualGateEngine()
            visual_result = vge.execute(config)
            
            if visual_result.passed:
                now_str = datetime.now(timezone.utc).isoformat()
                evidence_str = f"exit_code=0 timestamp={now_str} {visual_result.evidence}"
                if ledger:
                    ledger.update_gate_evidence(gate.id, evidence_str, met=True)
                    if ledger.filepath:
                        ledger.save()
                return GateResult(gate_id=gate.id, status='MET', exit_code=0, evidence=evidence_str)
            else:
                error_detail = visual_result.capture_error or 'Visual assertions failed'
                for ar in visual_result.assertion_results:
                    if not ar.passed:
                        error_detail += f'; {ar.assertion.value}: {ar.detail}'
                
                if ledger and (gate.status == "MET" or gate.evidence):
                    ledger.update_gate_evidence(gate.id, None, met=False)
                    if ledger.filepath:
                        ledger.save()
                        
                return GateResult(gate_id=gate.id, status='FAILED', exit_code=1, error=error_detail)
        def _demote_failure() -> None:
            if not getattr(self, "allow_regression", True):
                return
            if ledger and (gate.status == "MET" or gate.evidence):
                ledger.update_gate_evidence(gate.id, None, met=False)
                if ledger.filepath:
                    ledger.save()

        # Environment Pre-flight Verification:
        # If check runs node and package.json exists, auto-provision if node_modules missing
        pkg_json = work_dir / "package.json"
        if pkg_json.exists() and any(k in gate.check for k in ("node ", "npm ", "pnpm ")):
            node_mods = work_dir / "node_modules"
            if not node_mods.exists():
                try:
                    pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
                    has_deps = bool(pkg_data.get("dependencies") or pkg_data.get("devDependencies"))
                except Exception:
                    has_deps = False

                if has_deps:
                    try:
                        import shutil
                        pkg_mgr = "pnpm" if shutil.which("pnpm") else ("npm" if shutil.which("npm") else None)
                        if pkg_mgr:
                            subprocess.run([pkg_mgr, "install"], cwd=str(work_dir), capture_output=True, timeout=60.0)
                    except Exception:
                        pass

        try:
            # DOF: start gate check span
            _span = None
            if self._fabric:
                _span = self._fabric.start_span(
                    name="gate.check",
                    trace_id="gate_engine",
                    span_id=f"gate_{gate.id}",
                    attributes={"gate_id": gate.id, "check": gate.check, "expect": gate.expect or ""},
                )

            from dafg.sandbox import SubprocessExecutionBoundary, SandboxSecurityViolation
            base_sandbox_root = getattr(ledger, "work_dir", None) or (ledger.filepath.parent if (ledger and ledger.filepath) else work_dir)
            sandbox = SubprocessExecutionBoundary(workdir=base_sandbox_root, timeout=timeout_val)
            try:
                proc = sandbox.run(gate.check, cwd=work_dir)
            except SandboxSecurityViolation as ssv:
                return GateResult(
                    gate_id=gate.id,
                    status="FAILED",
                    error=f"Sandbox containment violation: {ssv}",
                )
            combined_output = proc.stdout + proc.stderr
            exit_ok = (proc.returncode == 0)

            # Environmental Error Detection: missing modules or commands are not code defects
            if not exit_ok:
                is_env_error = any(token in combined_output for token in [
                    "MODULE_NOT_FOUND", "Cannot find module", "command not found", "No module named"
                ])
                if is_env_error:
                    return GateResult(
                        gate_id=gate.id,
                        status="BLOCKED",
                        exit_code=proc.returncode,
                        error=f"Environment dependency error: {combined_output.strip()[:120]}",
                    )

            # Check pattern match
            matched = False
            match_preview = ""
            if gate.expect and exit_ok:
                m = re.search(gate.expect, combined_output)
                if m:
                    matched = True
                    match_preview = m.group(0)[:60].replace("\n", " ")

            if exit_ok and matched:
                now_str = datetime.now(timezone.utc).isoformat()
                run_id = (context or {}).get("run_id", "local_run")
                run_epoch = (context or {}).get("run_epoch", 1)
                node_id = (context or {}).get("node_id")
                attempt_id = (context or {}).get("attempt_id", 1)

                gate_sig = ApprovalStore.signature(gate)
                cmd_digest = hashlib.sha256((gate.check or "").encode("utf-8")).hexdigest()
                env_digest = hashlib.sha256(f"{work_dir}|{sys.platform}|{sys.version.split()[0]}".encode("utf-8")).hexdigest()

                rec = EvidenceRecord(
                    run_id=str(run_id),
                    run_epoch=int(run_epoch),
                    gate_id=gate.id,
                    gate_signature=gate_sig,
                    command_digest=cmd_digest,
                    environment_digest=env_digest,
                    timestamp=now_str,
                    node_id=str(node_id) if node_id else None,
                    attempt_id=int(attempt_id) if attempt_id else None,
                    match_preview=match_preview,
                )
                evidence_str = f"exit_code=0 timestamp={now_str} match='{match_preview}' epoch={run_epoch} sig={gate_sig[:12]} record={rec.serialize()}"
                if ledger:
                    ledger.update_gate_evidence(gate.id, evidence_str, met=True)
                    if ledger.filepath:
                        ledger.save()

                # DOF: close span OK
                if _span and self._fabric:
                    _span.attributes.update({"exit_code": 0, "evidence_strength": "STRING_MATCH"})
                    from dafg.observe import SpanStatus
                    self._fabric.end_span(_span, SpanStatus.OK)

                return GateResult(
                    gate_id=gate.id,
                    status="MET",
                    exit_code=0,
                    output=combined_output,
                    evidence=evidence_str,
                )
            else:
                err_msg = []
                if not exit_ok:
                    err_msg.append(f"exit code {proc.returncode}")
                if not matched:
                    err_msg.append(f"output did not match EXPECT: '{gate.expect}'")

                _demote_failure()

                # DOF: close span ERROR
                if _span and self._fabric:
                    _span.attributes.update({"exit_code": proc.returncode})
                    from dafg.observe import SpanStatus
                    self._fabric.end_span(_span, SpanStatus.ERROR)

                return GateResult(
                    gate_id=gate.id,
                    status="FAILED",
                    exit_code=proc.returncode,
                    output=combined_output,
                    error="; ".join(err_msg),
                )

        except (subprocess.TimeoutExpired, TimeoutError):
            _demote_failure()
            if _span and self._fabric:
                from dafg.observe import SpanStatus
                _span.attributes["error"] = f"timeout_{timeout_val}s"
                self._fabric.end_span(_span, SpanStatus.ERROR)
            return GateResult(
                gate_id=gate.id,
                status="FAILED",
                error=f"Command timed out after {timeout_val}s",
            )
        except Exception as e:
            _demote_failure()
            if _span and self._fabric:
                from dafg.observe import SpanStatus
                _span.attributes["error"] = str(e)
                self._fabric.end_span(_span, SpanStatus.ERROR)
            return GateResult(
                gate_id=gate.id,
                status="FAILED",
                error=f"Execution error: {e}",
            )

    def execute_all(
        self,
        ledger: GateLedger,
        reverify: bool = False,
    ) -> Dict[str, GateResult]:
        results: Dict[str, GateResult] = {}
        for gid, gate in ledger.gates.items():
            res = self.execute_gate(gate, ledger=ledger, reverify=reverify)
            results[gid] = res
        return results


def bootstrap_ledger(root: Union[str, Path] = Path(".")) -> GateLedger:
    """Discovers tests and scaffolds an initial valid GATES.md."""
    root_path = Path(root).resolve()
    ignore_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".agents", "dist", "build", ".pytest_cache", "eval_results",
    }
    test_files: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith(".")]
        for fname in filenames:
            is_py_test = (fname.startswith("test_") and fname.endswith(".py")) or fname.endswith("_test.py")
            is_js_test = any(fname.endswith(ext) for ext in (".test.js", ".test.ts", ".spec.js", ".spec.ts"))
            if is_py_test or is_js_test:
                test_files.append(Path(dirpath) / fname)

    test_files.sort(key=lambda p: p.relative_to(root_path).as_posix())

    gates_md_lines = [
        "# Project Acceptance Gates",
        "MODE: standard",
        "",
    ]

    import_re = re.compile(
        r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\s*\(\s*['"]([^'"]+)['"]\s*\))"""
    )

    if not test_files:
        owns_fallback = "src/" if (root_path / "src").is_dir() else "."
        gates_md_lines.extend([
            "- [ ] G1: Project initial test suite",
            "  CHECK: uv run pytest -q",
            "  EXPECT: passed",
            f"  OWNS: {owns_fallback}",
            "  EVIDENCE: pending",
            "  AUTHOR: external",
            "",
        ])
    else:
        for idx, tf in enumerate(test_files, start=1):
            gid = f"G{idx}"
            title = f"Test suite {tf.name}"
            rel_str = tf.relative_to(root_path).as_posix()
            owned_files: Set[str] = set()

            if tf.suffix == ".py":
                check_cmd = f"uv run pytest {rel_str} -q"
                expect_pat = "passed"
                try:
                    content = tf.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(content, filename=str(tf))
                    cands: Set[str] = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for n in node.names:
                                cands.add(n.name)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                cands.add(node.module)
                                for n in node.names:
                                    cands.add(f"{node.module}.{n.name}")
                    for mod in cands:
                        parts = mod.split(".")
                        for cand in [
                            root_path / "src" / f"{Path(*parts)}.py",
                            root_path / "src" / Path(*parts) / "__init__.py",
                            root_path / f"{Path(*parts)}.py",
                            root_path / Path(*parts) / "__init__.py",
                        ]:
                            if cand.is_file() and not any(part in ignore_dirs for part in cand.parts):
                                cand_rel = cand.relative_to(root_path)
                                if "tests" not in cand_rel.parts and not (cand_rel.name.startswith("test_") or cand_rel.name.endswith("_test.py")):
                                    owned_files.add(cand_rel.as_posix())
                    non_init = [f for f in owned_files if not f.endswith("__init__.py")]
                    if non_init:
                        owned_files = set(non_init)
                except Exception:
                    pass
            else:
                check_cmd = f"node {rel_str}"
                expect_pat = "passed"
                try:
                    content = tf.read_text(encoding="utf-8", errors="replace")
                    for m in import_re.finditer(content):
                        specifier = m.group(1) or m.group(2)
                        if specifier:
                            spec_paths = [
                                (tf.parent / specifier).resolve(),
                                (root_path / specifier.lstrip("/")).resolve(),
                            ]
                            for base in spec_paths:
                                for cand in [
                                    base,
                                    base.with_suffix(".js"),
                                    base.with_suffix(".ts"),
                                    base / "index.js",
                                    base / "index.ts",
                                ]:
                                    if cand.is_file() and not any(part in ignore_dirs for part in cand.parts):
                                        try:
                                            cand_rel = cand.relative_to(root_path)
                                            if "tests" not in cand_rel.parts and "test" not in cand_rel.name:
                                                owned_files.add(cand_rel.as_posix())
                                        except ValueError:
                                            pass
                except Exception:
                    pass

            if owned_files:
                owns_str = ", ".join(sorted(list(owned_files)))
            else:
                owns_str = "src/" if (root_path / "src").is_dir() else rel_str

            gates_md_lines.extend([
                f"- [ ] {gid}: {title}",
                f"  CHECK: {check_cmd}",
                f"  EXPECT: {expect_pat}",
                f"  OWNS: {owns_str}",
                f"  EVIDENCE: pending",
                f"  AUTHOR: external",
                "",
            ])

    ledger_text = "\n".join(gates_md_lines)
    ledger = GateLedger.parse(ledger_text, filepath=root_path / "GATES.md", work_dir=root_path)
    issues = GateLinter.lint(ledger)
    errors = [i for i in issues if i.severity == "ERROR"]
    warnings = [i for i in issues if i.severity == "WARNING"]
    if errors or warnings:
        issue_msgs = [f"[{i.severity}] {i.gate_id or 'GENERAL'}: {i.message}" for i in issues]
        raise ValueError(f"Bootstrapped ledger failed lint check: {'; '.join(issue_msgs)}")
    return ledger


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Gate Ledger Engine")
    parser.add_argument("file", nargs="?", default="GATES.md", help="Path to GATES.md")
    parser.add_argument("--status", action="store_true", help="Display gate status")
    parser.add_argument("--lint", action="store_true", help="Lint gate ledger")
    parser.add_argument("--approve", action="store_true", help="Approve all check commands in ledger")
    parser.add_argument("--run", action="store_true", help="Execute runnable gates")
    parser.add_argument("--reverify", action="store_true", help="Reverify previously met gates")
    parser.add_argument("--trends", action="store_true", help="Show trend briefing from recent runs")
    parser.add_argument("--approvals-file", default=".approved_gates.json", help="Path to approvals file")
    parser.add_argument("--pattern", default=None, help="Regex pattern to approve (used with --approve)")
    parser.add_argument("--bootstrap", action="store_true", help="Bootstrap initial GATES.md from existing test files")
    parser.add_argument("--mutate", action="store_true", help="Run mutation adequacy tests on gates")
    parser.add_argument("--repair", action="store_true", help="Run failing gates through the repair loop")
    parser.add_argument("--repair-fn", default=None, help="Path to repair script (receives gate_id, diagnosis, check as args)")
    parser.add_argument("--max-repair-attempts", type=int, default=3, help="Maximum repair attempts per gate")
    parser.add_argument("--adversarial", action="store_true", help="Run adversarial search on gates with ADVERSARIAL config")
    args = parser.parse_args(argv)

    if args.bootstrap:
        target_path = Path(args.file)
        ledger = bootstrap_ledger(Path("."))
        target_path.write_text(ledger.serialize(), encoding="utf-8")
        print(f"✓ Bootstrapped {len(ledger.gates)} gates into '{target_path}' from project tests.")
        return 0

    if args.pattern:
        appr_path = Path(args.approvals_file)
        if args.approvals_file == ".approved_gates.json" and Path(args.file).is_file() and (Path(args.file).parent / ".approved_gates.json").exists():
            appr_path = Path(args.file).parent / ".approved_gates.json"
        store = ApprovalStore(filepath=appr_path)
        try:
            store.approve_pattern(args.pattern)
            print(f"✓ Approved pattern '{args.pattern}' (saved to {appr_path})")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    ledger_path = Path(args.file)
    if not ledger_path.exists():
        print(f"Error: Ledger file '{ledger_path}' not found.", file=sys.stderr)
        return 1
        
    if args.trends:
        from dafg.trends import TrendStore, TrendAnalyzer
        store = TrendStore(filepath=ledger_path.parent / "eval_results" / "trends.jsonl")
        analyzer = TrendAnalyzer(store)
        print(analyzer.generate_briefing())
        return 0

    ledger = GateLedger.load(ledger_path)

    if args.lint:
        issues = GateLinter.lint(ledger)
        if not issues:
            print("✓ Ledger lint passed: 0 issues found.")
            return 0
        has_errors = False
        for issue in issues:
            if issue.severity == "ERROR":
                has_errors = True
            print(f"[{issue.severity}] Line {issue.line_number} (Gate {issue.gate_id or 'GENERAL'}): {issue.message}")
        if not has_errors:
            print(f"✓ Ledger lint passed: 0 errors, {len(issues)} warning(s) found.")
            return 0
        return 1

    appr_path = Path(args.approvals_file)
    if args.approvals_file == ".approved_gates.json" and (ledger_path.parent / ".approved_gates.json").exists():
        appr_path = ledger_path.parent / ".approved_gates.json"
    approval_store = ApprovalStore(filepath=appr_path, mode=getattr(ledger, "mode", "standard"))

    if args.approve:
        approval_store.approve_all(ledger)
        print(f"✓ Approved all commands in '{ledger_path}' (saved to {args.approvals_file})")
        return 0

    if args.adversarial:
        from dafg.adversarial import AdversarialInspector, ParameterSpace, SearchStrategy
        inspector = AdversarialInspector()
        found_failures = False
        for gid, gate in ledger.gates.items():
            if not gate.adversarial or gate.status == "ABANDONED":
                continue
            space = ParameterSpace.parse(gate.adversarial)
            budget = gate.adversarial_budget or 50
            result = inspector.search(
                gate, space,
                strategy=SearchStrategy.GRID,
                budget=budget,
                cwd=ledger_path.parent,
            )
            status = "✗ FAILURE FOUND" if result.found_failure else "✓ No failures"
            print(f"{gid:10} {status} (searched {result.budget_used}/{space.total_combinations} combos, {result.coverage_pct:.0f}% coverage)")
            if result.found_failure:
                print(f"           Worst params: {result.worst_params} (score={result.worst_score:.3f})")
                found_failures = True
            print(f"           Best params:  {result.best_params} (score={result.best_score:.3f})")
        if found_failures:
            return 1
        return 0

    if args.run or args.reverify:
        engine = GateEngine(approval_store=approval_store)
        results = engine.execute_all(ledger, reverify=args.reverify)
        all_met = True
        for gid, res in results.items():
            if res.status == "MET":
                print(f"✓ {gid}: MET ({res.evidence})")
            elif res.status == "ABANDONED":
                print(f"- {gid}: ABANDONED ({res.evidence})")
            elif res.status == "UNAPPROVED":
                print(f"✗ {gid}: UNAPPROVED ({res.error})")
                all_met = False
            else:
                print(f"✗ {gid}: FAILED ({res.error})")
                all_met = False

        # Record trend data
        try:
            from dafg.trends import TrendStore, RunSummary, GateRunRecord
            import uuid
            store = TrendStore(filepath=ledger_path.parent / "eval_results" / "trends.jsonl")
            gate_records = {}
            for gid, gate in ledger.gates.items():
                gate_records[gid] = GateRunRecord(
                    gate_id=gid,
                    status=gate.status,
                )
            met_count = sum(1 for g in ledger.gates.values() if g.status == "MET")
            failed_count = sum(1 for g in ledger.gates.values() if g.status not in ("MET", "ABANDONED"))
            summary = RunSummary(
                run_id=str(uuid.uuid4())[:8],
                timestamp=datetime.now(timezone.utc).isoformat(),
                gate_results=gate_records,
                gates_met=met_count,
                gates_failed=failed_count,
                gates_total=len(ledger.gates),
                outcome="COMPLETE" if failed_count == 0 else "PARTIAL",
            )
            store.append_run(summary)
        except Exception:
            pass  # Trend recording is best-effort

        return 0 if all_met else 1

    if args.mutate:
        from dafg.mutation import GateMutator
        if getattr(ledger, "mode", "standard") == "quick":
            print("Notice: Mutation testing is disabled in quick mode.")
            return 0
        mutator = GateMutator(mode=getattr(ledger, "mode", "standard"))
        weak_gates = []
        for gid, gate in ledger.gates.items():
            if not gate.check or gate.status == "ABANDONED":
                continue
            report = mutator.test_adequacy(gate, cwd=ledger_path.parent, mode=getattr(ledger, "mode", "standard"))
            strength = "STRONG" if not report.weak else "WEAK"
            print(f"{gid:10} kill_rate={report.kill_rate:.0%} {strength}")
            for r in report.results:
                status = "killed" if r.killed else "SURVIVED"
                print(f"           {r.strategy.value}: {status}")
            if report.weak:
                weak_gates.append(gid)
        if weak_gates:
            print(f"\n⚠ {len(weak_gates)} weak gate(s): {', '.join(weak_gates)}")
            return 1
        print(f"\n✓ All gates have adequate mutation kill rates")
        return 0

    if args.repair:
        from dafg.repair import RepairLoop, RepairBudget, RepairStatus
        import subprocess as repair_subprocess
        
        repair_fn = None
        if args.repair_fn:
            def _repair_fn(gate_id, diagnosis, check_cmd):
                proc = repair_subprocess.run(
                    [args.repair_fn, gate_id, diagnosis, check_cmd],
                    capture_output=True, text=True, timeout=30.0,
                )
                return proc.stdout.strip() or f"exit_code={proc.returncode}"
            repair_fn = _repair_fn
        
        budget = RepairBudget(max_repair_attempts=args.max_repair_attempts)
        engine = GateEngine(approval_store=approval_store)
        loop = RepairLoop(ledger=ledger, engine=engine, repair_fn=repair_fn, budget=budget)
        results = loop.repair_all_failing()
        
        repaired = sum(1 for r in results.values() if r.final_status == RepairStatus.REPAIRED)
        failed = sum(1 for r in results.values() if r.final_status != RepairStatus.REPAIRED)
        
        for gid, result in results.items():
            status_str = result.final_status.value
            print(f"{gid:10} {status_str:20} ({result.attempts} attempt(s))")
            for attempt in result.attempt_history:
                print(f"           #{attempt.attempt_num}: {attempt.diagnosis} -> {attempt.post_status} ({attempt.duration_ms:.0f}ms)")
        
        if results:
            print(f"\nRepair summary: {repaired} repaired, {failed} still failing")
        else:
            print("No failing gates to repair")
        return 1 if failed > 0 else 0

    # Default: --status
    print(f"Gate Ledger: {ledger_path}")
    print("=" * 40)
    
    star_map = {
        EvidenceStrength.NONE: "☆☆☆☆",
        EvidenceStrength.PENDING: "★☆☆☆",
        EvidenceStrength.MODEL_JUDGMENT: "★★☆☆",
        EvidenceStrength.STRING_MATCH: "★★★☆",
        EvidenceStrength.EXECUTABLE_PROOF: "★★★★",
    }
    
    for gid, gate in ledger.gates.items():
        strength = classify_evidence(gate)
        stars = star_map[strength]
        st = f"[{gate.status} {stars}]"
        print(f"{gid:10} {st:15} {gate.title:40} {strength.value}")
        if gate.check:
            appr = "approved" if approval_store.is_approved(gate) else "UNAPPROVED"
            print(f"           CHECK: {gate.check} ({appr})")
        if gate.evidence:
            print(f"           EVIDENCE: {gate.evidence}")
        if gate.abandon_reason:
            print(f"           ABANDON: {gate.abandon_reason}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
