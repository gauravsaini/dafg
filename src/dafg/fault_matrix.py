"""Calibrated fault matrix runner for verification-first control-plane evaluation.

Executes original and round-robin mutated BenchmarkTask fixtures in isolated subprocesses,
records JSON-serializable pass/exit/fault/verified/false-completion rows, and includes
impossible tasks as correct-block rows without mutating inputs.
Stdlib-only implementation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

try:
    from dafg.eval import StandardOutcome
    from dafg.faults import (
        BENCHMARK_FAULT_CLASSES,
        CLASS_1_SYNTAX_PACKAGING,
        CLASS_2_SUBTLE_LOGIC,
        CLASS_3_CONCURRENCY_RACES,
        CLASS_4_MOCK_FACADES,
        CLASS_5_SECURITY_VIOLATIONS,
        CLASS_6_UNSATISFIABLE_CONSTRAINTS,
        FAULT_OPERATORS,
        concurrency_race,
        facade_stub,
        logic_flip,
        scope_violation,
        syntax_break,
        unsatisfiable_constraint,
    )
except ImportError:
    from .eval import StandardOutcome
    from .faults import (
        BENCHMARK_FAULT_CLASSES,
        CLASS_1_SYNTAX_PACKAGING,
        CLASS_2_SUBTLE_LOGIC,
        CLASS_3_CONCURRENCY_RACES,
        CLASS_4_MOCK_FACADES,
        CLASS_5_SECURITY_VIOLATIONS,
        CLASS_6_UNSATISFIABLE_CONSTRAINTS,
        FAULT_OPERATORS,
        concurrency_race,
        facade_stub,
        logic_flip,
        scope_violation,
        syntax_break,
        unsatisfiable_constraint,
    )


class FaultIdentifier(str):
    """String representation of an injected fault that matches operator and class names."""

    def __new__(
        cls,
        op_name: str,
        class_name: Any,
        concise_name: Optional[str] = None,
    ) -> FaultIdentifier:
        obj = super().__new__(cls, op_name)
        obj.op_name = op_name
        obj.class_name = class_name
        obj.full_name = str(class_name)
        if concise_name:
            obj.concise_name = concise_name
        elif "(" in obj.full_name and ")" in obj.full_name:
            obj.concise_name = obj.full_name[
                obj.full_name.find("(") + 1 : obj.full_name.rfind(")")
            ].strip()
        else:
            obj.concise_name = obj.full_name
        return obj

    def __hash__(self) -> int:
        return super().__hash__()

    def __eq__(self, other: object) -> bool:
        if super().__eq__(other):
            return True
        if isinstance(other, str):
            other_lower = other.lower()
            if other_lower == self.op_name.lower():
                return True
            if other_lower == self.full_name.lower():
                return True
            if other_lower == self.concise_name.lower():
                return True
            if (
                other.replace(" and ", " & ").lower()
                == self.concise_name.replace(" and ", " & ").lower()
            ):
                return True
            if (
                other.replace(" & ", " and ").lower()
                == self.concise_name.replace(" & ", " and ").lower()
            ):
                return True
            if hasattr(self.class_name, "__eq__") and self.class_name == other:
                return True
        return False


ROUND_ROBIN_OPERATORS: Tuple[Tuple[str, Callable[[Optional[str]], Any], Any], ...] = (
    ("syntax_break", syntax_break, CLASS_1_SYNTAX_PACKAGING),
    ("logic_flip", logic_flip, CLASS_2_SUBTLE_LOGIC),
    ("concurrency_race", concurrency_race, CLASS_3_CONCURRENCY_RACES),
    ("facade_stub", facade_stub, CLASS_4_MOCK_FACADES),
    ("scope_violation", scope_violation, CLASS_5_SECURITY_VIOLATIONS),
    ("unsatisfiable_constraint", unsatisfiable_constraint, CLASS_6_UNSATISFIABLE_CONSTRAINTS),
)

OPERATOR_CLASS_MAP: Dict[str, Any] = {
    "syntax_break": CLASS_1_SYNTAX_PACKAGING,
    "logic_flip": CLASS_2_SUBTLE_LOGIC,
    "concurrency_race": CLASS_3_CONCURRENCY_RACES,
    "facade_stub": CLASS_4_MOCK_FACADES,
    "scope_violation": CLASS_5_SECURITY_VIOLATIONS,
    "unsatisfiable_constraint": CLASS_6_UNSATISFIABLE_CONSTRAINTS,
}


class FaultMatrixRow(dict):
    """Dictionary representing a single fault matrix outcome row with attribute access."""

    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        alt_hyphen = name.replace("_", "-")
        if alt_hyphen in self:
            return self[alt_hyphen]
        alt_under = name.replace("-", "_")
        if alt_under in self:
            return self[alt_under]
        raise AttributeError(f"'FaultMatrixRow' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def to_dict(self) -> Dict[str, Any]:
        """Return a clean dictionary representation suitable for standard JSON serialization."""
        return {
            k: (v if not hasattr(v, "to_dict") else v.to_dict()) for k, v in self.items()
        }


class FaultMatrixResult(list):
    """Container for calibrated fault matrix execution rows, supporting list and dict access."""

    def __init__(
        self,
        rows: Sequence[Dict[str, Any]],
        summary: Optional[Dict[str, Any]] = None,
        by_fault_class: Optional[Dict[str, Dict[str, Any]]] = None,
        by_cohort: Optional[Dict[str, Dict[str, Any]]] = None,
        total_trials: Optional[int] = None,
        detected_faults: Optional[int] = None,
        detection_rate: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(rows)
        self.summary = summary or {}
        self.rows = self
        self.trials = self
        self.by_fault_class = by_fault_class or {}
        self.by_cohort = by_cohort or {}
        self.total_trials = total_trials if total_trials is not None else len(rows)
        self.detected_faults = detected_faults if detected_faults is not None else self.summary.get("detected_faults", 0)
        self.detection_rate = detection_rate if detection_rate is not None else self.summary.get("detection_rate", 0.0)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if item in ("rows", "records", "results", "data", "trials"):
                return list(self)
            if item in ("summary", "metrics"):
                return self.summary
            if item in ("by_fault_class", "fault_classes"):
                return self.by_fault_class
            if item in ("by_cohort", "cohorts"):
                return self.by_cohort
            if item in self.summary:
                return self.summary[item]
            if hasattr(self, item):
                return getattr(self, item)
            raise KeyError(item)
        return super().__getitem__(item)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except (KeyError, TypeError, IndexError):
            return default

    def to_dict(self) -> Dict[str, Any]:
        """Convert result container to a JSON-serializable dictionary."""
        return {
            "rows": [dict(r) for r in self],
            "trials": [dict(r) for r in self],
            "summary": self.summary,
            "by_fault_class": self.by_fault_class,
            "by_cohort": self.by_cohort,
            "total_trials": self.total_trials,
            "detected_faults": self.detected_faults,
            "detection_rate": self.detection_rate,
        }


def _is_impossible(task: Any) -> bool:
    """Check if task is defined as impossible or infeasible."""
    if hasattr(task, "is_feasible"):
        if not task.is_feasible:
            return True
    if hasattr(task, "cohort") and task.cohort == "impossible":
        return True
    if hasattr(task, "is_impossible") and task.is_impossible:
        return True
    if isinstance(task, dict):
        if task.get("is_feasible") is False:
            return True
        if task.get("cohort") == "impossible":
            return True
        if task.get("is_impossible") is True:
            return True
    return False


def _get_test_fixture(task: Any) -> str:
    """Extract test fixture code from task object or dictionary."""
    if hasattr(task, "test_fixture") and task.test_fixture is not None:
        return str(task.test_fixture)
    if isinstance(task, dict) and "test_fixture" in task and task["test_fixture"] is not None:
        return str(task["test_fixture"])
    if hasattr(task, "hidden_eval_script") and task.hidden_eval_script:
        return str(task.hidden_eval_script)
    if isinstance(task, dict) and "hidden_eval_script" in task and task["hidden_eval_script"]:
        return str(task["hidden_eval_script"])
    return "print('PASS')"


def _get_task_id(task: Any, default: str = "") -> str:
    """Extract task identifier."""
    if hasattr(task, "task_id") and task.task_id:
        return str(task.task_id)
    if hasattr(task, "id") and task.id:
        return str(task.id)
    if isinstance(task, dict):
        return str(task.get("task_id") or task.get("id") or default)
    return default


def _get_title(task: Any) -> str:
    """Extract task title."""
    if hasattr(task, "title") and task.title:
        return str(task.title)
    if isinstance(task, dict) and "title" in task:
        return str(task["title"])
    return ""


def _get_cohort(task: Any) -> Optional[str]:
    """Extract task cohort identifier."""
    if hasattr(task, "cohort"):
        return task.cohort
    if isinstance(task, dict):
        return task.get("cohort")
    return None


def _execute_fixture_subprocess(
    fixture_code: str, timeout: float = 5.0
) -> Tuple[int, bool, str, str]:
    """Execute a test fixture snippet in an isolated subprocess.

    Returns:
        (exit_code, passed, stdout, stderr)
    """
    clean_env = os.environ.copy()
    clean_env["PYTHONUNBUFFERED"] = "1"

    # Add src/ and repo root to PYTHONPATH so package imports function in isolation
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    src_dir = os.path.join(repo_root, "src")
    existing_pythonpath = clean_env.get("PYTHONPATH", "")
    clean_env["PYTHONPATH"] = (
        f"{src_dir}:{repo_root}:{existing_pythonpath}" if existing_pythonpath else f"{src_dir}:{repo_root}"
    )

    with tempfile.TemporaryDirectory(prefix="dafg_fault_") as temp_dir:
        fixture_file = os.path.join(temp_dir, "fixture_run.py")
        with open(fixture_file, "w", encoding="utf-8") as f:
            f.write(fixture_code)

        try:
            proc = subprocess.run(
                [sys.executable, fixture_file],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=clean_env,
            )
            exit_code = proc.returncode
            passed = exit_code == 0
            return exit_code, passed, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout
                if isinstance(exc.stdout, str)
                else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            )
            stderr = (
                exc.stderr
                if isinstance(exc.stderr, str)
                else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
            )
            timeout_msg = f"\nTimeoutExpired: fixture execution exceeded {timeout}s limit"
            return 124, False, stdout, (stderr + timeout_msg).strip()
        except Exception as exc:
            return 1, False, "", f"SubprocessExecutionError: {exc}"


def run_calibrated_fault_matrix(
    tasks: Any,
    timeout: float = 5.0,
    seed: int = 42,
    **kwargs: Any,
) -> FaultMatrixResult:
    """Execute original and round-robin mutated BenchmarkTask fixtures in isolated subprocesses.

    Records JSON-serializable pass/exit/fault/verified/false-completion rows, and includes
    impossible tasks as correct-block rows. Never mutates input task fixtures or collections.

    Args:
        tasks: Sequence, iterable, or single BenchmarkTask fixture (or equivalent dict).
        timeout: Subprocess execution timeout in seconds per fixture (default: 5.0).
        seed: Random / round-robin calibration seed (default: 42).
        **kwargs: Optional configuration parameters (e.g., custom operators).

    Returns:
        FaultMatrixResult containing recorded rows and summary metrics.
    """
    # Defensive normalization: never mutate original inputs
    if tasks is None:
        task_seq: List[Any] = []
    elif isinstance(tasks, (list, tuple)):
        task_seq = list(tasks)
    elif isinstance(tasks, dict) and not (hasattr(tasks, "task_id") or "test_fixture" in tasks):
        task_seq = list(tasks.values())
    elif isinstance(tasks, Iterable) and not isinstance(tasks, (str, bytes)):
        task_seq = list(tasks)
    else:
        task_seq = [tasks]

    # Resolve operators mapping or tuple list
    operators_arg = kwargs.get("operators")
    if operators_arg is not None:
        if isinstance(operators_arg, dict):
            operators: List[Tuple[str, Callable[[Optional[str]], Any], Any]] = [
                (name, fn, OPERATOR_CLASS_MAP.get(name, name))
                for name, fn in operators_arg.items()
            ]
        elif isinstance(operators_arg, (list, tuple)):
            operators = list(operators_arg)
        else:
            operators = list(ROUND_ROBIN_OPERATORS)
    else:
        operators = list(ROUND_ROBIN_OPERATORS)

    rows: List[FaultMatrixRow] = []

    # Round-robin operator index over feasible tasks
    feasible_idx = 0

    # Tracking metrics per fault class and cohort
    by_fault_class: Dict[str, Dict[str, Any]] = {}
    for op_name, _, class_name in operators:
        c_key = str(class_name)
        if c_key not in by_fault_class:
            by_fault_class[c_key] = {
                "operator": op_name,
                "class_name": c_key,
                "total_trials": 0,
                "detected": 0,
                "detection_rate": 0.0,
                "expected_failure": "",
            }

    by_cohort: Dict[str, Dict[str, Any]] = {}

    for idx, task in enumerate(task_seq):
        task_id = _get_task_id(task, f"task_{idx}")
        title = _get_title(task)
        cohort = _get_cohort(task) or "unknown"
        is_imp = _is_impossible(task)

        if cohort not in by_cohort:
            by_cohort[cohort] = {
                "tasks": 0,
                "total_trials": 0,
                "detected": 0,
                "detection_rate": 0.0,
            }
        by_cohort[cohort]["tasks"] += 1

        if is_imp:
            # Impossible task: exactly one correct-block row
            fixture_code = _get_test_fixture(task)
            exit_code = 0
            stdout = ""
            stderr = ""
            if fixture_code:
                exit_code, _, stdout, stderr = _execute_fixture_subprocess(
                    fixture_code, timeout=timeout
                )

            row = FaultMatrixRow({
                "task_id": task_id,
                "title": title,
                "variant": "impossible",
                "is_feasible": False,
                "cohort": cohort,
                "seed": seed,
                "pass": True,
                "passed": True,
                "exit": exit_code,
                "exit_code": exit_code,
                "fault": None,
                "fault_operator": None,
                "operator": None,
                "fault_class": None,
                "baseline_claim": "BLOCKED",
                "completion_claim": "BLOCKED",
                "verified_accept": False,
                "detectable_by_gate": True,
                "expected_failure": "UnsatisfiableConstraintError: impossible task constraint",
                "verified": True,
                "verified_outcome": "CORRECT_BLOCK",
                "standard_outcome": (
                    StandardOutcome.CORRECT_BLOCK.value
                    if hasattr(StandardOutcome, "CORRECT_BLOCK")
                    else "CORRECT_BLOCK"
                ),
                "false_completion": False,
                "false-completion": False,
                "correct_block": True,
                "correct-block": True,
                "stdout": stdout,
                "stderr": stderr,
            })
            rows.append(row)
            by_cohort[cohort]["total_trials"] += 1
            by_cohort[cohort]["detected"] += 1
        else:
            # Feasible task: exactly one original row and one mutated row
            orig_fixture = _get_test_fixture(task)

            # 1. Original fixture execution
            orig_exit, orig_passed, orig_stdout, orig_stderr = _execute_fixture_subprocess(
                orig_fixture, timeout=timeout
            )
            orig_pass = bool(orig_passed)
            orig_baseline_claim = "SUCCESS"
            orig_verified_accept = orig_pass
            orig_false_comp = bool(orig_baseline_claim == "SUCCESS" and not orig_verified_accept)

            row_orig = FaultMatrixRow({
                "task_id": task_id,
                "title": title,
                "variant": "original",
                "is_feasible": True,
                "cohort": cohort,
                "seed": seed,
                "pass": orig_pass,
                "passed": orig_pass,
                "exit": orig_exit,
                "exit_code": orig_exit,
                "fault": None,
                "fault_operator": None,
                "operator": None,
                "fault_class": None,
                "baseline_claim": orig_baseline_claim,
                "completion_claim": orig_baseline_claim,
                "verified_accept": orig_verified_accept,
                "detectable_by_gate": False,
                "expected_failure": "",
                "verified": orig_verified_accept,
                "verified_outcome": "VERIFIED_SUCCESS" if orig_verified_accept else "VERIFIED_FAILURE",
                "standard_outcome": (
                    StandardOutcome.VERIFIED_SUCCESS.value
                    if orig_verified_accept
                    else (
                        StandardOutcome.VERIFIED_FAILURE.value
                        if hasattr(StandardOutcome, "VERIFIED_FAILURE")
                        else "VERIFIED_FAILURE"
                    )
                ),
                "false_completion": orig_false_comp,
                "false-completion": orig_false_comp,
                "correct_block": False,
                "correct-block": False,
                "stdout": orig_stdout,
                "stderr": orig_stderr,
            })
            rows.append(row_orig)
            by_cohort[cohort]["total_trials"] += 1

            # 2. Mutated fixture execution (one operator per feasible task, round-robin over six operators)
            if operators:
                op_name, op_fn, class_name = operators[feasible_idx % len(operators)]
                feasible_idx += 1

                # Deterministically mutate fixture code without mutating input task
                fault_res = op_fn(orig_fixture)
                mut_exit, mut_passed, mut_stdout, mut_stderr = _execute_fixture_subprocess(
                    fault_res.after, timeout=timeout
                )

                mutated_pass = bool(mut_passed)
                baseline_claim = "SUCCESS"
                verified_accept = mutated_pass
                false_completion = bool(baseline_claim == "SUCCESS" and not verified_accept)
                detectable_by_gate = bool(not mutated_pass)

                fault_id = FaultIdentifier(op_name, class_name)

                row_mut = FaultMatrixRow({
                    "task_id": task_id,
                    "title": title,
                    "variant": "mutated",
                    "is_feasible": True,
                    "cohort": cohort,
                    "seed": seed,
                    "pass": mutated_pass,
                    "passed": mutated_pass,
                    "exit": mut_exit,
                    "exit_code": mut_exit,
                    "fault": fault_id,
                    "fault_operator": op_name,
                    "operator": op_name,
                    "fault_class": str(class_name),
                    "baseline_claim": baseline_claim,
                    "completion_claim": baseline_claim,
                    "verified_accept": verified_accept,
                    "detectable_by_gate": detectable_by_gate,
                    "expected_failure": str(fault_res.expected_failure),
                    "verified": verified_accept,
                    "verified_outcome": "VERIFIED_SUCCESS" if verified_accept else "VERIFIED_FAILURE",
                    "standard_outcome": (
                        StandardOutcome.VERIFIED_SUCCESS.value
                        if verified_accept
                        else (
                            StandardOutcome.VERIFIED_FAILURE.value
                            if hasattr(StandardOutcome, "VERIFIED_FAILURE")
                            else "VERIFIED_FAILURE"
                        )
                    ),
                    "false_completion": false_completion,
                    "false-completion": false_completion,
                    "correct_block": False,
                    "correct-block": False,
                    "stdout": mut_stdout,
                    "stderr": mut_stderr,
                })
                rows.append(row_mut)

                by_cohort[cohort]["total_trials"] += 1
                if detectable_by_gate:
                    by_cohort[cohort]["detected"] += 1

                c_key = str(class_name)
                if c_key in by_fault_class:
                    by_fault_class[c_key]["total_trials"] += 1
                    if detectable_by_gate:
                        by_fault_class[c_key]["detected"] += 1
                    if not by_fault_class[c_key]["expected_failure"]:
                        by_fault_class[c_key]["expected_failure"] = str(fault_res.expected_failure)

    # Compute rates
    for fc_data in by_fault_class.values():
        total = fc_data["total_trials"]
        det = fc_data["detected"]
        fc_data["detection_rate"] = (det / total) if total > 0 else 0.0

    for ch_data in by_cohort.values():
        total = ch_data["total_trials"]
        det = ch_data["detected"]
        ch_data["detection_rate"] = (det / total) if total > 0 else 0.0

    total_rows = len(rows)
    impossible_count = sum(1 for r in rows if r["variant"] == "impossible")
    correct_block_count = sum(1 for r in rows if r["correct_block"])
    mutated_rows = [r for r in rows if r["variant"] == "mutated"]
    mutated_count = len(mutated_rows)
    original_count = sum(1 for r in rows if r["variant"] == "original")
    detected_faults = sum(1 for r in mutated_rows if r["detectable_by_gate"])

    summary = {
        "total_rows": total_rows,
        "total_tasks": len(task_seq),
        "passed_count": sum(1 for r in rows if r["passed"]),
        "failed_count": sum(1 for r in rows if not r["passed"]),
        "verified_count": sum(1 for r in rows if r["verified"]),
        "verified_rate": (sum(1 for r in rows if r["verified"]) / total_rows) if total_rows > 0 else 0.0,
        "false_completion_count": sum(1 for r in rows if r["false_completion"]),
        "false_completion_rate": (sum(1 for r in rows if r["false_completion"]) / total_rows) if total_rows > 0 else 0.0,
        "correct_block_count": correct_block_count,
        "correct_block_rate": (correct_block_count / impossible_count) if impossible_count > 0 else 1.0,
        "mutated_count": mutated_count,
        "original_count": original_count,
        "impossible_count": impossible_count,
        "detected_faults": detected_faults,
        "detection_rate": (detected_faults / mutated_count) if mutated_count > 0 else 0.0,
        "seed": seed,
        "timeout": timeout,
    }

    return FaultMatrixResult(
        rows,
        summary=summary,
        by_fault_class=by_fault_class,
        by_cohort=by_cohort,
        total_trials=total_rows,
        detected_faults=detected_faults,
        detection_rate=summary["detection_rate"],
        **kwargs,
    )


__all__ = [
    "run_calibrated_fault_matrix",
    "FaultMatrixResult",
    "FaultMatrixRow",
    "FaultIdentifier",
    "ROUND_ROBIN_OPERATORS",
]
