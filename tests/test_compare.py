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
