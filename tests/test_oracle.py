"""Tests for ground-truth oracle execution and discrepancy auditing."""

import os
from pathlib import Path
import pytest

from dafg import GroundTruthResult, audit_discrepancy, run_oracle


def _make_executable_script(path: Path, content: str) -> str:
    path.write_text(content)
    os.chmod(path, 0o755)
    return str(path)


def test_ground_truth_result_dataclass():
    """Verify GroundTruthResult dataclass fields, defaults, and conversion methods."""
    gt = GroundTruthResult(
        total=10,
        passed=8,
        failed=2,
        pass_rate=80.0,
        duration_s=1.23,
    )
    assert gt.total == 10
    assert gt.passed == 8
    assert gt.failed == 2
    assert gt.pass_rate == 80.0
    assert gt.duration_s == 1.23

    d = gt.to_dict()
    assert d == {
        "total": 10,
        "passed": 8,
        "failed": 2,
        "pass_rate": 80.0,
        "duration_s": 1.23,
    }

    reconstructed = GroundTruthResult.from_dict(d)
    assert reconstructed == gt

    # Defaults test
    empty_gt = GroundTruthResult()
    assert empty_gt.total == 0
    assert empty_gt.passed == 0
    assert empty_gt.failed == 0
    assert empty_gt.pass_rate == 0.0
    assert empty_gt.duration_s == 0.0


def test_run_oracle_pass(tmp_path: Path):
    """Verify run_oracle with a shell script returning a passing JSON payload."""
    script_path = tmp_path / "oracle_pass.sh"
    _make_executable_script(
        script_path,
        '#!/usr/bin/env bash\n'
        'echo \'{"total": 5, "passed": 5, "failed": 0, "pass_rate": 100.0}\'\n'
        'exit 0\n',
    )

    res = run_oracle(f"bash {script_path}", workdir=tmp_path)
    assert res["success"] is True
    assert res["status"] == "pass"
    assert res["total"] == 5
    assert res["passed"] == 5
    assert res["failed"] == 0
    assert res["pass_rate"] == 100.0
    assert res["returncode"] == 0
    assert res["duration_s"] >= 0.0
    # Attribute access
    assert res.success is True
    assert res.pass_rate == 100.0

    # Also test passing as list
    res_list = run_oracle(["bash", str(script_path)], workdir=tmp_path)
    assert res_list["success"] is True
    assert res_list["passed"] == 5


def test_run_oracle_fail(tmp_path: Path):
    """Verify run_oracle with a shell script returning failure JSON and exit code 1."""
    script_path = tmp_path / "oracle_fail.sh"
    _make_executable_script(
        script_path,
        '#!/usr/bin/env bash\n'
        'echo \'{"total": 10, "passed": 4, "failed": 6, "pass_rate": 40.0}\'\n'
        'exit 1\n',
    )

    res = run_oracle(["bash", str(script_path)], workdir=tmp_path)
    assert res["success"] is False
    assert res["status"] == "fail"
    assert res["total"] == 10
    assert res["passed"] == 4
    assert res["failed"] == 6
    assert res["pass_rate"] == 40.0
    assert res["returncode"] == 1
    assert res.success is False


def test_run_oracle_malformed(tmp_path: Path):
    """Verify run_oracle with a shell script returning non-JSON malformed output."""
    script_path = tmp_path / "oracle_malformed.sh"
    _make_executable_script(
        script_path,
        '#!/usr/bin/env bash\n'
        'echo "CRITICAL: memory error [broken output not json"\n'
        'exit 0\n',
    )

    res = run_oracle(["bash", str(script_path)], workdir=tmp_path)
    assert res["success"] is False
    assert res["status"] == "malformed"
    assert res["passed"] == 0
    assert res["failed"] == 1
    assert res["pass_rate"] == 0.0
    assert "error" in res
    assert "Malformed" in res["error"] or "malformed" in res["error"].lower()


def test_run_oracle_timeout(tmp_path: Path):
    """Verify run_oracle handles execution timeout gracefully."""
    script_path = tmp_path / "oracle_timeout.sh"
    _make_executable_script(
        script_path,
        '#!/usr/bin/env bash\n'
        'sleep 2\n'
        'echo \'{"total": 1, "passed": 1, "failed": 0}\'\n',
    )

    res = run_oracle(["bash", str(script_path)], workdir=tmp_path, timeout=0.1)
    assert res["success"] is False
    assert res["status"] == "timeout"
    assert res["returncode"] == -1
    assert res["passed"] == 0
    assert res["failed"] == 1
    assert "Timeout expired" in res["error"]


def test_audit_discrepancy_math():
    """Verify discrepancy math, threshold comparisons, and flagging."""
    # 1. Exact match (0 discrepancy)
    r1 = audit_discrepancy(internal_score=85.0, gt_dict={"pass_rate": 85.0}, threshold=10.0)
    assert r1["discrepancy"] == 0.0
    assert r1["flag"] is False
    assert r1["flagged"] is False

    # 2. Within threshold (< 10.0)
    r2 = audit_discrepancy(internal_score=92.0, gt_dict={"pass_rate": 85.0}, threshold=10.0)
    assert r2["discrepancy"] == 7.0
    assert r2["flag"] is False

    # 3. Exactly at threshold (not exceeding -> not flagged)
    r3 = audit_discrepancy(internal_score=95.0, gt_dict={"pass_rate": 85.0}, threshold=10.0)
    assert r3["discrepancy"] == 10.0
    assert r3["flag"] is False

    # 4. Exceeding threshold (> 10.0 -> flagged)
    r4 = audit_discrepancy(internal_score=98.0, gt_dict={"pass_rate": 85.0}, threshold=10.0)
    assert r4["discrepancy"] == 13.0
    assert r4["flag"] is True
    assert r4["flagged"] is True

    # 5. Negative difference (internal lower than ground truth)
    r5 = audit_discrepancy(internal_score=60.0, gt_dict={"pass_rate": 85.0}, threshold=10.0)
    assert r5["discrepancy"] == 25.0
    assert r5["flag"] is True

    # 6. Custom threshold
    r6 = audit_discrepancy(internal_score=83.0, gt_dict={"pass_rate": 80.0}, threshold=2.0)
    assert r6["discrepancy"] == 3.0
    assert r6["flag"] is True

    # 7. With GroundTruthResult dataclass object
    gt_obj = GroundTruthResult(total=10, passed=6, failed=4, pass_rate=60.0, duration_s=0.5)
    r7 = audit_discrepancy(internal_score=90.0, gt_dict=gt_obj, threshold=10.0)
    assert r7["discrepancy"] == 30.0
    assert r7["flag"] is True

    # 8. Fallback to passed / total when pass_rate not explicitly provided
    r8 = audit_discrepancy(internal_score=80.0, gt_dict={"passed": 8, "total": 10}, threshold=5.0)
    assert r8["gt_score"] == 80.0
    assert r8["discrepancy"] == 0.0
    assert r8["flag"] is False

    # 9. GroundTruthResult fraction scale 1.0 vs internal 100.0 -> discrepancy 0
    gt_frac_1 = GroundTruthResult(total=10, passed=10, failed=0, pass_rate=1.0, duration_s=0.5)
    r9 = audit_discrepancy(internal_score=100.0, gt_dict=gt_frac_1, threshold=10.0)
    assert r9["gt_score"] == 100.0
    assert r9["discrepancy"] == 0.0
    assert r9["flag"] is False

    # 10. GroundTruthResult fraction scale 0.0 vs internal 0.0 -> discrepancy 0
    gt_frac_0 = GroundTruthResult(total=10, passed=0, failed=10, pass_rate=0.0, duration_s=0.5)
    r10 = audit_discrepancy(internal_score=0.0, gt_dict=gt_frac_0, threshold=10.0)
    assert r10["gt_score"] == 0.0
    assert r10["discrepancy"] == 0.0
    assert r10["flag"] is False

    # 11. GroundTruthResult(pass_rate=1.0) with defaults vs internal 100.0 -> discrepancy 0
    gt_simple_1 = GroundTruthResult(pass_rate=1.0)
    r11 = audit_discrepancy(internal_score=100.0, gt_dict=gt_simple_1, threshold=10.0)
    assert r11["gt_score"] == 100.0
    assert r11["discrepancy"] == 0.0
    assert r11["flag"] is False

    # 12. GroundTruthResult(pass_rate=0.0) with defaults vs internal 0.0 -> discrepancy 0
    gt_simple_0 = GroundTruthResult(pass_rate=0.0)
    r12 = audit_discrepancy(internal_score=0.0, gt_dict=gt_simple_0, threshold=10.0)
    assert r12["gt_score"] == 0.0
    assert r12["discrepancy"] == 0.0
    assert r12["flag"] is False

    # 13. Dict with fraction pass_rate 1.0 and total context vs internal 100.0 -> discrepancy 0
    r13 = audit_discrepancy(internal_score=100.0, gt_dict={"pass_rate": 1.0, "total": 10}, threshold=10.0)
    assert r13["gt_score"] == 100.0
    assert r13["discrepancy"] == 0.0
    assert r13["flag"] is False

    # 14. Dict with fraction pass_rate 0.0 and total context vs internal 0.0 -> discrepancy 0
    r14 = audit_discrepancy(internal_score=0.0, gt_dict={"pass_rate": 0.0, "total": 10}, threshold=10.0)
    assert r14["gt_score"] == 0.0
    assert r14["discrepancy"] == 0.0
    assert r14["flag"] is False
