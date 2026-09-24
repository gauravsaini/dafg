"""Tests for programmatic experiment comparison tool."""
from pathlib import Path
import json
import pytest

from dafg.compare import ExperimentComparator, ExperimentRecord


def test_experiment_comparator_on_existing_dirs():
    dirs = [
        Path("experiments/node_service_blackbox"),
        Path("experiments/blackbox_goal_organism"),
        Path("experiments/staged_scaling"),
        Path("experiments/node_organism_eval"),
    ]
    records = [ExperimentComparator.analyze_dir(d) for d in dirs]
    assert len(records) == 4

    # Verify node_service_blackbox
    rec0 = records[0]
    assert rec0.name == "node_service_blackbox"
    assert rec0.gates_total == 6
    assert rec0.gates_met == 6
    assert rec0.stop_hook_decision == "allow"
    assert 0.5 <= rec0.avg_concurrency_ratio <= 0.6
    assert rec0.total_task_deferrals > 0

    # Verify blackbox_goal_organism
    rec1 = records[1]
    assert rec1.name == "blackbox_goal_organism"
    assert rec1.gates_total == 10
    assert rec1.gates_met == 10
    assert any("test_service.js" in x["file"] for x in rec1.overlapping_files)

    # Verify markdown generation
    md = ExperimentComparator.generate_markdown_table(records)
    assert "| `node_service_blackbox` |" in md
    assert "| `blackbox_goal_organism` |" in md
    assert "| `staged_scaling` |" in md
    assert "| `node_organism_eval` |" in md


def test_experiment_comparator_empty_dir(tmp_path):
    rec = ExperimentComparator.analyze_dir(tmp_path)
    assert rec.gates_total == 0
    assert rec.gates_met == 0
    assert rec.stop_hook_decision == "unknown"


def test_experiment_comparator_fresh_non_destructive():
    target_dir = Path("experiments/node_service_blackbox")
    gates_path = target_dir / "GATES.md"
    original_content = gates_path.read_text(encoding="utf-8")
    original_mtime = gates_path.stat().st_mtime

    rec = ExperimentComparator.analyze_dir(target_dir, fresh=True)

    assert rec.provenance == "fresh_execution"
    assert rec.gates_met == 6
    assert rec.gates_total == 6
    assert rec.composite_score >= 80.0
    assert rec.wave_count == 4
    assert rec.domain_deferrals == 3
    assert rec.barrier_deferrals == 3

    # Ensure zero mutation on disk
    assert gates_path.read_text(encoding="utf-8") == original_content
    assert gates_path.stat().st_mtime == original_mtime


def test_experiment_comparator_with_ground_truth(tmp_path):
    eval_dir = tmp_path / "eval_results"
    eval_dir.mkdir(parents=True)

    qdata = {
        "run_id": "run_test_01",
        "score": 94.3,
        "verdict": "IMPERFECT",
    }
    (eval_dir / "quality_report.json").write_text(json.dumps(qdata), encoding="utf-8")

    gt_data = {
        "total": 20,
        "passed": 0,
        "failed": 20,
        "pass_rate": 0.0,
        "duration_seconds": 0.5,
    }
    (eval_dir / "ground_truth.json").write_text(json.dumps(gt_data), encoding="utf-8")

    rec = ExperimentComparator.analyze_dir(tmp_path)
    assert rec.gt_total == 20
    assert rec.gt_passed == 0
    assert rec.gt_failed == 20
    assert rec.gt_pass_rate == 0.0
    assert rec.composite_score == 94.3
    assert rec.discrepancy == 94.3
    assert rec.evidence_status == "VALID"
    assert rec.evidence_issues == []

    # Test markdown generation includes GT columns
    md = ExperimentComparator.generate_markdown_table([rec])
    assert "GT Pass Rate" in md
    assert "Discrepancy" in md
    assert "0.0%" in md
    assert "**+94.3**" in md

    # Test zero discrepancy formatting (e.g. perfect alignment)
    rec_aligned = ExperimentRecord(
        name="aligned_exp",
        dir_path="/tmp/aligned",
        composite_score=100.0,
        gt_total=20,
        gt_passed=20,
        gt_failed=0,
        gt_pass_rate=1.0,
        discrepancy=0.0,
    )
    md_aligned = ExperimentComparator.generate_markdown_table([rec_aligned])
    assert "100.0%" in md_aligned
    assert "| 0.0 |" in md_aligned


def test_experiment_comparator_flags_missing_run_id(tmp_path):
    eval_dir = tmp_path / "eval_results"
    eval_dir.mkdir(parents=True)
    (eval_dir / "quality_report.json").write_text(
        json.dumps({"score": 90.0, "verdict": "VERIFIED_DELIVERY", "timestamp": "now"}),
        encoding="utf-8",
    )

    rec = ExperimentComparator.analyze_dir(tmp_path)

    assert rec.evidence_status == "INCOMPLETE"
    assert "quality report is missing run_id" in rec.evidence_issues


def test_experiment_comparator_flags_ground_truth_hash_mismatch(tmp_path):
    src_dir = tmp_path / "src"
    eval_dir = tmp_path / "eval_results"
    src_dir.mkdir()
    eval_dir.mkdir()
    (src_dir / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (eval_dir / "quality_report.json").write_text(
        json.dumps({"run_id": "run-1", "score": 100.0, "verdict": "IMPERFECT", "timestamp": "now"}),
        encoding="utf-8",
    )
    (eval_dir / "ground_truth.json").write_text(
        json.dumps({
            "total": 1,
            "passed": 1,
            "failed": 0,
            "pass_rate": 1.0,
            "source_hash": "stale",
        }),
        encoding="utf-8",
    )

    rec = ExperimentComparator.analyze_dir(tmp_path)

    assert rec.evidence_status == "INCOMPLETE"
    assert "ground-truth source hash does not match current source" in rec.evidence_issues


def test_experiment_comparator_positive_valid_evidence(tmp_path):
    """Native DAFG quality reports must not be marked incomplete for absent timestamp/duration."""
    eval_dir = tmp_path / "eval_results"
    eval_dir.mkdir(parents=True)

    # Native RunQualityReport.to_dict schema
    qdata = {
        "run_id": "run_native_valid_01",
        "verdict": "VERIFIED_DELIVERY",
        "score": 96.5,
        "outcome_status": "VERIFIED_DELIVERY",
        "friction_severity_index": 0.05,
        "gate_flakiness_index": 0.0,
        "dimensions": {
            "verification_integrity": {
                "name": "Verification Integrity",
                "score": 100.0,
                "weight": 0.25,
                "summary": "all gates met cleanly",
            }
        },
        "friction_points": [],
        "recommendations": [],
    }
    (eval_dir / "quality_report.json").write_text(json.dumps(qdata), encoding="utf-8")

    rec = ExperimentComparator.analyze_dir(tmp_path)
    assert rec.evidence_status == "VALID"
    assert rec.evidence_issues == []
    assert rec.run_id == "run_native_valid_01"
    assert rec.composite_score == 96.5
    assert rec.verdict == "VERIFIED_DELIVERY"

    table = ExperimentComparator.generate_markdown_table([rec])
    assert "`VALID`" in table
    assert "**INCOMPLETE**" not in table

    # Real on-disk native experiment report
    node_rec = ExperimentComparator.analyze_dir(Path("experiments/node_service_blackbox"))
    assert node_rec.evidence_status == "VALID"
    assert node_rec.evidence_issues == []


def test_experiment_comparator_fresh_computes_evidence_status():
    """analyze_dir(fresh=True) must compute evidence_status and evidence_issues before returning."""
    target_dir = Path("experiments/node_service_blackbox")
    rec = ExperimentComparator.analyze_dir(target_dir, fresh=True)

    assert rec.provenance == "fresh_execution"
    assert rec.evidence_status == "VALID"
    assert rec.evidence_issues == []
    assert rec.run_id != "unknown"
    assert rec.composite_score >= 80.0

    # Ensure fresh execution on a directory with defective ground truth computes issues
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Copy GATES.md
        (tmp_path / "GATES.md").write_text((target_dir / "GATES.md").read_text(encoding="utf-8"), encoding="utf-8")
        appr_file = target_dir / ".approved_gates.json"
        if appr_file.exists():
            (tmp_path / ".approved_gates.json").write_text(appr_file.read_text(encoding="utf-8"), encoding="utf-8")

        # Create on-disk src and mismatched ground truth
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("VALUE = 42\n", encoding="utf-8")

        eval_dir = tmp_path / "eval_results"
        eval_dir.mkdir()
        (eval_dir / "ground_truth.json").write_text(
            json.dumps({
                "total": 5,
                "passed": 5,
                "failed": 0,
                "pass_rate": 1.0,
                "source_hash": "mismatched_source_hash",
            }),
            encoding="utf-8",
        )

        rec_defective = ExperimentComparator.analyze_dir(tmp_path, fresh=True)
        assert rec_defective.provenance == "fresh_execution"
        assert rec_defective.evidence_status == "INCOMPLETE"
        assert "ground-truth source hash does not match current source" in rec_defective.evidence_issues


def test_experiment_comparator_flags_malformed_ground_truth(tmp_path):
    """Strict detection for missing ground truth fields and malformed numeric metrics."""
    eval_dir = tmp_path / "eval_results"
    eval_dir.mkdir(parents=True)
    (eval_dir / "quality_report.json").write_text(
        json.dumps({"run_id": "run-gt-01", "score": 90.0, "verdict": "IMPERFECT"}),
        encoding="utf-8",
    )

    # Missing required 'pass_rate' and 'failed'
    (eval_dir / "ground_truth.json").write_text(
        json.dumps({"total": 10, "passed": 10}),
        encoding="utf-8",
    )
    rec = ExperimentComparator.analyze_dir(tmp_path)
    assert rec.evidence_status == "INCOMPLETE"
    assert any("ground truth is missing fields: failed, pass_rate" in issue for issue in rec.evidence_issues)

    # Malformed numeric metrics (passed + failed > total)
    (eval_dir / "ground_truth.json").write_text(
        json.dumps({"total": 5, "passed": 10, "failed": 2, "pass_rate": 2.0}),
        encoding="utf-8",
    )
    rec2 = ExperimentComparator.analyze_dir(tmp_path)
    assert rec2.evidence_status == "INCOMPLETE"
    assert "ground truth contains malformed metrics" in rec2.evidence_issues
