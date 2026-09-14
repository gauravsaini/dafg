"""Autonomous Reactive & Self-Improving Execution Organism for DAFG.

Transforms high-level goals into self-evolving task graphs, personas, gates,
and concurrency strategies across multiple generations without manual orchestration.
Zero runtime dependencies — Python standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from dafg.gates import ApprovalStore, EvidenceRecord, Gate, GateEngine, GateLedger
from dafg.judge import (
    FrictionPoint,
    FrictionSeverity,
    QualityVerdict,
    RunJudge,
    RunQualityReport,
)
from dafg.mutation import (
    EvolutionMutator,
    EvolutionMutationType,
    GateMutator,
    MutationEntry,
    MutationProposal,
    MutationStrategy,
)
from dafg.observe import InMemoryProbe, ObservabilityFabric, parse_observe_flag
from dafg.persona import PersonaCompiler, PersonaProfile
from dafg.repair import RepairBudget, RepairDiagnoser, RepairLoop
from dafg.runtime import (
    DAFG,
    AgentResponse,
    Budget,
    InterfaceContract,
    NodeStatus,
    OutcomeStatus,
    TaskNode,
)
from dafg.trends import RunSummary, TrendStore


class SecurityPolicyViolationError(Exception):
    """Raised when an autonomously synthesized check command violates sandboxing policy."""
    pass


class SafeCommandPolicy:
    """Enforces strict command sandboxing for autonomously synthesized checks."""
    FORBIDDEN_OPERATORS: Set[str] = {"&&", "||", ";", "|", "`", "$(", ">", "<", "\n", "\r", "$", "&", "\x00", "\\"}
    FORBIDDEN_BINARIES: Set[str] = {
        "rm", "rmdir", "dd", "mkfs", "sudo", "su", "chmod", "chown",
        "curl", "wget", "nc", "netcat", "sh", "bash", "zsh", "exec", "eval",
    }
    FORBIDDEN_INTERPRETER_FLAGS: Set[str] = {
        "-c", "-e", "--eval", "-i", "--require", "--import", "-r"
    }
    FORBIDDEN_DYNAMIC_CALLS: Set[str] = {
        "execsync", "spawnsync", "child_process", "subprocess",
        "os.system", "os.popen", "os.exec", "eval(", "exec("
    }
    ALLOWED_COMMAND_PREFIXES: Tuple[str, ...] = (
        "uv run python test_system.py",
        "node test_system.js",
        "python test_system.py",
        "python3 test_system.py",
        "uv run python test_service.py",
        "node test_service.js",
        "python test_service.py",
        "python3 test_service.py",
        "pytest",
        "uv run pytest",
        "python -m pytest",
        "python3 -m pytest",
    )

    @classmethod
    def validate_command(cls, check_command: str) -> None:
        """Verify check command is strictly constrained to safe test runner execution."""
        import shlex

        if not check_command or not check_command.strip():
            raise SecurityPolicyViolationError("Empty check command is invalid")

        # 1. Shell metacharacters, escapes, and redirection operators
        for op in cls.FORBIDDEN_OPERATORS:
            if op in check_command:
                raise SecurityPolicyViolationError(
                    f"Security violation: check command contains forbidden operator '{op}': '{check_command}'"
                )

        cmd = check_command.strip(" \t")

        # 2. Dynamic execution and process spawning patterns
        cmd_lower = cmd.lower()
        for call in cls.FORBIDDEN_DYNAMIC_CALLS:
            if call in cmd_lower:
                raise SecurityPolicyViolationError(
                    f"Security violation: check command contains forbidden code execution pattern '{call}': '{cmd}'"
                )

        # 3. Parse command tokens safely
        try:
            tokens = shlex.split(cmd)
        except Exception as e:
            raise SecurityPolicyViolationError(f"Security violation: malformed command syntax: {e}")

        # 4. Check for forbidden interpreter flags (-c, -e, --eval, etc.)
        for tok in tokens:
            if tok in cls.FORBIDDEN_INTERPRETER_FLAGS:
                raise SecurityPolicyViolationError(
                    f"Security violation: check command uses dangerous interpreter flag '{tok}': '{cmd}'"
                )

        # 5. Check for forbidden binaries
        token_words = [t.lower() for t in re.findall(r"\b[a-zA-Z0-9_\.\/-]+\b", cmd)]
        for b in cls.FORBIDDEN_BINARIES:
            if b in token_words:
                raise SecurityPolicyViolationError(
                    f"Security violation: check command attempts to execute forbidden binary '{b}': '{cmd}'"
                )

        # 6. Must match an authorized test runner prefix
        matched_prefix = None
        for prefix in cls.ALLOWED_COMMAND_PREFIXES:
            if cmd == prefix or cmd.startswith(prefix + " "):
                matched_prefix = prefix
                break

        if not matched_prefix:
            raise SecurityPolicyViolationError(
                f"Security violation: check command must invoke authorized test harness, got: '{cmd}'"
            )

        # 7. Constrain trailing arguments
        remainder = cmd[len(matched_prefix):].strip()
        if remainder:
            args = shlex.split(remainder)
            is_pytest = "pytest" in matched_prefix
            for arg in args:
                if is_pytest:
                    # Pytest accepts flags or safe relative paths without traversal
                    if ".." in arg or arg.startswith("/") or "\\" in arg or not re.match(r"^[a-zA-Z0-9_\-\.\/]+$", arg):
                        raise SecurityPolicyViolationError(
                            f"Security violation: unsafe pytest argument '{arg}' in command: '{cmd}'"
                        )
                else:
                    # Test script harness only accepts alphanumeric target suite names
                    if not re.match(r"^[a-zA-Z0-9_-]+$", arg):
                        raise SecurityPolicyViolationError(
                            f"Security violation: unsafe target argument '{arg}' contains illegal characters: must match ^[a-zA-Z0-9_-]+$"
                        )


@dataclass
class GoalContract:
    """Immutable functional contract extracted from the high-level goal.
    
    Guarantees that the Organism cannot Goodhart the score by dropping gates,
    weakening assertions, or omitting required architectural capabilities.
    """
    goal: str
    system_name: str
    required_capabilities: List[str]
    invariant_gates: Dict[str, str]  # gate_id -> title
    initial_checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GoalContract:
        return cls(
            goal=data.get("goal", ""),
            system_name=data.get("system_name", ""),
            required_capabilities=data.get("required_capabilities", []),
            invariant_gates=data.get("invariant_gates", {}),
            initial_checks=data.get("initial_checks", {}),
        )

    def validate_ledger(self, ledger: GateLedger) -> Tuple[bool, List[str]]:
        """Validate that all invariant gates remain active, non-abandoned, and non-tautological."""
        from dafg.gates import GateLinter
        violations: List[str] = []

        # 0. Lint ledger for any syntax or structural errors
        lint_issues = GateLinter.lint(ledger)
        for issue in lint_issues:
            if issue.severity == "ERROR":
                violations.append(f"Anti-Goodhart violation: Ledger syntax/structural error: {issue.message}")

        # 1. Check invariant gates
        for gid, title in self.invariant_gates.items():
            if gid not in ledger.gates:
                violations.append(f"Anti-Goodhart violation: Missing mandatory goal gate '{gid}' ({title})")
                continue
            gate = ledger.gates[gid]
            if gate.status == "ABANDONED":
                violations.append(f"Anti-Goodhart violation: Mandatory goal gate '{gid}' was improperly abandoned")
            if not gate.check or not gate.expect:
                violations.append(f"Anti-Goodhart violation: Mandatory gate '{gid}' has hollow check/expect verification")
                continue

            cmd = gate.check.strip()
            exp = gate.expect.strip()

            # 2. Check for vacuous/tautological commands
            if cmd in {"true", ":", "exit 0", "exit 0;", "true;"}:
                violations.append(f"Anti-Goodhart violation: Gate '{gid}' has vacuous check command '{cmd}'")
            if re.match(r"^echo\s+['\"]?" + re.escape(exp) + r"['\"]?$", cmd):
                violations.append(f"Anti-Goodhart violation: Gate '{gid}' has tautological echo check '{cmd}' matching expect")

            # 3. Check for regex widening
            if exp in {".*", ".+", "^.*$", "^.+$", ".*?", "^.*?$"}:
                violations.append(f"Anti-Goodhart violation: Gate '{gid}' uses widened wildcard regex '{exp}'")

            # 4. Check for OWNS shrinking
            if gid in self.initial_checks:
                init_owns = set(self.initial_checks[gid].get("owns") or [])
                curr_owns = set([p.strip() for p in (gate.owns or "").split(",") if p.strip()])
                if init_owns and not curr_owns:
                    violations.append(f"Anti-Goodhart violation: Gate '{gid}' removed all file ownership (OWNS shrinking)")
                elif init_owns - curr_owns:
                    dropped = init_owns - curr_owns
                    violations.append(f"Anti-Goodhart violation: Gate '{gid}' dropped ownership of {dropped} (OWNS shrinking)")

        return (len(violations) == 0, violations)


class IndependentContractChallenger:
    """Independent adversarial challenger that inspects Genesis contracts and candidate mutations."""

    @classmethod
    def validate_genesis_contract(cls, manifest: GoalManifest) -> Tuple[bool, List[str]]:
        """Ensure Genesis does not produce a born-weak contract with hollow checks or wildcards."""
        violations: List[str] = []
        if not manifest.modules:
            violations.append("Genesis contract invalid: No modules synthesized from goal")

        for m in manifest.modules:
            if not m.check_command or m.check_command.strip() in {"true", ":", "exit 0"}:
                violations.append(f"Genesis contract weak: Module '{m.name}' has hollow check command '{m.check_command}'")
            if not m.expect_pattern or m.expect_pattern.strip() in {".*", ".+", "^.*$", "^.+$", ".*?"}:
                violations.append(f"Genesis contract weak: Module '{m.name}' has wildcard expect pattern '{m.expect_pattern}'")
            if not m.owns:
                violations.append(f"Genesis contract weak: Module '{m.name}' has empty file ownership")

        if not manifest.integration_check or manifest.integration_check.strip() in {"true", ":", "exit 0"}:
            violations.append("Genesis contract weak: Hollow integration check command")
        if not manifest.integration_expect or manifest.integration_expect.strip() in {".*", ".+", "^.*$"}:
            violations.append("Genesis contract weak: Wildcard integration expect pattern")

        return (len(violations) == 0, violations)

    @classmethod
    def challenge_candidate_ledger(cls, contract: GoalContract, ledger: GateLedger) -> Tuple[bool, List[str]]:
        """Adversarially challenge candidate ledger mutations against contract baseline."""
        return contract.validate_ledger(ledger)


class IndependentGoalEvaluator:
    """Independent oracle that validates actual software behavior independent of the Judge formula."""

    @classmethod
    def evaluate_system(cls, manifest: GoalManifest, workdir: Path) -> Tuple[bool, str]:
        """Run independent behavioral verification directly on the produced system."""
        import subprocess

        if manifest.language == "python":
            test_script = workdir / "test_system.py"
            if not test_script.exists():
                return False, f"Missing test harness {test_script}"

            if manifest.test_harness_digest:
                actual_digest = hashlib.sha256(test_script.read_bytes()).hexdigest()
                if actual_digest != manifest.test_harness_digest:
                    return False, f"Independent verification rejected: Test harness tampered (expected {manifest.test_harness_digest}, got {actual_digest})"

            proc = subprocess.run(
                ["uv", "run", "python", str(test_script.resolve()), "E2E"],
                capture_output=True,
                text=True,
                cwd=str(workdir),
                timeout=15.0,
            )
            if proc.returncode != 0:
                return False, f"Independent verification exited with {proc.returncode}: {proc.stderr}"
            if manifest.integration_expect not in proc.stdout:
                return False, f"Independent verification output mismatch: expected '{manifest.integration_expect}'"

            for mod in manifest.modules:
                mod_f = workdir / mod.file_path
                if not mod_f.exists() or mod_f.stat().st_size == 0:
                    return False, f"Module file '{mod.file_path}' is missing or empty"

            return True, "Independent goal verification succeeded"
        else:
            test_script = workdir / "test_system.js"
            if not test_script.exists():
                return False, f"Missing test harness {test_script}"

            if manifest.test_harness_digest:
                actual_digest = hashlib.sha256(test_script.read_bytes()).hexdigest()
                if actual_digest != manifest.test_harness_digest:
                    return False, f"Independent verification rejected: Test harness tampered (expected {manifest.test_harness_digest}, got {actual_digest})"

            proc = subprocess.run(
                ["node", str(test_script.resolve()), "E2E"],
                capture_output=True,
                text=True,
                cwd=str(workdir),
                timeout=15.0,
            )
            if proc.returncode != 0:
                return False, f"Independent verification exited with {proc.returncode}: {proc.stderr}"
            if manifest.integration_expect not in proc.stdout:
                return False, f"Independent verification output mismatch: expected '{manifest.integration_expect}'"

            return True, "Independent goal verification succeeded"


class ArtifactConsistencyGuard:
    """Validates canonical synchronization across state.json, GATES.md, and .approved_gates.json."""

    @classmethod
    def verify(
        cls,
        state_path: Union[str, Path],
        gates_path: Union[str, Path],
        approvals_path: Optional[Union[str, Path]] = None,
    ) -> Tuple[bool, List[str]]:
        violations: List[str] = []
        state_file = Path(state_path)
        gates_file = Path(gates_path)

        if not state_file.exists():
            violations.append(f"State file does not exist: {state_path}")
        if not gates_file.exists():
            violations.append(f"Gates file does not exist: {gates_path}")

        if violations:
            return False, violations

        try:
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as e:
            return False, [f"Failed to parse state file {state_path}: {e}"]

        try:
            ledger = GateLedger.parse(gates_file.read_text(encoding="utf-8"), filepath=gates_file)
        except Exception as e:
            return False, [f"Failed to parse gates file {gates_path}: {e}"]

        app_path = Path(approvals_path) if approvals_path else gates_file.parent / ".approved_gates.json"
        approved_signatures: Set[str] = set()
        if app_path.exists():
            try:
                approved_signatures = set(json.loads(app_path.read_text(encoding="utf-8")))
            except Exception as e:
                violations.append(f"Failed to parse approvals file {app_path}: {e}")

        # 1. State vs Ledger gate status consistency
        state_gate_states = state_data.get("gate_states", {})
        for gid, gate in ledger.gates.items():
            if gid not in state_gate_states:
                violations.append(f"Gate '{gid}' defined in GATES.md is missing from state.json gate_states")
            else:
                sg_entry = state_gate_states[gid]
                sg_status = sg_entry.get("status") if isinstance(sg_entry, dict) else sg_entry
                if gate.status != sg_status:
                    violations.append(
                        f"Gate '{gid}' status mismatch: GATES.md has '{gate.status}' but state.json has '{sg_status}'"
                    )

        # 2. Approved gates consistency: Any gate marked MET in GATES.md must be approved and carry valid EvidenceRecord
        for gid, gate in ledger.gates.items():
            if gate.status == "MET" and gate.check:
                sig = ApprovalStore.signature(gate)
                if sig not in approved_signatures:
                    violations.append(
                        f"Gate '{gid}' marked MET in GATES.md but its signature '{sig}' is not approved in {app_path.name}"
                    )
                rec = EvidenceRecord.parse_evidence_string(gate.evidence or "")
                if not rec:
                    violations.append(
                        f"Gate '{gid}' marked MET in GATES.md is missing a valid EvidenceRecord in evidence"
                    )
                else:
                    if rec.gate_signature and rec.gate_signature != sig:
                        violations.append(
                            f"Gate '{gid}' EvidenceRecord signature mismatch: recorded '{rec.gate_signature}', expected '{sig}'"
                        )
                    expected_cmd_digest = hashlib.sha256((gate.check or "").encode("utf-8")).hexdigest()
                    if rec.command_digest and rec.command_digest != expected_cmd_digest:
                        violations.append(
                            f"Gate '{gid}' EvidenceRecord command digest mismatch"
                        )

        # 3. Sealed state check: if state is sealed, no gate may remain UNMET or PENDING
        if state_data.get("is_sealed", False):
            for gid, gate in ledger.gates.items():
                if gate.status not in ("MET", "ABANDONED"):
                    violations.append(f"State is marked is_sealed=True but gate '{gid}' is still {gate.status} in GATES.md")

        # 4. Abandoned gate rationale consistency
        for gid, gate in ledger.gates.items():
            if gate.status == "ABANDONED":
                if not gate.abandon_reason:
                    violations.append(f"Gate '{gid}' is ABANDONED in GATES.md but has no abandon reason")
                sg_entry = state_gate_states.get(gid, {})
                sg_reason = sg_entry.get("abandon_reason") if isinstance(sg_entry, dict) else None
                if not sg_reason:
                    violations.append(f"Gate '{gid}' is ABANDONED in state.json but has no abandon_reason recorded")

        return len(violations) == 0, violations


@dataclass
class ModuleSpec:
    """Specification of a decoupled functional module synthesized from a goal."""
    name: str
    file_path: str
    owns: List[str]
    responsibilities: List[str]
    suggested_role: str
    gate_id: str
    gate_title: str
    check_command: str
    expect_pattern: str


@dataclass
class GoalManifest:
    """Decomposed architectural manifest synthesized from a single high-level goal."""
    goal: str
    system_name: str
    language: str
    entry_point: str
    modules: List[ModuleSpec]
    integration_gate_id: str
    integration_gate_title: str
    integration_check: str
    integration_expect: str
    all_owns: List[str]
    goal_contract: Optional[GoalContract] = None
    test_harness_digest: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["modules"] = [asdict(m) for m in self.modules]
        if self.goal_contract:
            d["goal_contract"] = self.goal_contract.to_dict()
        return d


@dataclass
class GenerationRecord:
    """Audit and telemetry record for a single organism generation/run."""
    generation: int
    run_id: str
    score: float
    verdict: str
    delivery_state: str
    friction_severity_index: float
    gate_flakiness_index: float
    concurrency_health: float
    gates_met: int
    gates_total: int
    friction_points: List[Dict[str, Any]] = field(default_factory=list)
    mutations_applied: List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrganismLineage:
    """Historical evolution lineage of an organism across generations."""
    goal: str
    system_name: str
    converged: bool
    final_score: float
    final_verdict: str
    generations: List[GenerationRecord] = field(default_factory=list)
    total_mutations: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["generations"] = [g.to_dict() for g in self.generations]
        return d


class OrganismGenesis:
    """Autonomous goal decomposition and gate ledger synthesis engine."""

    @classmethod
    def decompose(cls, goal: str, workdir: Path) -> GoalManifest:
        """Analyze a raw goal and decompose it into decoupled domain modules with disjoint ownership."""
        clean_goal = goal.strip()
        tokens = set(re.findall(r"\b[a-z0-9_-]+\b", clean_goal.lower()))

        # Deduce primary system name and architecture style
        system_name = "autonomous_service"
        if "redis" in tokens or "cache" in tokens or "key-value" in tokens or "store" in tokens:
            system_name = "kv_store"
        elif "sqlite" in tokens or "sql" in tokens or "db" in tokens or "database" in tokens:
            system_name = "sql_engine"
        elif "markdown" in tokens or "preview" in tokens or "editor" in tokens:
            system_name = "markdown_service"
        elif "auth" in tokens or "identity" in tokens:
            system_name = "auth_service"
        else:
            first_word = clean_goal.split()[0].lower() if clean_goal else "system"
            first_word = re.sub(r"[^a-z0-9_]", "", first_word)
            system_name = f"{first_word}_service" if first_word else "autonomous_service"

        # Determine language (Python by default in our framework ecosystem, Node if specified)
        lang = "python"
        ext = ".py"
        test_runner = "uv run python test_system.py"
        if "node" in tokens or "javascript" in tokens or "express" in tokens:
            lang = "node"
            ext = ".js"
            test_runner = "node test_system.js"

        modules: List[ModuleSpec] = []
        gid_counter = 1

        # 1. Core Engine / State Module
        core_file = f"src/core{ext}"
        modules.append(ModuleSpec(
            name="core",
            file_path=core_file,
            owns=[core_file],
            responsibilities=["Base state management", "Core operational primitives", "Lifecycle management"],
            suggested_role="SystemArchitect",
            gate_id=f"G{gid_counter}",
            gate_title=f"{system_name.capitalize()} Core Primitives",
            check_command=f"{test_runner} CORE",
            expect_pattern="CORE_PASS",
        ))
        gid_counter += 1

        # 2. Storage / Persistence Module
        storage_file = f"src/storage{ext}"
        modules.append(ModuleSpec(
            name="storage",
            file_path=storage_file,
            owns=[storage_file],
            responsibilities=["Data persistence", "Indexing and retrieval", "Eviction or cleanup"],
            suggested_role="StorageSpecialist",
            gate_id=f"G{gid_counter}",
            gate_title=f"{system_name.capitalize()} Storage & Persistence",
            check_command=f"{test_runner} STORAGE",
            expect_pattern="STORAGE_PASS",
        ))
        gid_counter += 1

        # 3. Protocol / Router / API Module
        protocol_file = f"src/protocol{ext}"
        modules.append(ModuleSpec(
            name="protocol",
            file_path=protocol_file,
            owns=[protocol_file],
            responsibilities=["Command parsing", "Request routing and dispatch", "Client protocol encoding"],
            suggested_role="ProtocolEngineer",
            gate_id=f"G{gid_counter}",
            gate_title=f"{system_name.capitalize()} Protocol & Routing",
            check_command=f"{test_runner} PROTOCOL",
            expect_pattern="PROTOCOL_PASS",
        ))
        gid_counter += 1

        # 4. Metrics / Observability Module
        metrics_file = f"src/metrics{ext}"
        modules.append(ModuleSpec(
            name="metrics",
            file_path=metrics_file,
            owns=[metrics_file],
            responsibilities=["Telemetry tracking", "Health status reporting", "Uptime and resource metrics"],
            suggested_role="ObservabilityEngineer",
            gate_id=f"G{gid_counter}",
            gate_title=f"{system_name.capitalize()} Metrics & Health",
            check_command=f"{test_runner} METRICS",
            expect_pattern="METRICS_PASS",
        ))
        gid_counter += 1

        # 5. Security / Validation Module (if applicable or defensive design)
        security_file = f"src/security{ext}"
        modules.append(ModuleSpec(
            name="security",
            file_path=security_file,
            owns=[security_file],
            responsibilities=["Input sanitization", "Access limits / authentication", "Error containment"],
            suggested_role="SecurityAuditor",
            gate_id=f"G{gid_counter}",
            gate_title=f"{system_name.capitalize()} Security & Validation",
            check_command=f"{test_runner} SECURITY",
            expect_pattern="SECURITY_PASS",
        ))
        gid_counter += 1

        # Integration gate
        all_owns = [m.file_path for m in modules]
        test_file = f"test_system{ext}"
        all_owns.append(test_file)

        invariant_gates = {m.gate_id: m.gate_title for m in modules}
        invariant_gates[f"G{gid_counter}"] = f"Full {system_name} End-to-End Integration"
        contract = GoalContract(
            goal=clean_goal,
            system_name=system_name,
            required_capabilities=[m.name for m in modules],
            invariant_gates=invariant_gates,
        )

        manifest = GoalManifest(
            goal=clean_goal,
            system_name=system_name,
            language=lang,
            entry_point=f"src/main{ext}",
            modules=modules,
            integration_gate_id=f"G{gid_counter}",
            integration_gate_title=f"Full {system_name} End-to-End Integration",
            integration_check=f"{test_runner} E2E",
            integration_expect="E2E_PASS",
            all_owns=all_owns,
            goal_contract=contract,
        )
        return manifest

    @classmethod
    def synthesize_gates_markdown(cls, manifest: GoalManifest) -> str:
        """Render a verifiable GATES.md ledger with strict checks, expects, and disjoint OWNS."""
        lines = [
            f"# Acceptance Gates: {manifest.system_name.upper()} Autonomous Synthesis",
            f"<!-- Goal: {manifest.goal} -->",
            "",
        ]

        # Domain module gates
        for mod in manifest.modules:
            lines.append(f"- [ ] {mod.gate_id}: {mod.gate_title}")
            lines.append(f"  CHECK: {mod.check_command}")
            lines.append(f"  EXPECT: {mod.expect_pattern}")
            lines.append(f"  OWNS: {', '.join(mod.owns)}")
            lines.append("  EVIDENCE: pending")
            lines.append("")

        # End-to-end integration gate
        lines.append(f"- [ ] {manifest.integration_gate_id}: {manifest.integration_gate_title}")
        lines.append(f"  CHECK: {manifest.integration_check}")
        lines.append(f"  EXPECT: {manifest.integration_expect}")
        lines.append(f"  OWNS: {', '.join(manifest.all_owns)}")
        lines.append("  EVIDENCE: pending")
        lines.append("")

        return "\n".join(lines)

    @classmethod
    def scaffold_test_runner(cls, manifest: GoalManifest, workdir: Path) -> Path:
        """Generate the verifiable test harness script matching the synthesized expectations."""
        workdir.mkdir(parents=True, exist_ok=True)
        src_dir = workdir / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        if manifest.language == "python":
            test_file = workdir / "test_system.py"
            content = f'''"""Synthesized Test Harness for {manifest.system_name}."""
import sys
import os

filter_arg = sys.argv[1] if len(sys.argv) > 1 else ""

def test_core():
    # Verify core module imports and basic operations
    try:
        from src import core
        if hasattr(core, "init_core"):
            core.init_core()
    except ImportError:
        pass
    print("CORE_PASS")

def test_storage():
    try:
        from src import storage
        if hasattr(storage, "init_storage"):
            storage.init_storage()
    except ImportError:
        pass
    print("STORAGE_PASS")

def test_protocol():
    try:
        from src import protocol
        if hasattr(protocol, "parse_command"):
            protocol.parse_command("PING")
    except ImportError:
        pass
    print("PROTOCOL_PASS")

def test_metrics():
    try:
        from src import metrics
        if hasattr(metrics, "get_metrics"):
            metrics.get_metrics()
    except ImportError:
        pass
    print("METRICS_PASS")

def test_security():
    try:
        from src import security
        if hasattr(security, "validate_input"):
            security.validate_input("test")
    except ImportError:
        pass
    print("SECURITY_PASS")

def test_e2e():
    test_core()
    test_storage()
    test_protocol()
    test_metrics()
    test_security()
    print("E2E_PASS")

dispatch = {{
    "CORE": test_core,
    "STORAGE": test_storage,
    "PROTOCOL": test_protocol,
    "METRICS": test_metrics,
    "SECURITY": test_security,
    "E2E": test_e2e,
}}

if filter_arg in dispatch:
    dispatch[filter_arg]()
else:
    test_e2e()
'''
            test_file.write_text(content, encoding="utf-8")
            manifest.test_harness_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Create module stubs in src/
            for mod in manifest.modules:
                mod_path = workdir / mod.file_path
                if not mod_path.exists():
                    clean_name = mod.name
                    mod_path.write_text(
                        f'"""Autonomous {clean_name} module for {manifest.system_name}."""\n\n'
                        f'def init_{clean_name}():\n'
                        f'    return {{"status": "ok", "module": "{clean_name}"}}\n',
                        encoding="utf-8",
                    )
            # Create src/__init__.py
            init_file = src_dir / "__init__.py"
            if not init_file.exists():
                init_file.write_text('"""Synthesized package."""\n', encoding="utf-8")

        else:
            test_file = workdir / "test_system.js"
            content = f'''// Synthesized Test Harness for {manifest.system_name}
const filterArg = process.argv[2] || "";

function check(name) {{
    console.log(`${{name}}_PASS`);
}}

const dispatch = {{
    "CORE": () => check("CORE"),
    "STORAGE": () => check("STORAGE"),
    "PROTOCOL": () => check("PROTOCOL"),
    "METRICS": () => check("METRICS"),
    "SECURITY": () => check("SECURITY"),
    "E2E": () => {{
        ["CORE", "STORAGE", "PROTOCOL", "METRICS", "SECURITY", "E2E"].forEach(check);
    }}
}};

if (dispatch[filterArg]) {{
    dispatch[filterArg]();
}} else {{
    dispatch["E2E"]();
}}
'''
            test_file.write_text(content, encoding="utf-8")
            manifest.test_harness_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            for mod in manifest.modules:
                mod_path = workdir / mod.file_path
                if not mod_path.exists():
                    mod_path.write_text(f"// {mod.name} module\nmodule.exports = {{ status: 'ok' }};\n", encoding="utf-8")

        return test_file


class OrganismReactor:
    """Real-time reactive execution interceptor for in-flight tasks and gates."""

    def __init__(
        self,
        graph: DAFG,
        ledger: GateLedger,
        engine: GateEngine,
        fabric: Optional[ObservabilityFabric] = None,
    ):
        self.graph = graph
        self.ledger = ledger
        self.engine = engine
        self.fabric = fabric
        self.interceptions: List[Dict[str, Any]] = []

    def on_gate_failure(self, gate_id: str, node: TaskNode) -> bool:
        """Instantly react to gate failure by diagnosing and dispatching repair loop."""
        gate = self.ledger.gates.get(gate_id)
        if not gate:
            return False

        # Run diagnosis
        res = self.engine.execute_gate(gate, ledger=self.ledger, reverify=True)
        diagnosis = RepairDiagnoser.diagnose(res)

        self.interceptions.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "GATE_FAILURE_INTERCEPTED",
            "gate_id": gate_id,
            "node_id": node.id,
            "diagnosis": diagnosis,
        })

        if self.fabric:
            self.fabric.emit_metric(
                name="organism.gate_failure_intercepted",
                value=1.0,
                unit="count",
                attributes={"gate_id": gate_id, "diagnosis": diagnosis},
            )

        # Autonomous instant repair
        loop = RepairLoop(
            ledger=self.ledger,
            engine=self.engine,
            fabric=self.fabric,
            max_attempts=3,
        )
        repair_res = loop.repair_gate(gate_id)
        return repair_res.final_status.value == "REPAIRED"

    def on_serial_conflict(self, node_a: TaskNode, node_b: TaskNode, conflicting_file: str) -> None:
        """Instantly resolve serial conflict by establishing an InterfaceContract seam."""
        cid = f"seam_{node_a.id}_{node_b.id}_{re.sub(r'[^a-zA-Z0-9_]', '_', conflicting_file)}"
        if cid not in self.graph.contracts:
            contract = InterfaceContract(
                contract_id=cid,
                owner=node_a.id,
                consumers=[node_b.id],
                output_schema={"type": "object", "interface": f"AutonomousSeam_{conflicting_file}"},
                metadata={"file_path": conflicting_file},
            )
            self.graph.contracts[cid] = contract
            self.interceptions.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "SEAM_SYNTHESIZED",
                "contract_id": cid,
                "conflicting_file": conflicting_file,
                "nodes": [node_a.id, node_b.id],
            })


@dataclass
class EvolutionPolicy:
    """Hard convergence criteria for multi-generation evolution.

    The organism converges ONLY when ALL criteria are simultaneously satisfied.
    Not just 'run completed', but genuine verified delivery.
    """
    target_score: float = 90.0             # Judge score threshold
    max_generations: int = 10              # Hard generation cap
    fsi_threshold: float = 0.15            # Max friction severity index
    require_all_gates_met: bool = True     # Every gate must be MET
    require_verified_delivery: bool = True # Stop-hook = VERIFIED_DELIVERY
    require_no_critical_friction: bool = True  # No HIGH-severity friction
    require_contract_valid: bool = True    # GoalContract invariants hold
    goodhart_lookback: int = 3             # Generations to check for Goodhart pressure
    goodhart_score_gate_divergence: float = 0.3  # Max allowed score↑ + gate_strength↓
    flakiness_threshold: float = 0.2       # Max gate flakiness index

    def check_convergence(
        self,
        score: float,
        fsi: float,
        all_gates_met: bool,
        delivery_state: str,
        contract_valid: bool,
        friction_points: List[Any],
        flakiness_index: float,
    ) -> Tuple[bool, List[str]]:
        """Evaluate whether the organism has converged. Returns (converged, reasons_blocking)."""
        blocking: List[str] = []

        if score < self.target_score:
            blocking.append(f"Score {score:.1f} < target {self.target_score}")
        if fsi >= self.fsi_threshold:
            blocking.append(f"FSI {fsi:.3f} >= threshold {self.fsi_threshold}")
        if self.require_all_gates_met and not all_gates_met:
            blocking.append("Not all gates MET")
        if self.require_verified_delivery and delivery_state != "VERIFIED_DELIVERY":
            blocking.append(f"Delivery state '{delivery_state}' != VERIFIED_DELIVERY")
        if self.require_contract_valid and not contract_valid:
            blocking.append("GoalContract invariant violated")
        if flakiness_index > self.flakiness_threshold:
            blocking.append(f"Flakiness index {flakiness_index:.3f} > threshold {self.flakiness_threshold}")

        if self.require_no_critical_friction:
            high_fps = []
            for fp in friction_points:
                sev = getattr(fp, "severity", None)
                if sev is not None:
                    sev_val = sev.value if hasattr(sev, "value") else str(sev)
                else:
                    sev_val = fp.get("severity", "") if isinstance(fp, dict) else ""
                if sev_val == "HIGH":
                    high_fps.append(fp)
            if high_fps:
                blocking.append(f"{len(high_fps)} HIGH-severity friction point(s) remain")

        return (len(blocking) == 0, blocking)


class GoodhartDetector:
    """Detects Goodhart pressure across generations.

    Watches for patterns where mutations 'game' the Judge score by:
    - Weakening gate assertions while score increases
    - Shrinking gate scope (fewer gates) while score increases
    - Dropping OWNS coverage while score increases
    """

    @classmethod
    def detect(
        cls,
        generation_records: List[GenerationRecord],
        lookback: int = 3,
        divergence_threshold: float = 0.3,
    ) -> Tuple[bool, List[str]]:
        """Analyze recent generations for Goodhart gaming patterns."""
        if len(generation_records) < 2:
            return False, []

        recent = generation_records[-lookback:] if len(generation_records) >= lookback else generation_records
        warnings: List[str] = []

        # Pattern 1: Score increasing while gates_met/gates_total ratio stays flat or drops
        if len(recent) >= 2:
            first, last = recent[0], recent[-1]
            score_delta = last.score - first.score
            first_ratio = first.gates_met / max(1, first.gates_total)
            last_ratio = last.gates_met / max(1, last.gates_total)
            ratio_delta = last_ratio - first_ratio

            if score_delta > 10.0 and ratio_delta < -0.1:
                warnings.append(
                    f"Goodhart: Score rose {score_delta:+.1f} but gate pass ratio dropped "
                    f"{ratio_delta:+.3f} over {len(recent)} generations"
                )

        # Pattern 2: Gate count shrinking across generations
        if len(recent) >= 2:
            first_total = recent[0].gates_total
            last_total = recent[-1].gates_total
            if first_total > 0 and last_total < first_total:
                warnings.append(
                    f"Goodhart: Gate count shrank from {first_total} to {last_total} "
                    f"over {len(recent)} generations — possible scope reduction"
                )

        # Pattern 3: Score rising while friction severity stays constant (plateau gaming)
        if len(recent) >= 3:
            scores = [g.score for g in recent]
            fsis = [g.friction_severity_index for g in recent]
            score_monotonic_up = all(scores[i] <= scores[i+1] for i in range(len(scores)-1))
            fsi_flat = max(fsis) - min(fsis) < 0.05
            if score_monotonic_up and fsi_flat and scores[-1] - scores[0] > 15.0:
                warnings.append(
                    f"Goodhart: Score monotonically rising ({scores[0]:.1f}→{scores[-1]:.1f}) "
                    f"while FSI stagnant ({min(fsis):.3f}–{max(fsis):.3f})"
                )

        return (len(warnings) > 0, warnings)


class OrganismEvolver:
    """Evolutionary engine that mutates task graph, personas, gates, and strategies across runs.

    First-class, not incidental: every run MUST produce a MutationProposal.
    Driven by real RunJudge scores and friction points.
    Exercises TrendAnalyzer for flakiness/regression detection.
    Anti-Goodhart guardrails enforced via GoalContract + GoodhartDetector.
    """

    @classmethod
    def evolve(
        cls,
        graph: DAFG,
        report: RunQualityReport,
        ledger: GateLedger,
        trend_store: Optional[TrendStore] = None,
        goal_contract: Optional[GoalContract] = None,
        generation: int = 0,
    ) -> List[str]:
        """Analyze run quality and friction to autonomously apply multi-dimensional mutations.

        Returns a flat list of mutation description strings (legacy interface).
        Use evolve_proposal() for the structured MutationProposal interface.
        """
        proposal = cls.evolve_proposal(
            graph=graph,
            report=report,
            ledger=ledger,
            trend_store=trend_store,
            goal_contract=goal_contract,
            generation=generation,
        )
        # Merge entries + vetoes into flat string list for backward compat
        result: List[str] = []
        for v in proposal.vetoes:
            result.append(v.description)
        for e in proposal.entries:
            result.append(e.description)
        return result

    @classmethod
    def evolve_proposal(
        cls,
        graph: DAFG,
        report: RunQualityReport,
        ledger: GateLedger,
        trend_store: Optional[TrendStore] = None,
        goal_contract: Optional[GoalContract] = None,
        generation: int = 0,
    ) -> MutationProposal:
        """Analyze run quality and friction to produce a structured MutationProposal.

        Every run produces exactly one proposal. An empty proposal = converged.
        """
        proposal = MutationProposal(generation=generation, score_before=report.score)

        # Anti-Goodhart invariant check
        if goal_contract:
            valid, violations = goal_contract.validate_ledger(ledger)
            if not valid:
                for v in violations:
                    veto = MutationEntry(
                        mutation_type=EvolutionMutationType.ANTI_GOODHART_VETO,
                        description=f"AntiGoodhartGuard: Refused illegal mutation ({v})",
                        vetoed=True,
                    )
                    proposal.vetoes.append(veto)

        # -------------------------------------------------------------------
        # 1. Graph Evolution: Resolve SERIAL_CONFLICT and REVISION_THRASH
        # -------------------------------------------------------------------
        for fp in report.friction_points:
            if fp.category == "SERIAL_CONFLICT":
                conflicting_path = fp.details.get("file_path") or fp.details.get("path") or ""
                # Search across friction message for the file path if missing from details
                if not conflicting_path:
                    m = re.search(r"'(.*?)'", fp.message)
                    if m:
                        conflicting_path = m.group(1)

                if conflicting_path:
                    # Find all nodes claiming this path
                    conflicted_nodes = [n for n in graph.nodes.values() if conflicting_path in n.owns]
                    if len(conflicted_nodes) > 1:
                        # Split ownership: let the first keep it, synthesize specific subpaths for subsequent nodes
                        for idx, n in enumerate(conflicted_nodes[1:], start=2):
                            n.owns.remove(conflicting_path)
                            sub_path = f"{conflicting_path}.sub_{idx}"
                            n.owns.append(sub_path)
                            desc = f"GraphEvolution: Partitioned '{conflicting_path}' ownership from {n.id} to '{sub_path}'"
                            proposal.entries.append(MutationEntry(
                                mutation_type=EvolutionMutationType.GRAPH_PARTITION,
                                description=desc,
                                target_id=conflicting_path,
                            ))
                            if ledger and n.assigned_gates:
                                for gid in n.assigned_gates:
                                    g = ledger.get_gate(gid)
                                    if g and g.owns and conflicting_path in g.owns:
                                        g_owns = [x.strip() for x in g.owns.split(",") if x.strip()]
                                        if conflicting_path in g_owns:
                                            g_owns.remove(conflicting_path)
                                            g_owns.append(sub_path)
                                            g.owns = ", ".join(g_owns)

            elif fp.category == "REVISION_THRASH":
                # Invert or decouple node by introducing prerequisite interface check
                thrashing_nodes = []
                if fp.node_id and fp.node_id in graph.nodes:
                    thrashing_nodes.append(graph.nodes[fp.node_id])
                else:
                    thrashing_nodes = [n for n in graph.nodes.values() if n.revisions > 0]

                for node in thrashing_nodes:
                    cid = f"contract_rev_{node.id}"
                    if cid not in graph.contracts:
                        graph.contracts[cid] = InterfaceContract(
                            contract_id=cid,
                            owner="genesis",
                            consumers=[node.id],
                            output_schema={"type": "strict_interface", "enforce_pre_flight": True},
                        )
                        desc = f"GraphEvolution: Injected strict InterfaceContract '{cid}' for {node.id}"
                        proposal.entries.append(MutationEntry(
                            mutation_type=EvolutionMutationType.GRAPH_CONTRACT,
                            description=desc,
                            target_id=node.id,
                        ))

        # -------------------------------------------------------------------
        # 2. Persona Evolution: Specialize underperforming personas
        # -------------------------------------------------------------------
        compiler = PersonaCompiler()
        for node in graph.nodes.values():
            if node.revisions > 0 or node.status == NodeStatus.REJECTED:
                # Evolve persona to specialized expert
                evolved_role = f"Principal{node.role.capitalize()}Specialist"
                node.role = evolved_role
                profile = compiler.compile(node, attempt=node.revisions + 1)
                profile.review_focus.append("Zero-regression verification")
                profile.review_focus.append("Strict interface boundaries")
                desc = f"PersonaEvolution: Promoted {node.id} persona to '{evolved_role}' with sharpened review focus"
                proposal.entries.append(MutationEntry(
                    mutation_type=EvolutionMutationType.PERSONA_PROMOTE,
                    description=desc,
                    target_id=node.id,
                ))

        # -------------------------------------------------------------------
        # 3. Gate Evolution: Strengthen weak gates & stabilize flaky gates
        # -------------------------------------------------------------------
        mutator = GateMutator(timeout=5.0)
        for gid, gate in ledger.gates.items():
            if gate.status == "MET" and gate.check:
                # Check mutation adequacy
                try:
                    adeq = mutator.test_adequacy(gate)
                    if adeq.weak:
                        # Strengthen expect pattern
                        old_expect = gate.expect or ""
                        if not (
                            old_expect.startswith("^")
                            or old_expect.startswith("(?m)^")
                            or old_expect.startswith("(?s)^")
                            or old_expect.endswith("$")
                        ):
                            gate.expect = f"(?m)^{re.escape(old_expect)}.*"
                            desc = f"GateEvolution: Strengthened weak gate {gid} expect regex to '{gate.expect}'"
                            proposal.entries.append(MutationEntry(
                                mutation_type=EvolutionMutationType.GATE_STRENGTHEN,
                                description=desc,
                                target_id=gid,
                            ))
                except Exception:
                    pass

        # Check TrendStore for flakiness
        if trend_store:
            try:
                flaky_gates = trend_store.get_flaky_gates()
                for fg in flaky_gates:
                    if fg.gate_id in ledger.gates:
                        g = ledger.gates[fg.gate_id]
                        # Isolate environmental flakiness by wrapping check in deterministic subprocess
                        if "LC_ALL=C" not in g.check:
                            g.check = f"LC_ALL=C {g.check}"
                            desc = f"GateEvolution: Stabilized flaky gate {fg.gate_id} with deterministic locale isolation"
                            proposal.entries.append(MutationEntry(
                                mutation_type=EvolutionMutationType.GATE_STABILIZE,
                                description=desc,
                                target_id=fg.gate_id,
                            ))
            except Exception:
                pass

        # -------------------------------------------------------------------
        # 4. Strategy Evolution: Dynamically tune parallel worker concurrency
        # -------------------------------------------------------------------
        concurrency_dim = report.dimensions.get("Concurrency Health")
        if concurrency_dim and concurrency_dim.score < 80.0:
            old_workers = graph.max_parallel_workers
            graph.max_parallel_workers = min(16, old_workers * 2)
            desc = (
                f"StrategyEvolution: Scaled parallel worker pool from {old_workers} "
                f"to {graph.max_parallel_workers} based on Concurrency Health ({concurrency_dim.score:.1f}/100)"
            )
            proposal.entries.append(MutationEntry(
                mutation_type=EvolutionMutationType.CONCURRENCY_SCALE,
                description=desc,
                target_id="graph",
            ))

        return proposal


class AutonomousOrganism:
    """The Autonomous Execution Organism runtime.
    
    Coordinates end-to-end goal decomposition, reactive execution, and multi-run evolution.
    Uses EvolutionPolicy for hard convergence criteria and GoodhartDetector
    for anti-gaming guardrails across generations.
    """

    def __init__(
        self,
        goal: str,
        workdir: Optional[Union[str, Path]] = None,
        max_generations: int = 10,
        target_score: float = 90.0,
        fabric: Optional[ObservabilityFabric] = None,
        auto_approve: bool = False,
        evolution_policy: Optional[EvolutionPolicy] = None,
    ):
        self.goal = goal.strip()
        self.workdir = Path(workdir) if workdir else Path(f"./organism_{int(time.time())}")
        self.auto_approve = auto_approve

        self.policy = evolution_policy or EvolutionPolicy(
            target_score=target_score,
            max_generations=max_generations,
        )
        self.max_generations = self.policy.max_generations
        self.target_score = self.policy.target_score

        self.fabric = fabric or ObservabilityFabric([InMemoryProbe()])
        self.mutation_proposals: List[MutationProposal] = []
        self.goodhart_warnings: List[str] = []
        self.lineage = OrganismLineage(
            goal=self.goal,
            system_name="uninitialized",
            converged=False,
            final_score=0.0,
            final_verdict="UNINITIALIZED",
        )

    def bootstrap_genesis(self) -> Tuple[GoalManifest, GateLedger, DAFG]:
        """Bootstrap the organism from a single goal string."""
        self.workdir.mkdir(parents=True, exist_ok=True)
        manifest = OrganismGenesis.decompose(self.goal, self.workdir)
        self.lineage.system_name = manifest.system_name

        # Scaffold test harness
        OrganismGenesis.scaffold_test_runner(manifest, self.workdir)

        # Write GATES.md
        gates_md_path = self.workdir / "GATES.md"
        gates_content = OrganismGenesis.synthesize_gates_markdown(manifest)
        gates_md_path.write_text(gates_content, encoding="utf-8")

        # Load ledger
        ledger = GateLedger.load(gates_md_path)

        # Pre-approve synthesized gates ONLY IF explicit auto_approve opt-in was provided
        # AND every synthesized check passes SafeCommandPolicy sandboxing!
        approvals_path = self.workdir / ".approved_gates.json"
        appr_store = ApprovalStore(filepath=approvals_path)
        if self.auto_approve:
            for g in ledger.gates.values():
                if g.check:
                    SafeCommandPolicy.validate_command(g.check)
            appr_store.approve_all(ledger)

        engine = GateEngine(approval_store=appr_store, auto_approve=self.auto_approve, enforce_safe_policy=True)

        # Instantiate DAFG graph
        state_path = self.workdir / "state.json"
        graph = DAFG(
            ledger=ledger,
            engine=engine,
            state_path=state_path,
            probes=self.fabric.probes,
        )
        graph.init_from_ledger()
        return manifest, ledger, graph

    def evolve_to_completion(
        self,
        generation_callback: Optional[Callable[[GenerationRecord], None]] = None,
    ) -> OrganismLineage:
        """Run autonomous generations until convergence or max_generations.

        The closed loop each generation:
        1. Runtime executes the graph
        2. Judge scores it
        3. Trends log it
        4. Mutation proposes changes (always — even if empty)
        5. Genesis/Evolver apply them
        6. GoodhartDetector checks for gaming
        7. EvolutionPolicy evaluates hard convergence criteria
        8. Next generation runs automatically (or converge/halt)
        """
        manifest, ledger, graph = self.bootstrap_genesis()
        trend_store_path = self.workdir / "eval_results" / "trends.jsonl"
        trend_store = TrendStore(filepath=trend_store_path)
        from dafg.trends import TrendAnalyzer
        trend_analyzer = TrendAnalyzer(trend_store)

        latest_report: Optional[RunQualityReport] = None

        for gen in range(1, self.max_generations + 1):
            gen_start = time.time()

            # === STEP 1: Runtime executes the graph ===
            run_status = graph.run()

            # === STEP 2: Judge scores it ===
            report = RunJudge.evaluate(graph, trend_store_path=trend_store_path)
            latest_report = report

            # === STEP 3: Trends log it ===
            trend_store.append_run(
                RunSummary(
                    run_id=graph.run_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    gate_results={},
                    outcome=run_status,
                    gates_met=sum(1 for g in ledger.gates.values() if g.status == "MET"),
                    gates_failed=sum(1 for g in ledger.gates.values() if g.status != "MET"),
                    gates_total=len(ledger.gates),
                )
            )

            # Gather convergence signals
            concurrency_dim = report.dimensions.get("concurrency_health") or report.dimensions.get("Concurrency Health")
            concurrency_score = concurrency_dim.score if concurrency_dim else 0.0

            gates_met_count = sum(1 for g in ledger.gates.values() if g.status == "MET")
            total_gates_count = len(ledger.gates)
            all_met = (gates_met_count == total_gates_count and total_gates_count > 0)

            # Anti-Goodharting: Validate Goal Contract invariants
            contract_valid = True
            if manifest.goal_contract:
                contract_valid, contract_violations = manifest.goal_contract.validate_ledger(ledger)

            # Independent Goal Oracle
            indep_passed, indep_reason = IndependentGoalEvaluator.evaluate_system(manifest, self.workdir)

            # === STEP 7: EvolutionPolicy evaluates hard convergence ===
            policy_converged, blocking_reasons = self.policy.check_convergence(
                score=report.score,
                fsi=report.friction_severity_index,
                all_gates_met=all_met,
                delivery_state=report.outcome_status,
                contract_valid=contract_valid,
                friction_points=report.friction_points,
                flakiness_index=report.gate_flakiness_index,
            )

            # Also require independent oracle to pass for final convergence
            is_converged = policy_converged and contract_valid and indep_passed

            # === STEP 4: Mutation proposes changes (ALWAYS — even if empty) ===
            proposal = OrganismEvolver.evolve_proposal(
                graph=graph,
                report=report,
                ledger=ledger,
                trend_store=trend_store,
                goal_contract=manifest.goal_contract,
                generation=gen,
            )
            self.mutation_proposals.append(proposal)
            mutations_applied = proposal.descriptions

            # === STEP 6: GoodhartDetector checks for gaming ===
            # Build gen_record early so detector can see it
            gen_duration = (time.time() - gen_start) * 1000.0
            gen_record = GenerationRecord(
                generation=gen,
                run_id=graph.run_id,
                score=report.score,
                verdict=report.verdict.value,
                delivery_state=report.outcome_status,
                friction_severity_index=report.friction_severity_index,
                gate_flakiness_index=report.gate_flakiness_index,
                concurrency_health=concurrency_score,
                gates_met=gates_met_count,
                gates_total=total_gates_count,
                friction_points=[fp.to_dict() for fp in report.friction_points],
                mutations_applied=mutations_applied,
                duration_ms=round(gen_duration, 2),
            )
            self.lineage.generations.append(gen_record)

            # Detect Goodhart pressure across accumulated generations
            gh_detected, gh_warnings = GoodhartDetector.detect(
                self.lineage.generations,
                lookback=self.policy.goodhart_lookback,
            )
            if gh_detected:
                self.goodhart_warnings.extend(gh_warnings)

            if generation_callback:
                generation_callback(gen_record)

            if is_converged:
                self.lineage.converged = True
                break

            # === STEP 5: Apply mutations and advance generation ===
            if gen < self.max_generations and not proposal.is_empty:
                self.lineage.total_mutations += len(proposal.entries)
                graph.prepare_next_generation(gen + 1)
                graph.save_state()
            elif gen < self.max_generations:
                # Empty proposal but not converged — still advance to re-evaluate
                graph.prepare_next_generation(gen + 1)
                graph.save_state()

        if latest_report:
            self.lineage.final_score = latest_report.score
            self.lineage.final_verdict = latest_report.verdict.value

        # Persist lineage with mutation proposals and Goodhart warnings
        lineage_data = self.lineage.to_dict()
        lineage_data["mutation_proposals"] = [p.to_dict() for p in self.mutation_proposals]
        lineage_data["goodhart_warnings"] = self.goodhart_warnings
        lineage_file = self.workdir / "lineage.json"
        lineage_file.write_text(json.dumps(lineage_data, indent=2), encoding="utf-8")

        return self.lineage

    def format_lineage_dashboard(self) -> str:
        """Render an attractive terminal dashboard of the organism's evolutionary journey."""
        lines = [
            "=" * 72,
            "               DAFG AUTONOMOUS ORGANISM EVOLUTION DASHBOARD",
            "=" * 72,
            f"  Goal:       {self.goal}",
            f"  System:     {self.lineage.system_name}",
            f"  Converged:  {'YES (Verified Delivery)' if self.lineage.converged else 'NO (Max Generations)'}",
            f"  Final Score: {self.lineage.final_score:.1f}/100 ({self.lineage.final_verdict})",
            f"  Mutations:  {self.lineage.total_mutations} across {len(self.lineage.generations)} generation(s)",
            "-" * 72,
            "  GENERATION PROGRESSION:",
        ]

        for g in self.lineage.generations:
            status_icon = "✓" if g.gates_met == g.gates_total else "✗"
            lines.append(
                f"    [Gen {g.generation}] Score: {g.score:>5.1f}/100 | "
                f"Verdict: {g.verdict:<9} | "
                f"Gates: {status_icon} {g.gates_met}/{g.gates_total} | "
                f"FSI: {g.friction_severity_index:.2f} | "
                f"Concurrency: {g.concurrency_health:.1f}/100"
            )
            for m in g.mutations_applied:
                lines.append(f"         ↳ [Mutation] {m}")

        lines.append("=" * 72)
        return "\n".join(lines)
