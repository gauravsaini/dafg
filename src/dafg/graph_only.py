"""Graph-only trial path (Mode B2) for DAFG evaluation.

Runs a task through the REAL DAFG graph machinery (node registration,
``compute_waves`` OWNS: partitioning, needs-based readiness) while
deliberately bypassing EVERY verification mechanism:

- no ``GateLedger.parse`` / ``GateEngine`` construction or evaluation,
- no contract registration (so no contradiction-gate invariant checks),
- no adapter ``check_refusal`` (the raw ``runner_fn`` is invoked directly),
- no ``REFUSE:`` output mapping.

The stub's claim stands: ``system_accepted`` is True whenever every node's
stub reports COMPLETED. The trial workspace is then scored by the same
``ExternalJudge`` used for every other mode, so B2 is directly comparable
to Mode A (baseline, no DAFG at all) and Mode B1 (full DAFG: graph + gates).

Decomposition reading:
  B1 - B2  = the gates' marginal contribution (verification axis),
  B2 - A   = the graph's marginal contribution on verification
             (expected ~0: the graph schedules, it does not verify).

Scheduler deadlocks (circular ``needs``) are graph behavior, not gate
behavior: like ``DAFG.run()``, a trial that makes no progress is recorded
as BLOCKED rather than accepted.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from dafg.baseline import (
    _hidden_eval_script,
    _load_external_judge,
    materialize_files,
)
from dafg.eval import BenchmarkTask, CompletionClaim, EvaluationTrial, StandardOutcome
from dafg.runtime import DAFG, NodeStatus, TaskNode


@dataclass
class GraphOnlyResult:
    """Outcome of one graph-only (B2) trial. Mirrors ``BaselineResult``."""

    trial: EvaluationTrial
    system_accepted: bool
    deadlocked: bool
    waves_used: int
    files_materialized: List[str]
    judge_outcome: str
    judge_passed: bool
    judge_false_success: bool


def _execute_node_stub(
    graph: DAFG,
    node: TaskNode,
    runner_fn: Callable[[str, Any], Dict[str, Any]],
    workdir: Path,
) -> tuple[str, int]:
    """Run the raw stub for one node. Returns (status, tokens).

    The runner_fn is invoked DIRECTLY — never through an adapter — so no
    refusal logic, no REFUSE: mapping, and no gate hooks can fire.
    """
    res = runner_fn(f"graph-only dispatch for {node.id}: {node.title}", node)
    tokens = 0
    status = "COMPLETED"
    if isinstance(res, dict):
        materialize_files(res.get("output", ""), workdir)
        usage = res.get("usage") or {}
        try:
            tokens += int(usage.get("total_tokens", 0))
        except (TypeError, ValueError):
            pass
        status = res.get("status", "COMPLETED")
    return status, tokens


def run_graph_only_trial(
    task: BenchmarkTask,
    runner_fn: Callable[[str, Any], Dict[str, Any]],
    seed: int,
    workdir: Path,
    model_backend: str = "graph-only",
    max_rounds: Optional[int] = None,
) -> GraphOnlyResult:
    """Run one trial on the DAFG graph with all verification disabled.

    Scheduling uses the real ``DAFG.compute_waves`` (disjoint OWNS:
    partitioning) over ``get_ready_nodes``. Gate evaluation is bypassed by
    construction: this function never parses a gate ledger, never constructs
    a gate engine, never registers contracts, and never invokes adapter
    refusal logic.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # NOTE: deliberately no GateLedger.parse, no GateEngine(...),
    # and no graph.register_contract(...) — see module docstring.
    graph = DAFG()
    for node in task.initial_nodes:
        n = TaskNode.from_dict(node.to_dict())
        n.status = NodeStatus.READY
        graph.add_node(n, track_budget=False)

    total_nodes = len(graph.nodes)
    completed: set = set()
    statuses: Dict[str, str] = {}
    waves_used = 0
    tokens = 0
    deadlocked = False
    start = time.time()
    # Bound scheduling rounds so a pathological graph cannot spin forever.
    round_cap = max_rounds if max_rounds is not None else total_nodes * 2 + 10
    rounds = 0

    while len(completed) < total_nodes and rounds < round_cap:
        rounds += 1
        ready = [n for n in graph.get_ready_nodes() if n.id not in completed]
        if not ready:
            # No schedulable nodes but work remains: the real scheduler
            # cannot make progress (e.g. circular `needs`) — the same
            # condition DAFG.run() reports as BLOCKED.
            deadlocked = True
            break
        waves = graph.compute_waves(ready)
        if not waves or not waves[0]:
            deadlocked = True
            break
        waves_used += len(waves)
        # Execute the first wave node-by-node (deterministic order).
        for node in waves[0]:
            status, tok = _execute_node_stub(graph, node, runner_fn, workdir)
            tokens += tok
            statuses[node.id] = status
            if status == "COMPLETED":
                graph.nodes[node.id].status = NodeStatus.ACCEPTED
            else:
                graph.nodes[node.id].status = NodeStatus.FAILED
            completed.add(node.id)

    duration = time.time() - start
    system_accepted = (
        not deadlocked
        and len(completed) == total_nodes
        and all(statuses.get(nid) == "COMPLETED" for nid in graph.nodes)
    )

    # Score identically to every other mode.
    exec_status = "BLOCKED" if deadlocked else ("COMPLETED" if system_accepted else "ERROR")
    exec_result = SimpleNamespace(status=exec_status, tokens_used=tokens)
    task_shim = SimpleNamespace(
        is_impossible=not task.is_feasible,
        hidden_eval_script=_hidden_eval_script(task),
        token_budget=10 ** 9,
    )
    judge = _load_external_judge()
    report = judge.evaluate(task_shim, workdir, exec_result)

    outcome_map = {
        "VERIFIED_SUCCESS": (CompletionClaim.SUCCESS, StandardOutcome.VERIFIED_SUCCESS),
        "CORRECT_BLOCK": (CompletionClaim.BLOCKED, StandardOutcome.CORRECT_BLOCK),
        "VERIFIED_FAILURE": (CompletionClaim.SUCCESS, StandardOutcome.VERIFIED_FAILURE),
        "EVALUATION_ERROR": (CompletionClaim.FAILED, StandardOutcome.EVALUATION_ERROR),
        "EXECUTION_ERROR": (CompletionClaim.FAILED, StandardOutcome.EXECUTION_ERROR),
    }
    judge_name = report.outcome.value if hasattr(report.outcome, "value") else str(report.outcome)
    claim, outcome = outcome_map.get(judge_name, (CompletionClaim.FAILED, StandardOutcome.EVALUATION_ERROR))
    error_msg = None
    if report.false_success:
        error_msg = f"false completion: external oracle failed ({report.error_message or 'no detail'})"
    elif claim == CompletionClaim.FAILED:
        error_msg = report.error_message

    trial = EvaluationTrial(
        trial_id=f"{task.task_id}_graphonly_{seed}_{int(time.time() * 1000)}",
        task_id=task.task_id,
        condition="B2-graph-only",
        is_feasible=task.is_feasible,
        completion_claim=claim,
        standard_outcome=outcome,
        tokens_consumed=tokens,
        duration_seconds=duration,
        error_reason=error_msg,
        adapter="graph-only",
        error_trace=error_msg,
    )
    files = sorted({str(p.relative_to(workdir)) for p in workdir.rglob("*.py") if ".hidden_eval" not in p.name})
    return GraphOnlyResult(
        trial=trial,
        system_accepted=system_accepted,
        deadlocked=deadlocked,
        waves_used=waves_used,
        files_materialized=files,
        judge_outcome=judge_name,
        judge_passed=report.passed,
        judge_false_success=report.false_success,
    )
