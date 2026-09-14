"""CI integrity test: ensures ground_truth.json artifacts are never committed stale or fabricated.

Checks:
1. Every committed generation in experiments/real_world_agent_eval/generations/ must have a
   valid eval_results/ground_truth.json whose recorded source_hash matches a fresh SHA-256
   of its on-disk src/*.py files.
2. ExperimentComparator must automatically detect hash mismatches, set gt_hash_matched=False,
   and flag the artifact as invalid/stale in markdown table reductions.
"""
from __future__ import annotations

import json
import pathlib
import hashlib
import tempfile
import pytest

from dafg.compare import ExperimentComparator, ExperimentRecord


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
GENERATIONS_DIR = REPO_ROOT / "experiments" / "real_world_agent_eval" / "generations"


def test_all_committed_generation_ground_truths_match_source_hash():
    """Fail CI if any committed ground_truth.json does not match the actual on-disk source code."""
    assert GENERATIONS_DIR.is_dir(), f"Generations dir not found: {GENERATIONS_DIR}"

    gen_dirs = sorted([d for d in GENERATIONS_DIR.iterdir() if d.is_dir()])
    assert len(gen_dirs) >= 4, f"Expected at least 4 generations, found {len(gen_dirs)}"

    for gd in gen_dirs:
        gt_file = gd / "eval_results" / "ground_truth.json"
        assert gt_file.is_file(), f"Missing ground_truth.json for generation: {gd.name}"

        gt_data = json.loads(gt_file.read_text(encoding="utf-8"))
        assert "source_hash" in gt_data, f"ground_truth.json for {gd.name} missing 'source_hash' field"

        recorded_hash = gt_data["source_hash"]
        expected_hash = ExperimentComparator.compute_source_hash(gd)

        assert expected_hash is not None, f"Could not compute source hash for {gd.name} (no src/*.py?)"
        assert recorded_hash == expected_hash, (
            f"INTEGRITY VIOLATION in {gd.name}:\n"
            f"Recorded source_hash in ground_truth.json: {recorded_hash}\n"
            f"Actual computed hash of on-disk src/*.py:  {expected_hash}\n"
            f"This artifact is STALE or was copied from another codebase without running the test suite."
        )


def test_comparator_detects_tampered_ground_truth_hash():
    """ExperimentComparator must flag a mismatched or tampered source_hash as invalid."""
    gen_4 = GENERATIONS_DIR / "gen_4_verified_delivery"
    assert gen_4.is_dir()

    # Normal analysis of valid generation
    rec_valid = ExperimentComparator.analyze_dir(gen_4)
    assert rec_valid.gt_hash_matched is True
    assert rec_valid.gt_pass_rate == 1.0

    # Tampered analysis in temp dir with altered source_hash
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        # Copy src
        src_tmp = tmp_path / "src"
        src_tmp.mkdir()
        for f in (gen_4 / "src").glob("*.py"):
            (src_tmp / f.name).write_bytes(f.read_bytes())

        # Copy GATES.md
        if (gen_4 / "GATES.md").is_file():
            (tmp_path / "GATES.md").write_text((gen_4 / "GATES.md").read_text())

        # Write fraudulent ground_truth with mismatched hash
        eval_dir = tmp_path / "eval_results"
        eval_dir.mkdir()
        fake_gt = {
            "total": 20,
            "passed": 20,
            "failed": 0,
            "pass_rate": 1.0,
            "source_hash": "deadbeef12345678",
            "generated_at": "2026-01-01T00:00:00Z",
        }
        (eval_dir / "ground_truth.json").write_text(json.dumps(fake_gt))

        rec_tampered = ExperimentComparator.analyze_dir(tmp_path)
        assert rec_tampered.gt_hash_matched is False, "Comparator failed to detect mismatched hash!"

        table = ExperimentComparator.generate_markdown_table([rec_tampered])
        assert "STALE HASH" in table, f"Table did not highlight stale hash:\n{table}"
        assert "INVALID (HASH MISMATCH)" in table, f"Table did not flag discrepancy as invalid:\n{table}"
