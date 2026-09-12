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
