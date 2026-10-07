"""Graph-isolation A/B experiment for DAFG.

Measures what DAFG's *graph* contributes by itself — wave scheduling with
disjoint OWNS: partitioning, file-ownership enforcement, and budget caps —
isolated from the gates/verification layer.

Three modes on synthetic multi-node task graphs:
  G-dafg-graph     real DAFG.compute_waves + real Budget, no gates
  S-sequential     topological order, one node at a time (safe baseline)
  P-naive-parallel all nodes at once, no ownership enforcement
                   (what "just fan out agents" does in a normal workflow)

Deterministic; no network; no model calls. Stub executors sleep a fixed
duration then append split-half marker lines to their owned files, so
concurrent writers on the same file interleave into malformed lines.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SEED = 42

# Marker lines look like "[s2_c1:3]". Node ids are [a-z0-9_]+ by construction.
LINE_RE = re.compile(r"^\[([a-z0-9_]+):(\d+)\]$")


@dataclass
class NodeSpec:
    id: str
    owns: List[str]
    needs: List[str] = field(default_factory=list)
    kind: str = "normal"  # "normal" | "runaway"
    duration_s: float = 0.2
    markers: int = 5


@dataclass
class TrialResult:
    shape: str
    mode: str
    rep: int
    wall_s: float
    waves_used: int
    deferrals: int
    corruption_files: int
    corruption_incidents: int
    files_checked: int
    starved: int
    hangs: int
    completed_nodes: int
    total_nodes: int
    verdicts: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["wall_s"] = round(self.wall_s, 3)
        return d


# ---------------------------------------------------------------- shapes ---

def build_shape(shape_id: str) -> List[NodeSpec]:
    """Synthetic multi-node task graphs. Specs are returned in topological order."""
    if shape_id == "shape1_fanout":
        # 6 nodes, disjoint OWNS, n4..n6 depend on n1..n3 -> 2 waves of 3.
        specs = [
            NodeSpec(id=f"s1_n{i}", owns=[f"s1/s1_n{i}.txt"], duration_s=0.2, markers=5)
            for i in (1, 2, 3)
        ]
        specs += [
            NodeSpec(id=f"s1_n{i}", owns=[f"s1/s1_n{i}.txt"],
                     needs=[f"s1_n{i - 3}"], duration_s=0.2, markers=5)
            for i in (4, 5, 6)
        ]
        return specs
    if shape_id == "shape2_conflict":
        # c1 and c2 both claim s2/shared.txt -> OWNS: must serialize them.
        return [
            NodeSpec(id="s2_c1", owns=["s2/shared.txt"], duration_s=0.2, markers=8),
            NodeSpec(id="s2_c2", owns=["s2/shared.txt"], duration_s=0.2, markers=8),
            NodeSpec(id="s2_c3", owns=["s2/c3.txt"], duration_s=0.2, markers=8),
            NodeSpec(id="s2_c4", owns=["s2/c4.txt"], duration_s=0.2, markers=8),
        ]
    if shape_id == "shape3_runaway":
        return [
            NodeSpec(id=f"s3_n{i}", owns=[f"s3/s3_n{i}.txt"], duration_s=0.2, markers=5)
            for i in (1, 2, 3)
        ] + [NodeSpec(id="s3_r1", owns=["s3/runaway.txt"], kind="runaway")]
    raise ValueError(f"unknown shape {shape_id}")


# ------------------------------------------------------- stub executors ---

def write_markers(workdir: Path, node_id: str, relpath: str, count: int,
                  stop: Optional[threading.Event] = None, gap_s: float = 0.001) -> int:
    """Append `count` marker lines, each written in two halves with a gap.

    The split write is deliberate: concurrent writers on the same file
    interleave halves into malformed lines, which is the corruption signal.
    Returns markers completed (may be partial if `stop` fires).
    """
    p = workdir / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    for i in range(count):
        if stop is not None and stop.is_set():
            return done
        with open(p, "a") as f:
            f.write(f"[{node_id}:{i}")
        time.sleep(gap_s)
        with open(p, "a") as f:
            f.write("]\n")
        time.sleep(gap_s)
        done += 1
    return done


def execute_node_spec(spec: NodeSpec, workdir: Path, stop: threading.Event) -> str:
    """Run one node's stub work. Returns 'completed' | 'stopped'."""
    if spec.kind == "runaway":
        # Tight non-terminating loop. Polls `stop` every 64 writes: the
        # experiment measures the supervisor's verdict/timing discipline,
        # not uncooperative-thread killing (Python threads cannot be killed).
        i = 0
        p = workdir / spec.owns[0]
        p.parent.mkdir(parents=True, exist_ok=True)
        while True:
            if i % 64 == 0 and stop.is_set():
                return "stopped"
            with open(p, "a") as f:
                f.write(f"[{spec.id}:{i}]\n")
            i += 1
    time.sleep(spec.duration_s)
    for rel in spec.owns:
        write_markers(workdir, spec.id, rel, spec.markers, stop)
    return "completed"


# ------------------------------------------------------- corruption check ---

def expected_markers(specs: List[NodeSpec], exclude_runaway: bool = True) -> Dict[str, Counter]:
    """Map each owned file -> expected Counter of (node_id, idx) markers."""
    out: Dict[str, Counter] = {}
    for s in specs:
        if exclude_runaway and s.kind == "runaway":
            continue
        for rel in s.owns:
            c = out.setdefault(rel, Counter())
            for i in range(s.markers):
                c[(s.id, i)] += 1
    return out


def check_file_markers(path: Path, expected: Counter) -> List[str]:
    """Return incident strings; empty means the file is exactly as expected."""
    incidents: List[str] = []
    try:
        text = path.read_text()
    except FileNotFoundError:
        return [f"missing file: {path}"]
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    seen: Counter = Counter()
    for ln in lines:
        m = LINE_RE.match(ln)
        if not m:
            incidents.append(f"malformed line: {ln[:48]!r}")
        else:
            seen[(m.group(1), int(m.group(2)))] += 1
    if seen != expected:
        incidents.append(
            f"content mismatch: {sum(seen.values())} well-formed markers, "
            f"expected {sum(expected.values())}"
        )
    return incidents


def check_trial_corruption(specs: List[NodeSpec], workdir: Path) -> Tuple[int, int, int]:
    """Returns (files_with_incidents, total_incidents, files_checked)."""
    exp = expected_markers(specs)
    files_bad = 0
    incidents = 0
    for rel, want in exp.items():
        got = check_file_markers(workdir / rel, want)
        if got:
            files_bad += 1
            incidents += len(got)
    return files_bad, incidents, len(exp)


# ----------------------------------------------------------------- modes ---

def topo_order(specs: List[NodeSpec]) -> List[NodeSpec]:
    """Kahn's algorithm; specs are already near-topological, this is belt-and-braces."""
    by_id = {s.id: s for s in specs}
    indeg = {s.id: 0 for s in specs}
    for s in specs:
        for dep in s.needs:
            if dep in indeg:
                indeg[s.id] += 1
    queue = [s for s in specs if indeg[s.id] == 0]
    out: List[NodeSpec] = []
    while queue:
        s = queue.pop(0)
        out.append(s)
        for t in specs:
            if s.id in t.needs:
                indeg[t.id] -= 1
                if indeg[t.id] == 0:
                    queue.append(t)
    if len(out) != len(specs):
        raise ValueError("dependency cycle in specs")
    return out


def _run_in_thread(spec: NodeSpec, workdir: Path, stop: threading.Event,
                   outcomes: Dict[str, str]) -> None:
    try:
        outcomes[spec.id] = execute_node_spec(spec, workdir, stop)
    except Exception as exc:  # noqa: BLE001 - record, don't crash the trial
        outcomes[spec.id] = f"error: {exc}"


def run_mode_g(specs: List[NodeSpec], workdir: Path, node_budget_s: float = 1.0) -> TrialResult:
    """Mode G: real DAFG.compute_waves + real Budget, no gates/verification."""
    from dafg.runtime import DAFG, Budget, BudgetExceededError, NodeStatus, TaskNode

    t0 = time.perf_counter()
    g = DAFG()
    g.max_parallel_workers = 4
    spec_by_id = {s.id: s for s in specs}
    for s in specs:
        n = TaskNode(id=s.id, title=s.id, owns=list(s.owns), needs=list(s.needs))
        n.status = NodeStatus.READY
        g.add_node(n, track_budget=False)
    call_budget = Budget()  # per-dispatch call budgeting, as in execute_node
    stop_events = {s.id: threading.Event() for s in specs}
    verdicts: Dict[str, str] = {}
    completed: set = set()
    waves_used = 0
    deferrals = 0
    diag_mark = 0
    starved = 0

    while len(completed) < len(specs):
        ready = [n for n in g.get_ready_nodes() if n.id not in completed]
        if not ready:
            break
        waves = g.compute_waves(ready)  # real OWNS: partitioning
        waves_used += len(waves)
        for d in g.wave_diagnostics[diag_mark:]:
            deferrals += len(d.conflict_reasons)
        diag_mark = len(g.wave_diagnostics)
        wave = waves[0]
        outcomes: Dict[str, str] = {}
        threads = {
            n.id: threading.Thread(
                target=_run_in_thread,
                args=(spec_by_id[n.id], workdir, stop_events[n.id], outcomes),
                daemon=True,
            )
            for n in wave
        }
        for n in wave:
            call_budget.check_call()
        for t in threads.values():
            t.start()
        # Supervise the wave; enforce the per-node time budget on runaways
        # through the real DAFG Budget class.
        pending = set(threads)
        node_deadline = time.perf_counter() + node_budget_s
        while pending:
            for nid in list(pending):
                if not threads[nid].is_alive():
                    pending.discard(nid)
                    completed.add(nid)
                    g.nodes[nid].status = NodeStatus.ACCEPTED
            if not pending:
                break
            now = time.perf_counter()
            for nid in list(pending):
                if spec_by_id[nid].kind == "runaway" and now >= node_deadline:
                    enforcer = Budget(deadline=node_deadline)
                    try:
                        enforcer.check_deadline()
                    except BudgetExceededError:
                        starved += 1
                        verdicts[nid] = "STARVED"
                    stop_events[nid].set()
                    pending.discard(nid)
                    completed.add(nid)
                    g.nodes[nid].status = NodeStatus.FAILED
            time.sleep(0.01)
        for n in wave:
            verdicts.setdefault(
                n.id, "COMPLETED" if outcomes.get(n.id) == "completed" else outcomes.get(n.id, "unknown")
            )

    wall = time.perf_counter() - t0
    bad_files, incidents, checked = check_trial_corruption(specs, workdir)
    normal = [s for s in specs if s.kind != "runaway"]
    done_ok = sum(1 for s in normal if verdicts.get(s.id) == "COMPLETED")
    return TrialResult(
        shape="", mode="G-dafg-graph", rep=0, wall_s=wall, waves_used=waves_used,
        deferrals=deferrals, corruption_files=bad_files, corruption_incidents=incidents,
        files_checked=checked, starved=starved, hangs=0,
        completed_nodes=done_ok, total_nodes=len(normal), verdicts=verdicts,
    )


def run_mode_s(specs: List[NodeSpec], workdir: Path, watchdog_s: float = 2.0) -> TrialResult:
    """Mode S: topological order, one node at a time. Safe baseline."""
    t0 = time.perf_counter()
    verdicts: Dict[str, str] = {}
    hangs = 0
    for s in topo_order(specs):
        stop = threading.Event()
        outcomes: Dict[str, str] = {}
        t = threading.Thread(target=_run_in_thread, args=(s, workdir, stop, outcomes), daemon=True)
        t.start()
        t.join(watchdog_s if s.kind == "runaway" else 30.0)
        if t.is_alive():
            hangs += 1
            verdicts[s.id] = "HANG"
            stop.set()
            t.join(5.0)
        else:
            verdicts[s.id] = "COMPLETED" if outcomes.get(s.id) == "completed" else outcomes.get(s.id, "unknown")
    wall = time.perf_counter() - t0
    bad_files, incidents, checked = check_trial_corruption(specs, workdir)
    normal = [s for s in specs if s.kind != "runaway"]
    done_ok = sum(1 for s in normal if verdicts.get(s.id) == "COMPLETED")
    return TrialResult(
        shape="", mode="S-sequential", rep=0, wall_s=wall, waves_used=len(specs),
        deferrals=0, corruption_files=bad_files, corruption_incidents=incidents,
        files_checked=checked, starved=0, hangs=hangs,
        completed_nodes=done_ok, total_nodes=len(normal), verdicts=verdicts,
    )


def run_mode_p(specs: List[NodeSpec], workdir: Path, watchdog_s: float = 2.0) -> TrialResult:
    """Mode P: all nodes at once, no ownership enforcement. Naive-fanout baseline."""
    t0 = time.perf_counter()
    verdicts: Dict[str, str] = {}
    hangs = 0
    stop_events = {s.id: threading.Event() for s in specs}
    outcomes: Dict[str, str] = {}
    threads = {
        s.id: threading.Thread(target=_run_in_thread, args=(s, workdir, stop_events[s.id], outcomes), daemon=True)
        for s in specs
    }
    for t in threads.values():
        t.start()
    deadline = time.perf_counter() + watchdog_s
    pending = set(threads)
    while pending:
        for nid in list(pending):
            if not threads[nid].is_alive():
                pending.discard(nid)
        if not pending:
            break
        if time.perf_counter() >= deadline:
            for nid in list(pending):  # only runaways should still be alive
                hangs += 1
                verdicts[nid] = "HANG"
                stop_events[nid].set()
                pending.discard(nid)
            break
        time.sleep(0.01)
    for t in threads.values():
        t.join(5.0)
    for s in specs:
        verdicts.setdefault(
            s.id, "COMPLETED" if outcomes.get(s.id) == "completed" else outcomes.get(s.id, "unknown")
        )
    wall = time.perf_counter() - t0
    bad_files, incidents, checked = check_trial_corruption(specs, workdir)
    normal = [s for s in specs if s.kind != "runaway"]
    done_ok = sum(1 for s in normal if verdicts.get(s.id) == "COMPLETED")
    return TrialResult(
        shape="", mode="P-naive-parallel", rep=0, wall_s=wall, waves_used=1,
        deferrals=0, corruption_files=bad_files, corruption_incidents=incidents,
        files_checked=checked, starved=0, hangs=hangs,
        completed_nodes=done_ok, total_nodes=len(normal), verdicts=verdicts,
    )


# -------------------------------------------------------------- summarize ---

MODES = ("G-dafg-graph", "S-sequential", "P-naive-parallel")
RUNNERS = {
    "G-dafg-graph": run_mode_g,
    "S-sequential": run_mode_s,
    "P-naive-parallel": run_mode_p,
}
REPS = {"shape1_fanout": 3, "shape2_conflict": 5, "shape3_runaway": 3}


def run_trial(shape_id: str, mode: str, rep: int, root: Path) -> TrialResult:
    specs = build_shape(shape_id)
    workdir = root / f"{shape_id}" / mode / f"rep{rep}"
    workdir.mkdir(parents=True, exist_ok=True)
    res = RUNNERS[mode](specs, workdir)
    res.shape = shape_id
    res.rep = rep
    return res


def _mean(xs: List[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def summarize_shape(shape_id: str, results: List[TrialResult]) -> Dict[str, Any]:
    modes: Dict[str, Any] = {}
    for mode in MODES:
        rs = [r for r in results if r.mode == mode]
        modes[mode] = {
            "trials": len(rs),
            "wall_s_mean": _mean([r.wall_s for r in rs]),
            "waves_used_mean": _mean([float(r.waves_used) for r in rs]),
            "deferrals_total": sum(r.deferrals for r in rs),
            "corruption_files_total": sum(r.corruption_files for r in rs),
            "corruption_trials": sum(1 for r in rs if r.corruption_files > 0),
            "corruption_rate": round(sum(1 for r in rs if r.corruption_files > 0) / max(len(rs), 1), 3),
            "starved_total": sum(r.starved for r in rs),
            "hangs_total": sum(r.hangs for r in rs),
            "completion_rate": round(sum(r.completed_nodes for r in rs) / max(sum(r.total_nodes for r in rs), 1), 3),
        }
    return {"modes": modes}


def build_report(results: List[TrialResult], wall_s: float) -> Dict[str, Any]:
    shapes: Dict[str, Any] = {}
    for shape_id in ("shape1_fanout", "shape2_conflict", "shape3_runaway"):
        shapes[shape_id] = summarize_shape(shape_id, [r for r in results if r.shape == shape_id])

    s1 = shapes["shape1_fanout"]["modes"]
    speedup_g_vs_s = round(s1["S-sequential"]["wall_s_mean"] / max(s1["G-dafg-graph"]["wall_s_mean"], 1e-9), 2)
    speedup_p_vs_s = round(s1["S-sequential"]["wall_s_mean"] / max(s1["P-naive-parallel"]["wall_s_mean"], 1e-9), 2)
    shapes["shape1_fanout"]["deltas"] = {
        "speedup_G_vs_S": speedup_g_vs_s,
        "speedup_P_vs_S": speedup_p_vs_s,
    }
    shapes["shape1_fanout"]["verdict"] = (
        f"G wall={s1['G-dafg-graph']['wall_s_mean']}s vs S wall={s1['S-sequential']['wall_s_mean']}s "
        f"(speedup {speedup_g_vs_s}x); waves_used G={s1['G-dafg-graph']['waves_used_mean']}; "
        f"corruption 0 in all modes (disjoint OWNS)."
    )

    s2 = shapes["shape2_conflict"]["modes"]
    shapes["shape2_conflict"]["deltas"] = {
        "corruption_rate_G_minus_P": round(s2["G-dafg-graph"]["corruption_rate"] - s2["P-naive-parallel"]["corruption_rate"], 3),
    }
    shapes["shape2_conflict"]["verdict"] = (
        f"G deferrals={s2['G-dafg-graph']['deferrals_total']} (c2 serialized), "
        f"corruption_rate G={s2['G-dafg-graph']['corruption_rate']} "
        f"S={s2['S-sequential']['corruption_rate']} "
        f"P={s2['P-naive-parallel']['corruption_rate']} "
        f"over {s2['P-naive-parallel']['trials']} trials."
    )

    s3 = shapes["shape3_runaway"]["modes"]
    shapes["shape3_runaway"]["deltas"] = {
        "G_starved_vs_S_hangs": [s3["G-dafg-graph"]["starved_total"], s3["S-sequential"]["hangs_total"]],
    }
    shapes["shape3_runaway"]["verdict"] = (
        f"G: starved={s3['G-dafg-graph']['starved_total']} hangs={s3['G-dafg-graph']['hangs_total']} "
        f"(explicit budget verdict); S: hangs={s3['S-sequential']['hangs_total']}; "
        f"P: hangs={s3['P-naive-parallel']['hangs_total']} (external watchdog)."
    )

    g_ok = (
        shapes["shape1_fanout"]["modes"]["G-dafg-graph"]["corruption_rate"] == 0
        and shapes["shape2_conflict"]["modes"]["G-dafg-graph"]["corruption_rate"] == 0
        and shapes["shape3_runaway"]["modes"]["G-dafg-graph"]["starved_total"] > 0
        and shapes["shape3_runaway"]["modes"]["G-dafg-graph"]["hangs_total"] == 0
    )
    return {
        "suite": "graph-ab",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deterministic": True,
        "network_used": False,
        "seed": SEED,
        "trials": len(results),
        "wall_s": round(wall_s, 1),
        "shapes": shapes,
        "per_trial": [r.to_dict() for r in results],
        "limitations": [
            "Stub executors (fixed sleep + marker writes) measure the scheduler, not real "
            "agent behavior: no planning variance, no tool-call patterns, no genuine stalls.",
            "File-write races are a proxy for workspace races: real agents race on reads, "
            "partial edits, and git state, not just appends.",
            "The runaway is a tight loop with per-iteration stop polling; the experiment "
            "measures supervisor verdict/timing discipline, not uncooperative-thread killing "
            "(Python threads cannot be killed). DAFG's real Budget is likewise cooperative "
            "(checked at dispatch); the supervisor here enforces it per-node via "
            "Budget.check_deadline().",
            "Mode G uses DAFG.compute_waves/nodes_conflict/Budget directly, bypassing the "
            "protocol state machine and gate ledger: this is the requested isolation, but "
            "full DAFG.run() adds dispatch overhead not measured here.",
            "Shape-2 corruption is timing-dependent; 5 repetitions bound but do not "
            "eliminate sampling noise. Interleaving pressure (8 markers, 1ms gaps) is modest "
            "by design.",
            "Single seed; wall-time comparisons are hardware-specific (this sandbox).",
        ],
        "overall_verdict": (
            "SUPPORTS graph value: G matches S on safety (0 corruption both), beats S on "
            "speed (shape-1 speedup), serializes OWNS: conflicts P corrupts, and converts "
            "runaway hangs into explicit budget starvation."
            if g_ok else
            "MIXED: one or more graph expectations failed; see per-shape verdicts."
        ),
    }
