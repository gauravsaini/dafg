#!/usr/bin/env python3
"""Validation gate for the v04 fixture-redesign pilot suite.

Anti-flakiness rule: a flaky fixture is worse than a vacuous one. Every
fixture must PASS against its correct reference implementation and FAIL
against at least two broken variants:
  v1 (syntax):   one owns module replaced with a syntax error
  v2 (semantic): one owns module replaced with a minimal behavioral break

Runs each fixture as the ExternalJudge would: `<python> <fixture>` with
cwd=<workdir>, pass = exit 0 AND 'EVAL_PASSED' on stdout.

Writes eval_results/v04_fixture_validation.json. Any fixture failing the
gate is reported for fix-or-drop (never silently kept).

Usage:
    uv run python scripts/validate_v04_fixtures.py [--out eval_results/v04_fixture_validation.json]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / "benchmarks" / "v04_pilot"
TIMEOUT_S = 15


def run_fixture(fixture_path: Path, workdir: Path):
    """Run a fixture the way ExternalJudge does: copy its content to
    <workdir>/.hidden_eval.py and execute with cwd=workdir.
    Returns (passed, stdout, stderr)."""
    eval_script = workdir / ".hidden_eval.py"
    eval_script.write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(eval_script)],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, "", "TIMEOUT"
    finally:
        if eval_script.exists():
            eval_script.unlink()
    passed = proc.returncode == 0 and "EVAL_PASSED" in proc.stdout
    return passed, proc.stdout[-2000:], proc.stderr[-2000:]


def materialize(task_id: str, workdir: Path, variant: str | None = None):
    """Copy reference tree for task_id into workdir; overlay broken variant."""
    ref = SUITE / "reference" / task_id
    for src in ref.rglob("*"):
        if src.is_file():
            dest = workdir / src.relative_to(ref)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    if variant:
        over = SUITE / "broken" / task_id / variant
        for src in over.rglob("*"):
            if src.is_file():
                dest = workdir / src.relative_to(over)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)


def validate_task(task: dict) -> dict:
    task_id = task["task_id"]
    fixture = SUITE / task["fixture_file"]
    result = {"task_id": task_id, "checks": {}, "gate": "FAIL", "notes": []}

    with tempfile.TemporaryDirectory(prefix=f"v04val_{task_id}_") as td:
        workdir = Path(td)
        # 1. reference must PASS
        materialize(task_id, workdir)
        ok, out, err = run_fixture(fixture, workdir)
        result["checks"]["reference_pass"] = ok
        if not ok:
            result["notes"].append(f"reference FAILED: stdout={out!r} stderr={err!r}")
            return result
        # 2. broken variants must FAIL
        for variant in ("broken_v1", "broken_v2"):
            label = variant.split("_", 1)[1]
            with tempfile.TemporaryDirectory(prefix=f"v04val_{task_id}_{label}_") as td2:
                wd2 = Path(td2)
                materialize(task_id, wd2, variant=variant)
                ok_b, out_b, err_b = run_fixture(fixture, wd2)
                key = f"broken_{label}_fails"
                result["checks"][key] = not ok_b
                if ok_b:
                    result["notes"].append(
                        f"{label} unexpectedly PASSED: stdout={out_b!r}"
                    )
    checks = result["checks"]
    if checks.get("reference_pass") and checks.get("broken_v1_fails") and checks.get("broken_v2_fails"):
        result["gate"] = "PASS"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval_results/v04_fixture_validation.json")
    args = ap.parse_args()

    tasks = json.loads((SUITE / "tasks.json").read_text(encoding="utf-8"))
    t0 = time.time()
    results = [validate_task(t) for t in tasks]
    passed = [r for r in results if r["gate"] == "PASS"]
    report = {
        "suite": "v04-fixture-validation",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "tasks": len(results),
        "gates_passed": len(passed),
        "gates_failed": len(results) - len(passed),
        "wall_s": round(time.time() - t0, 1),
        "results": results,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"V04_VALIDATION: {len(passed)}/{len(results)} fixtures passed the gate")
    for r in results:
        if r["gate"] != "PASS":
            print(f"  FAIL {r['task_id']}: {r['notes']}")
    print(f"wrote {out}")
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
