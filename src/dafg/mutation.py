from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class MutationStrategy(str, Enum):
    NEGATE_EXIT = "NEGATE_EXIT"
    CORRUPT_EXPECT = "CORRUPT_EXPECT"
    ENV_INJECTION = "ENV_INJECTION"


@dataclass
class MutationResult:
    strategy: MutationStrategy
    killed: bool
    original_passed: bool
    mutant_passed: bool
    duration_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class AdequacyReport:
    gate_id: str
    strategies_tested: int
    strategies_killed: int
    kill_rate: float
    weak: bool
    results: List[MutationResult] = field(default_factory=list)


class GateMutator:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def _evaluate(self, check: str, expect: Optional[str], env: Optional[dict], cwd: Optional[Path]) -> bool:
        try:
            work_dir = cwd if cwd else Path.cwd()
            proc = subprocess.run(
                check,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=str(work_dir)
            )
            if proc.returncode != 0:
                return False
            if expect:
                combined_output = proc.stdout + proc.stderr
                return bool(re.search(expect, combined_output))
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def mutate(self, gate: Any, strategy: MutationStrategy, cwd: Optional[Path] = None) -> MutationResult:
        start_time = time.time()
        
        # Verify original gate passes
        original_env = os.environ.copy()
        original_passed = self._evaluate(gate.check, gate.expect, original_env, cwd)
        
        mutant_passed = False
        killed = False
        error = None
        
        if original_passed:
            try:
                if strategy == MutationStrategy.NEGATE_EXIT:
                    mutated_check = f"false && {gate.check}"
                    mutant_passed = self._evaluate(mutated_check, gate.expect, original_env, cwd)
                    killed = not mutant_passed
                elif strategy == MutationStrategy.CORRUPT_EXPECT:
                    mutated_expect = f"IMPOSSIBLE_MUTATION_TOKEN_{int(time.time())}"
                    # Use original check, but corrupt expect
                    mutant_passed = self._evaluate(gate.check, mutated_expect, original_env, cwd)
                    killed = not mutant_passed
                elif strategy == MutationStrategy.ENV_INJECTION:
                    mutated_env = original_env.copy()
                    mutated_env["DAFG_MUTATION"] = "1"
                    mutant_passed = self._evaluate(gate.check, gate.expect, mutated_env, cwd)
                    # ENV_INJECTION doesn't strictly kill or fail the strong gate test, but we record if it was 'detected' somehow?
                    # The prompt says: "For ENV_INJECTION: purely informational — record but don't flag as weak."
                    # We can set killed = not mutant_passed just for recording, or always False.
                    # Actually: "If the script detects it and fails, killed=True. If it passes identically, it doesn't test behavior sensitive..."
                    killed = not mutant_passed
            except Exception as e:
                error = str(e)
                killed = True
                mutant_passed = False
        else:
            killed = False

        duration_ms = (time.time() - start_time) * 1000.0

        return MutationResult(
            strategy=strategy,
            killed=killed,
            original_passed=original_passed,
            mutant_passed=mutant_passed,
            duration_ms=duration_ms,
            error=error
        )

    def test_adequacy(self, gate: Any, cwd: Optional[Path] = None) -> AdequacyReport:
        results = []
        
        # Apply applicable strategies
        strategies = [MutationStrategy.NEGATE_EXIT, MutationStrategy.ENV_INJECTION]
        if gate.expect:
            strategies.append(MutationStrategy.CORRUPT_EXPECT)
            
        strategies_tested = 0
        strategies_killed = 0
        
        for strategy in strategies:
            result = self.mutate(gate, strategy, cwd)
            results.append(result)
            
            if strategy != MutationStrategy.ENV_INJECTION:
                strategies_tested += 1
                if result.killed:
                    strategies_killed += 1

        kill_rate = (strategies_killed / strategies_tested) if strategies_tested > 0 else 1.0
        weak = kill_rate < 1.0
        
        # If original didn't pass, we might consider it weak or kill rate 0?
        # Actually, if the original doesn't pass, our strategies aren't tested effectively.
        # But wait, original_passed=False means mutant_passed=False -> killed=False -> weak=True.

        return AdequacyReport(
            gate_id=gate.id,
            strategies_tested=strategies_tested,
            strategies_killed=strategies_killed,
            kill_rate=kill_rate,
            weak=weak,
            results=results
        )


class EvolutionMutationType(str, Enum):
    """Classification of mutations proposed by the evolution engine."""
    GRAPH_PARTITION = "GRAPH_PARTITION"        # Ownership partitioning
    GRAPH_CONTRACT = "GRAPH_CONTRACT"          # InterfaceContract injection
    GATE_STRENGTHEN = "GATE_STRENGTHEN"        # Tighten expect pattern
    GATE_STABILIZE = "GATE_STABILIZE"          # Fix flaky gate
    PERSONA_PROMOTE = "PERSONA_PROMOTE"        # Specialize persona
    CONCURRENCY_SCALE = "CONCURRENCY_SCALE"    # Adjust worker pool
    ANTI_GOODHART_VETO = "ANTI_GOODHART_VETO"  # Blocked mutation


@dataclass
class MutationEntry:
    """A single proposed mutation with type, description, and affected targets."""
    mutation_type: EvolutionMutationType
    description: str
    target_id: str = ""        # node_id, gate_id, or graph-level
    vetoed: bool = False       # True if anti-Goodhart blocked this


@dataclass
class MutationProposal:
    """Structured mutation output from a single evolution pass.

    Every generation produces exactly one proposal. An empty proposal
    (zero entries) signals convergence — no mutations needed.
    """
    generation: int
    entries: List[MutationEntry] = field(default_factory=list)
    vetoes: List[MutationEntry] = field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0  # Filled after next gen runs

    @property
    def is_empty(self) -> bool:
        """True when no mutations proposed — signals convergence."""
        return len(self.entries) == 0

    @property
    def descriptions(self) -> List[str]:
        """Flat list of mutation description strings for backward compat."""
        return [e.description for e in self.entries]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generation": self.generation,
            "entries": [
                {
                    "mutation_type": e.mutation_type.value,
                    "description": e.description,
                    "target_id": e.target_id,
                    "vetoed": e.vetoed,
                }
                for e in self.entries
            ],
            "vetoes": [
                {
                    "mutation_type": v.mutation_type.value,
                    "description": v.description,
                    "target_id": v.target_id,
                    "vetoed": True,
                }
                for v in self.vetoes
            ],
            "score_before": self.score_before,
            "score_after": self.score_after,
        }


class EvolutionMutator:
    """Proposes structured mutations from Judge reports and trend data.

    Consumes RunQualityReport friction points and TrendAnalyzer signals
    to produce a MutationProposal. Anti-Goodhart vetoes are recorded
    but never applied.
    """

    @classmethod
    def propose(
        cls,
        generation: int,
        friction_points: List[Any],
        score: float,
        flaky_gates: Optional[List[Any]] = None,
        regressions: Optional[List[Any]] = None,
    ) -> MutationProposal:
        """Build a MutationProposal from raw friction/trend signals."""
        proposal = MutationProposal(generation=generation, score_before=score)

        for fp in friction_points:
            cat = getattr(fp, "category", "") if not isinstance(fp, dict) else fp.get("category", "")
            msg = getattr(fp, "message", "") if not isinstance(fp, dict) else fp.get("message", "")
            node_id = getattr(fp, "node_id", "") if not isinstance(fp, dict) else fp.get("node_id", "")
            gate_id = getattr(fp, "gate_id", "") if not isinstance(fp, dict) else fp.get("gate_id", "")
            details = getattr(fp, "details", {}) if not isinstance(fp, dict) else fp.get("details", {})

            if cat == "SERIAL_CONFLICT":
                path = details.get("path") or details.get("file_path") or ""
                proposal.entries.append(MutationEntry(
                    mutation_type=EvolutionMutationType.GRAPH_PARTITION,
                    description=f"Partition ownership of '{path}' to eliminate serial conflict",
                    target_id=path,
                ))
            elif cat == "REVISION_THRASH":
                proposal.entries.append(MutationEntry(
                    mutation_type=EvolutionMutationType.GRAPH_CONTRACT,
                    description=f"Inject InterfaceContract for thrashing node '{node_id}'",
                    target_id=node_id or "unknown",
                ))
            elif cat == "GATE_FAILURE":
                proposal.entries.append(MutationEntry(
                    mutation_type=EvolutionMutationType.GATE_STRENGTHEN,
                    description=f"Strengthen failing gate verification: {msg}",
                    target_id=gate_id or "",
                ))
            elif cat == "PERSONA_THRASH":
                proposal.entries.append(MutationEntry(
                    mutation_type=EvolutionMutationType.PERSONA_PROMOTE,
                    description=f"Promote persona on node '{node_id}' to specialist",
                    target_id=node_id or "",
                ))
            elif cat == "BUDGET_PRESSURE":
                proposal.entries.append(MutationEntry(
                    mutation_type=EvolutionMutationType.CONCURRENCY_SCALE,
                    description=f"Scale concurrency to reduce budget pressure: {msg}",
                    target_id="graph",
                ))

        # Trend-driven mutations
        if flaky_gates:
            for fg in flaky_gates:
                gid = getattr(fg, "gate_id", "") if not isinstance(fg, dict) else fg.get("gate_id", "")
                proposal.entries.append(MutationEntry(
                    mutation_type=EvolutionMutationType.GATE_STABILIZE,
                    description=f"Stabilize flaky gate '{gid}' with deterministic isolation",
                    target_id=gid,
                ))

        if regressions:
            for reg in regressions:
                metric = getattr(reg, "metric_name", "") if not isinstance(reg, dict) else reg.get("metric_name", "")
                if metric == "pass_rate":
                    proposal.entries.append(MutationEntry(
                        mutation_type=EvolutionMutationType.GATE_STRENGTHEN,
                        description=f"Address pass_rate regression across recent runs",
                        target_id="trend",
                    ))

        return proposal
