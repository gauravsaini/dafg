"""Adversarial Inspection — Search for Worst Case.

Instead of confirming with curated presets, search for the parameters
where things break. Integrates with the dormant CHALLENGING protocol state.
"""
from __future__ import annotations

import itertools
import json
import os
import random
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from dafg.runtime import FailureClass, RevisionDirective
from dafg.transport import ControlSignal, StreamChannel, StreamFrame


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


def check_token_invariants(
    text: str,
    allowed_owns: Optional[Sequence[str]] = None,
    forbidden_imports: Optional[Sequence[str]] = None,
    forbidden_patterns: Optional[Sequence[str]] = None,
) -> Optional[Tuple[str, str, FailureClass]]:
    """Pure invariant checker for streamed token deltas.

    Evaluates incremental token text against boundary and security contracts:
    - Boundary (OWNS:) contract: disallows modifying or declaring files outside allowed_owns.
    - Security imports contract: disallows importing modules in forbidden_imports.
    - Structural patterns contract: disallows matching regexes in forbidden_patterns.

    Returns:
        Optional tuple of (violation_type, reason, failure_class) if violated, else None.
    """
    if forbidden_imports:
        # Check import statements (e.g. "import os", "from subprocess import Popen", "; import sys")
        import_pattern = r"(?:^|\n|;)\s*(?:from\s+([a-zA-Z0-9_\.]+)\s+import|import\s+([a-zA-Z0-9_\.]+))"
        for match in re.finditer(import_pattern, text):
            mod = match.group(1) or match.group(2)
            if mod:
                root_mod = mod.split(".")[0]
                for fb in forbidden_imports:
                    if root_mod == fb or mod == fb or mod.startswith(fb + "."):
                        return (
                            "FORBIDDEN_IMPORT",
                            f"Security invariant violation: Forbidden import '{mod}' detected in stream",
                            FailureClass.PERMISSION_DENIED,
                        )

        # Check dynamic imports (e.g. __import__('os'))
        dynamic_pattern = r"__import__\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"
        for match in re.finditer(dynamic_pattern, text):
            mod = match.group(1)
            root_mod = mod.split(".")[0]
            for fb in forbidden_imports:
                if root_mod == fb or mod == fb or mod.startswith(fb + "."):
                    return (
                        "FORBIDDEN_IMPORT",
                        f"Security invariant violation: Forbidden dynamic import '{mod}' detected in stream",
                        FailureClass.PERMISSION_DENIED,
                    )

    if allowed_owns is not None:
        allowed_set = {os.path.normpath(p.strip()) for p in allowed_owns}
        allowed_basenames = {os.path.basename(p) for p in allowed_set}

        owns_patterns = [
            r"(?:OWNS|owns|TARGET|target):\s*([a-zA-Z0-9_\-\./\\]+)",
            r"(?:writing to|touching|modifying|creating)\s+([a-zA-Z0-9_\-\./\\]+)",
            r"open\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wa\+][^'\"]*['\"]\)",
        ]
        for pat in owns_patterns:
            for match in re.finditer(pat, text):
                target_file = match.group(1).strip()
                norm_target = os.path.normpath(target_file)
                base_target = os.path.basename(norm_target)
                if norm_target not in allowed_set and base_target not in allowed_basenames:
                    return (
                        "OWNS_VIOLATION",
                        f"Boundary violation: Stream touched file '{target_file}' outside declared ownership {list(allowed_owns)}",
                        FailureClass.INTERFACE_MISMATCH,
                    )

    if forbidden_patterns:
        for pat in forbidden_patterns:
            if re.search(pat, text):
                return (
                    "STRUCTURAL_GATE_BREACH",
                    f"Structural gate breach: Stream matched forbidden pattern '{pat}'",
                    FailureClass.LOCAL_DEFECT,
                )

    return None


@dataclass(frozen=True)
class InterceptionEvent:
    """Immutable event representing a challenger interception trigger."""

    violated: bool
    violation_type: Optional[str] = None
    reason: str = ""
    token_delta: str = ""
    directive: Optional[RevisionDirective] = None
    abort_frame: Optional[StreamFrame] = None
    latency_ms: float = 0.0


class StreamingTokenInspector:
    """Hot-Path Challenger Interceptor (Box 2 of Streaming Triad).

    Taps Channel 0x01 (DATA) token deltas in real-time to enforce invariants:
    - OWNS Invariant: Intercepts when generated tokens declare, touch, or write
      to files outside node.owns or allowed_owns.
    - Forbidden Imports: Intercepts blacklisted modules (e.g. os, subprocess).
    - Structural Gates: Early interception on pattern violations.

    When an invariant is breached, dispatches Channel 0x02 (CONTROL) 0x01 ABORT
    frame with a structured RevisionDirective payload with sub-millisecond latency.
    """

    def __init__(
        self,
        allowed_owns: Optional[Sequence[str]] = None,
        forbidden_imports: Optional[Sequence[str]] = None,
        forbidden_patterns: Optional[Sequence[str]] = None,
        stream_id: int = 1,
        epoch: int = 1,
    ):
        self.allowed_owns = tuple(allowed_owns) if allowed_owns is not None else None
        self.forbidden_imports = (
            tuple(forbidden_imports)
            if forbidden_imports is not None
            else ("os", "subprocess", "pty", "shutil", "socket")
        )
        self.forbidden_patterns = tuple(forbidden_patterns) if forbidden_patterns is not None else ()
        self.stream_id = stream_id
        self.epoch = epoch
        self._buffer: str = ""
        self._interceptions_count: int = 0
        self._total_inspected_tokens: int = 0
        self._last_event: Optional[InterceptionEvent] = None

    @property
    def buffer(self) -> str:
        return self._buffer

    @property
    def interceptions_count(self) -> int:
        return self._interceptions_count

    @property
    def total_inspected_tokens(self) -> int:
        return self._total_inspected_tokens

    @property
    def last_event(self) -> Optional[InterceptionEvent]:
        return self._last_event

    def reset(self) -> None:
        """Reset internal buffer and tracking state."""
        self._buffer = ""
        self._interceptions_count = 0
        self._total_inspected_tokens = 0
        self._last_event = None

    def inspect_delta(self, token_delta: str, seq: int = 0) -> InterceptionEvent:
        """Inspect a single token delta or text chunk in real time.

        Enforces invariants and returns an InterceptionEvent. If a violation is found,
        constructs a StreamFrame with channel=CONTROL, signal=ABORT and RevisionDirective.
        """
        t0 = time.perf_counter()
        self._buffer += token_delta
        self._total_inspected_tokens += 1

        check = check_token_invariants(
            text=self._buffer,
            allowed_owns=self.allowed_owns,
            forbidden_imports=self.forbidden_imports,
            forbidden_patterns=self.forbidden_patterns,
        )

        latency_ms = (time.perf_counter() - t0) * 1000.0

        if check is not None:
            violation_type, reason, failure_class = check
            self._interceptions_count += 1
            directive = RevisionDirective(
                verdict="ABORT",
                failure_class=failure_class,
                feedback=reason,
                repair_scope="LOCAL_ONLY",
            )
            abort_payload = json.dumps(directive.to_dict()).encode("utf-8")
            abort_frame = StreamFrame(
                stream_id=self.stream_id,
                channel=StreamChannel.CONTROL,
                seq=seq + 1,
                signal=ControlSignal.ABORT,
                epoch=self.epoch,
                payload=abort_payload,
            )
            event = InterceptionEvent(
                violated=True,
                violation_type=violation_type,
                reason=reason,
                token_delta=token_delta,
                directive=directive,
                abort_frame=abort_frame,
                latency_ms=latency_ms,
            )
            self._last_event = event
            return event

        event = InterceptionEvent(
            violated=False,
            token_delta=token_delta,
            latency_ms=latency_ms,
        )
        self._last_event = event
        return event

    def inspect_frame(self, frame: StreamFrame) -> Optional[StreamFrame]:
        """Inspect a StreamFrame; returns an ABORT StreamFrame if an invariant is breached."""
        if frame.channel != StreamChannel.DATA:
            return None
        text_chunk = frame.payload.decode("utf-8", errors="replace")
        event = self.inspect_delta(text_chunk, seq=frame.seq)
        if event.violated:
            return event.abort_frame
        return None
