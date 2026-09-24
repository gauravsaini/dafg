"""Ground-truth oracle execution and discrepancy auditing."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Optional, Sequence, Union


@dataclass
class GroundTruthResult:
    """Structured ground truth execution result."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert result to a plain dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroundTruthResult":
        """Instantiate GroundTruthResult from a dictionary."""
        return cls(
            total=int(data.get("total", 0)),
            passed=int(data.get("passed", 0)),
            failed=int(data.get("failed", 0)),
            pass_rate=float(data.get("pass_rate", 0.0)),
            duration_s=float(data.get("duration_s", 0.0)),
        )


class OracleResult(dict):
    """Dictionary representing oracle execution result with attribute access."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"'OracleResult' object has no attribute {item!r}")

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value

    def to_ground_truth(self) -> GroundTruthResult:
        """Convert to a GroundTruthResult instance."""
        return GroundTruthResult.from_dict(self)


def _extract_json(output: str) -> Optional[dict[str, Any]]:
    """Attempt to parse a JSON dictionary from command output string."""
    text = output.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def run_oracle(
    cmd: Union[str, Sequence[str]],
    workdir: Optional[Union[str, Path]] = None,
    timeout: Optional[float] = None,
) -> OracleResult:
    """Run an oracle verification command and return a pass/fail JSON dictionary."""
    start_time = time.perf_counter()
    shell = isinstance(cmd, str)
    cwd = str(workdir) if workdir is not None else None

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
            shell=shell,
        )
        duration_s = time.perf_counter() - start_time
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        returncode = proc.returncode

        parsed_json = _extract_json(stdout) or _extract_json(stderr)
        if parsed_json is None:
            return OracleResult({
                "args": cmd,
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "total": 0,
                "passed": 0,
                "failed": 1,
                "pass_rate": 0.0,
                "duration_s": round(duration_s, 4),
                "success": False,
                "status": "malformed",
                "error": "Malformed output: failed to parse JSON dictionary",
            })

        # Process parsed JSON metrics
        is_bool_passed = isinstance(parsed_json.get("passed"), bool)
        bool_pass_val = parsed_json.get("passed") if is_bool_passed else None

        if "total" in parsed_json:
            total = int(parsed_json["total"])
            if is_bool_passed:
                passed = total if bool_pass_val else 0
                failed = 0 if bool_pass_val else total
            else:
                passed = int(parsed_json.get("passed", 0))
                failed = int(parsed_json.get("failed", max(0, total - passed)))
        elif "passed" in parsed_json and not is_bool_passed and "failed" in parsed_json:
            passed = int(parsed_json["passed"])
            failed = int(parsed_json["failed"])
            total = passed + failed
        elif is_bool_passed:
            total = 1
            passed = 1 if bool_pass_val else 0
            failed = 0 if bool_pass_val else 1
        elif "passed" in parsed_json and not is_bool_passed:
            passed = int(parsed_json["passed"])
            failed = int(parsed_json.get("failed", 0))
            total = passed + failed
        elif "failed" in parsed_json:
            failed = int(parsed_json["failed"])
            passed = int(parsed_json.get("passed", 0))
            total = passed + failed
        else:
            succ_val = parsed_json.get("success")
            if succ_val is None and "status" in parsed_json:
                succ_val = parsed_json["status"] in ("pass", "passed", "ok", "success")
            if succ_val is not None:
                total = 1
                passed = 1 if succ_val else 0
                failed = 0 if succ_val else 1
            else:
                total = 0
                passed = 0
                failed = 0

        if "pass_rate" in parsed_json:
            pass_rate = float(parsed_json["pass_rate"])
        elif total > 0:
            pass_rate = round((passed / total) * 100.0, 2)
        else:
            pass_rate = 100.0 if (returncode == 0 and failed == 0) else 0.0

        if "success" in parsed_json:
            success = bool(parsed_json["success"])
        elif returncode != 0:
            success = False
        elif failed > 0:
            success = False
        elif is_bool_passed:
            success = bool_pass_val
        elif parsed_json.get("status") in ("fail", "failed", "error"):
            success = False
        else:
            success = (passed > 0 or total == 0) and failed == 0

        result = OracleResult(parsed_json)
        result.update({
            "args": cmd,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": pass_rate,
            "duration_s": round(duration_s, 4),
            "success": success,
            "status": "pass" if success else "fail",
        })
        return result

    except subprocess.TimeoutExpired as exc:
        duration_s = time.perf_counter() - start_time
        out = exc.stdout if isinstance(exc.stdout, str) else (
            exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        )
        err = exc.stderr if isinstance(exc.stderr, str) else (
            exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        )
        return OracleResult({
            "args": cmd,
            "returncode": -1,
            "stdout": out,
            "stderr": err,
            "total": 0,
            "passed": 0,
            "failed": 1,
            "pass_rate": 0.0,
            "duration_s": round(duration_s, 4),
            "success": False,
            "status": "timeout",
            "error": f"Timeout expired after {timeout} seconds",
        })

    except OSError as exc:
        duration_s = time.perf_counter() - start_time
        return OracleResult({
            "args": cmd,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "total": 0,
            "passed": 0,
            "failed": 1,
            "pass_rate": 0.0,
            "duration_s": round(duration_s, 4),
            "success": False,
            "status": "error",
            "error": str(exc),
        })


def audit_discrepancy(
    internal_score: Union[int, float],
    gt_dict: Union[dict[str, Any], GroundTruthResult],
    threshold: float = 10.0,
) -> dict[str, Any]:
    """Audit discrepancy between internal score and ground-truth oracle pass rate."""
    if isinstance(gt_dict, GroundTruthResult):
        gt_score = float(gt_dict.pass_rate)
    elif isinstance(gt_dict, dict):
        if "pass_rate" in gt_dict:
            gt_score = float(gt_dict["pass_rate"])
        elif "score" in gt_dict:
            gt_score = float(gt_dict["score"])
        elif "total" in gt_dict and int(gt_dict["total"]) > 0:
            passed = float(gt_dict.get("passed", 0))
            total = float(gt_dict["total"])
            gt_score = (passed / total) * 100.0
        elif "success" in gt_dict:
            gt_score = 100.0 if gt_dict["success"] else 0.0
        else:
            gt_score = 0.0
    else:
        gt_score = float(gt_dict)

    internal = float(internal_score)
    discrepancy = round(abs(internal - gt_score), 4)
    flag = bool(discrepancy > float(threshold))

    return {
        "discrepancy": discrepancy,
        "flag": flag,
        "flagged": flag,
        "threshold": float(threshold),
        "internal_score": internal,
        "gt_score": gt_score,
    }
