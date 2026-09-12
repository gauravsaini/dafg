"""Compounding Telemetry — Trend Store & Session Briefing.

Every gate run appends results to a JSONL trend store.
Session N starts with 'here's what was flaky last time.'
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class GateRunRecord:
    """Result of a single gate execution within a run."""
    gate_id: str
    status: str           # MET, FAILED, UNAPPROVED, ABANDONED
    duration_ms: float = 0.0
    evidence_strength: str = "NONE"  # NONE, PENDING, MODEL_JUDGMENT, STRING_MATCH, EXECUTABLE_PROOF
    error: Optional[str] = None


@dataclass  
class RunSummary:
    """Summary of a complete gate ledger run."""
    run_id: str
    timestamp: str
    gate_results: Dict[str, GateRunRecord]  # gate_id -> record; stored as dicts in JSON
    total_wall_time_ms: float = 0.0
    outcome: str = "COMPLETE"  # COMPLETE, PARTIAL, FAILED
    gates_met: int = 0
    gates_failed: int = 0
    gates_total: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = {
            'run_id': self.run_id,
            'timestamp': self.timestamp,
            'gate_results': {k: asdict(v) for k, v in self.gate_results.items()},
            'total_wall_time_ms': self.total_wall_time_ms,
            'outcome': self.outcome,
            'gates_met': self.gates_met,
            'gates_failed': self.gates_failed,
            'gates_total': self.gates_total,
        }
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RunSummary:
        gate_results = {}
        for gid, rec in data.get('gate_results', {}).items():
            if isinstance(rec, dict):
                gate_results[gid] = GateRunRecord(**rec)
            else:
                gate_results[gid] = rec
        return cls(
            run_id=data['run_id'],
            timestamp=data['timestamp'],
            gate_results=gate_results,
            total_wall_time_ms=data.get('total_wall_time_ms', 0.0),
            outcome=data.get('outcome', 'COMPLETE'),
            gates_met=data.get('gates_met', 0),
            gates_failed=data.get('gates_failed', 0),
            gates_total=data.get('gates_total', 0),
        )


@dataclass
class FlakyGate:
    """A gate that flips between MET and FAILED across recent runs."""
    gate_id: str
    flip_count: int       # Number of status transitions
    last_n_results: List[str]  # Recent statuses e.g. ['MET','FAILED','MET']
    confidence: float     # 0.0-1.0, lower = more flaky


@dataclass
class Regression:
    """A metric that worsened compared to recent history."""
    metric_name: str
    previous_mean: float
    current_value: float
    delta_pct: float      # Percentage change (negative = regression)


class TrendStore:
    """Append-only JSONL store for gate run results."""

    def __init__(self, filepath: Optional[str | Path] = None):
        self.filepath = Path(filepath) if filepath else Path("eval_results/trends.jsonl")

    def append_run(self, summary: RunSummary) -> None:
        """Append a run summary to the trend store."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(summary.to_dict())
        with open(self.filepath, 'a', encoding='utf-8') as f:
            f.write(line + '\n')

    def load_runs(self, limit: Optional[int] = None) -> List[RunSummary]:
        """Load run summaries from the trend store."""
        if not self.filepath.exists():
            return []
        runs = []
        with open(self.filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        if not isinstance(data, dict):
                            continue
                        runs.append(RunSummary.from_dict(data))
                    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                        continue  # Skip malformed lines
        if limit is not None:
            runs = runs[-limit:]
        return runs

    def clear(self) -> None:
        """Clear the trend store."""
        if self.filepath.exists():
            self.filepath.unlink()


class TrendAnalyzer:
    """Analyzes trend store data for flaky gates, regressions, and bottlenecks."""

    def __init__(self, store: TrendStore):
        self.store = store

    def get_flaky_gates(self, window: int = 10) -> List[FlakyGate]:
        """Find gates that flip between MET and FAILED across recent runs."""
        runs = self.store.load_runs(limit=window)
        if len(runs) < 2:
            return []

        # Collect per-gate status sequences
        gate_sequences: Dict[str, List[str]] = {}
        for run in runs:
            for gid, rec in run.gate_results.items():
                if gid not in gate_sequences:
                    gate_sequences[gid] = []
                gate_sequences[gid].append(rec.status)

        flaky = []
        for gid, statuses in gate_sequences.items():
            if len(statuses) < 2:
                continue
            flips = sum(1 for i in range(1, len(statuses)) if statuses[i] != statuses[i-1])
            if flips >= 1:  # At least one flip
                confidence = 1.0 - (flips / (len(statuses) - 1))
                flaky.append(FlakyGate(
                    gate_id=gid,
                    flip_count=flips,
                    last_n_results=statuses,
                    confidence=round(confidence, 3),
                ))

        return sorted(flaky, key=lambda f: f.flip_count, reverse=True)

    def get_regression_signals(self, window: int = 10) -> List[Regression]:
        """Find metrics that regressed compared to the historical window."""
        runs = self.store.load_runs(limit=window)
        if len(runs) < 2:
            return []

        regressions = []

        # Check wall time regression
        wall_times = [r.total_wall_time_ms for r in runs if r.total_wall_time_ms > 0]
        if len(wall_times) >= 2:
            prev_mean = sum(wall_times[:-1]) / len(wall_times[:-1])
            current = wall_times[-1]
            if prev_mean > 0:
                delta = ((current - prev_mean) / prev_mean) * 100
                if delta > 20:  # >20% slower
                    regressions.append(Regression(
                        metric_name="total_wall_time_ms",
                        previous_mean=round(prev_mean, 1),
                        current_value=round(current, 1),
                        delta_pct=round(delta, 1),
                    ))

        # Check pass rate regression
        pass_rates = []
        for r in runs:
            if r.gates_total > 0:
                pass_rates.append(r.gates_met / r.gates_total)
        if len(pass_rates) >= 2:
            prev_mean = sum(pass_rates[:-1]) / len(pass_rates[:-1])
            current = pass_rates[-1]
            if prev_mean > 0:
                delta = ((current - prev_mean) / prev_mean) * 100
                if delta < -10:  # >10% worse pass rate
                    regressions.append(Regression(
                        metric_name="pass_rate",
                        previous_mean=round(prev_mean, 3),
                        current_value=round(current, 3),
                        delta_pct=round(delta, 1),
                    ))

        return regressions

    def get_bottleneck_gates(self, window: int = 10, threshold_pct: float = 30.0) -> List[Tuple[str, float]]:
        """Find gates consuming >threshold% of total wall time."""
        runs = self.store.load_runs(limit=window)
        if not runs:
            return []

        # Accumulate per-gate total duration
        gate_durations: Dict[str, float] = {}
        total_duration = 0.0
        for run in runs:
            for gid, rec in run.gate_results.items():
                gate_durations[gid] = gate_durations.get(gid, 0.0) + rec.duration_ms
                total_duration += rec.duration_ms

        if total_duration <= 0:
            return []

        bottlenecks = []
        for gid, dur in gate_durations.items():
            pct = (dur / total_duration) * 100
            if pct >= threshold_pct:
                bottlenecks.append((gid, round(pct, 1)))

        return sorted(bottlenecks, key=lambda x: x[1], reverse=True)

    def generate_briefing(self, window: int = 10) -> str:
        """Generate a human-readable session briefing."""
        runs = self.store.load_runs(limit=window)
        if not runs:
            return "No previous runs recorded."

        lines = []
        lines.append(f"=== Session Briefing ({len(runs)} recent runs) ===")

        # Last run summary
        last = runs[-1]
        lines.append(f"Last run: {last.timestamp} — {last.gates_met}/{last.gates_total} gates met ({last.outcome})")

        # Flaky gates
        flaky = self.get_flaky_gates(window)
        if flaky:
            lines.append(f"\n⚠ Flaky gates ({len(flaky)}):")
            for fg in flaky[:5]:
                seq = " → ".join(fg.last_n_results[-5:])
                lines.append(f"  {fg.gate_id}: {fg.flip_count} flip(s), confidence={fg.confidence} [{seq}]")

        # Regressions
        regressions = self.get_regression_signals(window)
        if regressions:
            lines.append(f"\n⚠ Regressions ({len(regressions)}):")
            for reg in regressions:
                lines.append(f"  {reg.metric_name}: {reg.previous_mean} → {reg.current_value} ({reg.delta_pct:+.1f}%)")

        # Bottlenecks
        bottlenecks = self.get_bottleneck_gates(window)
        if bottlenecks:
            lines.append(f"\n⏱ Bottleneck gates:")
            for gid, pct in bottlenecks[:3]:
                lines.append(f"  {gid}: {pct}% of total wall time")

        if not flaky and not regressions and not bottlenecks:
            lines.append("\n✓ No flaky gates, regressions, or bottlenecks detected.")

        return "\n".join(lines)
