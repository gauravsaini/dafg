"""Adversarial Inspection — Search for Worst Case.

Instead of confirming with curated presets, search for the parameters
where things break. Integrates with the dormant CHALLENGING protocol state.
"""
from __future__ import annotations

import itertools
import os
import random
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


class SearchStrategy(str, Enum):
    GRID = "GRID"           # Exhaustive grid search
    RANDOM = "RANDOM"       # Random sampling
    ADAPTIVE = "ADAPTIVE"   # Focus on worst-performing regions


@dataclass
class ParameterSpace:
    """Defines the parameter space for adversarial search."""
    dimensions: Dict[str, List[Any]]   # param_name -> list of values
    
    @classmethod
    def parse(cls, spec: str) -> ParameterSpace:
        """Parse parameter spec string like 'camera_angle=0:360:15,zoom=0.5:2.0:0.5'
        
        Format: param=start:stop:step,param=start:stop:step
        Or: param=val1;val2;val3 for explicit values
        """
        dims: Dict[str, List[Any]] = {}
        if not spec or not spec.strip():
            return cls(dimensions=dims)
        
        for part in spec.split(','):
            part = part.strip()
            if '=' not in part:
                continue
            name, values_str = part.split('=', 1)
            name = name.strip()
            values_str = values_str.strip()
            
            if ':' in values_str:
                # Range format: start:stop:step
                parts = values_str.split(':')
                try:
                    if '.' in values_str:
                        start, stop, step = float(parts[0]), float(parts[1]), float(parts[2])
                        vals = []
                        v = start
                        while v <= stop + 1e-9:
                            vals.append(round(v, 6))
                            v += step
                    else:
                        start, stop, step = int(parts[0]), int(parts[1]), int(parts[2])
                        vals = list(range(start, stop + 1, step))
                except (ValueError, IndexError):
                    continue
                dims[name] = vals
            elif ';' in values_str:
                # Explicit values: val1;val2;val3
                dims[name] = [v.strip() for v in values_str.split(';')]
            else:
                dims[name] = [values_str]
        
        return cls(dimensions=dims)
    
    @property
    def total_combinations(self) -> int:
        if not self.dimensions:
            return 0
        total = 1
        for vals in self.dimensions.values():
            total *= len(vals)
        return total


@dataclass
class Evaluation:
    """Result of a single adversarial evaluation."""
    params: Dict[str, Any]
    score: float              # The objective metric value
    passed: bool              # Whether the gate passed with these params
    duration_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class AdversarialResult:
    """Result of an adversarial search."""
    gate_id: str
    worst_params: Dict[str, Any]    # Parameters that produced worst score
    worst_score: float              # The worst (highest diff, lowest quality) score found
    best_params: Dict[str, Any]     # Parameters that produced best score
    best_score: float
    all_evaluations: List[Evaluation] = field(default_factory=list)
    coverage_pct: float = 0.0       # Fraction of parameter space explored
    found_failure: bool = False     # Did we find params that make the gate fail?
    budget_used: int = 0
    strategy: str = "GRID"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['all_evaluations'] = [asdict(e) for e in self.all_evaluations]
        return d


class AdversarialInspector:
    """Searches for the parameters where a gate performs worst."""

    def __init__(
        self,
        timeout: float = 30.0,
    ):
        self.timeout = timeout

    def search(
        self,
        gate,  # Gate object
        param_space: ParameterSpace,
        strategy: SearchStrategy = SearchStrategy.GRID,
        budget: int = 50,
        objective: str = "exit_code",  # What to maximize (exit_code, diff_ratio, etc.)
        cwd: Optional[Path] = None,
    ) -> AdversarialResult:
        """Explore parameter space to find worst-case gate parameters."""
        if not gate.check or not param_space.dimensions:
            return AdversarialResult(
                gate_id=gate.id,
                worst_params={},
                worst_score=0.0,
                best_params={},
                best_score=0.0,
                strategy=strategy.value,
            )

        # Generate candidate parameter combinations
        candidates = self._generate_candidates(param_space, strategy, budget)
        
        evaluations = []
        worst_eval = None
        best_eval = None
        
        for params in candidates:
            start = time.monotonic()
            score, passed, error = self._evaluate(gate, params, objective, cwd)
            duration = (time.monotonic() - start) * 1000
            
            ev = Evaluation(
                params=dict(params),
                score=score,
                passed=passed,
                duration_ms=duration,
                error=error,
            )
            evaluations.append(ev)
            
            if worst_eval is None or score > worst_eval.score:
                worst_eval = ev
            if best_eval is None or score < best_eval.score:
                best_eval = ev
            
            # Adaptive: if we found a failure, explore nearby
            if strategy == SearchStrategy.ADAPTIVE and not passed:
                nearby = self._generate_nearby(params, param_space, count=3)
                for np in nearby:
                    if len(evaluations) >= budget:
                        break
                    s2 = time.monotonic()
                    sc, pa, er = self._evaluate(gate, np, objective, cwd)
                    d2 = (time.monotonic() - s2) * 1000
                    ev2 = Evaluation(params=dict(np), score=sc, passed=pa, duration_ms=d2, error=er)
                    evaluations.append(ev2)
                    if sc > worst_eval.score:
                        worst_eval = ev2
                    if sc < best_eval.score:
                        best_eval = ev2
            
            if len(evaluations) >= budget:
                break
        
        total_combos = param_space.total_combinations
        coverage = len(evaluations) / total_combos if total_combos > 0 else 1.0
        
        return AdversarialResult(
            gate_id=gate.id,
            worst_params=worst_eval.params if worst_eval else {},
            worst_score=worst_eval.score if worst_eval else 0.0,
            best_params=best_eval.params if best_eval else {},
            best_score=best_eval.score if best_eval else 0.0,
            all_evaluations=evaluations,
            coverage_pct=round(min(coverage, 1.0) * 100, 1),
            found_failure=any(not e.passed for e in evaluations),
            budget_used=len(evaluations),
            strategy=strategy.value,
        )

    def _generate_candidates(
        self,
        space: ParameterSpace,
        strategy: SearchStrategy,
        budget: int,
    ) -> List[Dict[str, Any]]:
        if not space.dimensions:
            return []

        keys = list(space.dimensions.keys())
        value_lists = [space.dimensions[k] for k in keys]

        if strategy == SearchStrategy.GRID:
            # Full grid, capped at budget
            candidates = []
            for combo in itertools.product(*value_lists):
                candidates.append(dict(zip(keys, combo)))
                if len(candidates) >= budget:
                    break
            return candidates

        elif strategy == SearchStrategy.RANDOM:
            candidates = []
            for _ in range(budget):
                params = {k: random.choice(vals) for k, vals in zip(keys, value_lists)}
                candidates.append(params)
            return candidates

        elif strategy == SearchStrategy.ADAPTIVE:
            # Start with random sample, then adapt (adaptation happens in search())
            candidates = []
            initial = min(budget // 2, 10)
            for _ in range(initial):
                params = {k: random.choice(vals) for k, vals in zip(keys, value_lists)}
                candidates.append(params)
            return candidates

        return []

    def _evaluate(
        self,
        gate,
        params: Dict[str, Any],
        objective: str,
        cwd: Optional[Path],
    ) -> Tuple[float, bool, Optional[str]]:
        """Evaluate the gate with given parameters.
        
        Returns (score, passed, error).
        Score should be HIGHER for worse results (adversarial objective).
        """
        # Inject parameters as environment variables
        env = dict(os.environ)
        for k, v in params.items():
            env[f"DAFG_ADV_{k.upper()}"] = str(v)
        
        check_cmd = gate.check
        work_dir = str(cwd) if cwd else None
        
        try:
            proc = subprocess.run(
                check_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=work_dir,
                env=env,
            )
            
            exit_code = proc.returncode
            combined = (proc.stdout or '') + (proc.stderr or '')
            
            # Check EXPECT match
            expect_matched = True
            if gate.expect:
                expect_matched = bool(re.search(gate.expect, combined))
            
            passed = (exit_code == 0) and expect_matched
            
            # Score: higher = worse. Use exit code as base.
            if objective == "exit_code":
                score = float(exit_code) + (0.0 if expect_matched else 0.5)
            elif objective == "diff_ratio":
                # Try to extract diff_ratio from output
                m = re.search(r'diff_ratio=([\d.]+)', combined)
                score = float(m.group(1)) if m else (1.0 if not passed else 0.0)
            else:
                score = 0.0 if passed else 1.0
            
            return score, passed, None
            
        except subprocess.TimeoutExpired:
            return 1.0, False, "timeout"
        except Exception as e:
            return 1.0, False, str(e)

    def _generate_nearby(
        self,
        params: Dict[str, Any],
        space: ParameterSpace,
        count: int = 3,
    ) -> List[Dict[str, Any]]:
        """Generate parameter combinations near the given params."""
        nearby = []
        for _ in range(count):
            new_params = dict(params)
            # Perturb one random dimension
            if space.dimensions:
                dim = random.choice(list(space.dimensions.keys()))
                new_params[dim] = random.choice(space.dimensions[dim])
            nearby.append(new_params)
        return nearby
