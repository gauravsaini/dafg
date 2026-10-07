"""Tests for the v04 fixture-redesign pilot suite.

The critical invariant: no fixture may be vacuous. Every v04 fixture must
reference at least one of its task's owns modules, so a fixture can never
silently regress to the Phase-1 vacuity (0/75 fixtures referencing workspace
code, machine-verified 2026-10-08).
"""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
SUITE = REPO / "benchmarks" / "v04_pilot"

sys.path.insert(0, str(REPO / "src"))
from dafg.eval import EvaluationHarness  # noqa: E402


def _load_raw():
    return json.loads((SUITE / "tasks.json").read_text(encoding="utf-8"))


def _owns_stems(task_dict):
    stems = set()
    for node in task_dict["initial_nodes"]:
        for p in node["owns"]:
            stems.add(Path(p).stem)
    return stems


def test_suite_has_20_tasks_across_3_cohorts():
    tasks = _load_raw()
    assert len(tasks) == 20
    cohorts = {}
    for t in tasks:
        cohorts[t["cohort"]] = cohorts.get(t["cohort"], 0) + 1
    assert cohorts == {"multifile": 8, "protocol": 6, "concurrency": 6}


def test_no_fixture_is_vacuous():
    """Every fixture must reference at least one owns module stem.

    This is the machine-enforced version of the vacuity check: if a future
    fixture edit drops all workspace references, this test fails loudly
    instead of letting EVD silently stop discriminating.
    """
    tasks = _load_raw()
    for t in tasks:
        fixture = (SUITE / t["fixture_file"]).read_text(encoding="utf-8")
        stems = _owns_stems(t)
        assert any(
            re.search(r"\b" + re.escape(s) + r"\b", fixture) for s in stems
        ), f"{t['task_id']}: fixture references no owns module {sorted(stems)}"


def test_every_fixture_prints_eval_passed():
    tasks = _load_raw()
    for t in tasks:
        fixture = (SUITE / t["fixture_file"]).read_text(encoding="utf-8")
        assert "EVAL_PASSED" in fixture, f"{t['task_id']}: missing EVAL_PASSED marker"


def test_every_fixture_has_behavior_docstring():
    tasks = _load_raw()
    for t in tasks:
        fixture = (SUITE / t["fixture_file"]).read_text(encoding="utf-8").lstrip()
        assert fixture.startswith('"""'), f"{t['task_id']}: fixture lacks docstring"


def test_loader_inlines_fixtures_and_builds_tasks():
    tasks = EvaluationHarness().load_v04_pilot_tasks()
    assert len(tasks) == 20
    for t in tasks:
        assert "EVAL_PASSED" in (t.test_fixture or "")
        assert len(t.all_owns) >= 1
        # no task may be vacuous after loading either
        stems = [Path(p).stem for p in t.all_owns]
        assert any(
            re.search(r"\b" + re.escape(s) + r"\b", t.test_fixture) for s in stems
        ), f"{t.task_id}: loaded fixture is vacuous"


def test_reference_trees_cover_all_owns():
    tasks = _load_raw()
    for t in tasks:
        ref = SUITE / "reference" / t["task_id"]
        for node in t["initial_nodes"]:
            for p in node["owns"]:
                assert (ref / p).exists(), f"{t['task_id']}: missing reference {p}"


def test_broken_variants_overlay_known_files():
    tasks = _load_raw()
    for t in tasks:
        ref_files = {
            str(p.relative_to(SUITE / "reference" / t["task_id"]))
            for p in (SUITE / "reference" / t["task_id"]).rglob("*")
            if p.is_file()
        }
        for variant in ("broken_v1", "broken_v2"):
            vdir = SUITE / "broken" / t["task_id"] / variant
            assert vdir.exists(), f"{t['task_id']}: missing {variant}"
            for p in vdir.rglob("*"):
                if p.is_file():
                    rel = str(p.relative_to(vdir))
                    assert rel in ref_files, f"{t['task_id']}: {variant} overlays unknown {rel}"


def test_validation_report_exists_and_all_pass():
    rep_path = REPO / "eval_results" / "v04_fixture_validation.json"
    assert rep_path.exists(), "run scripts/validate_v04_fixtures.py first"
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    assert rep["tasks"] == 20
    assert rep["gates_failed"] == 0, [
        r["task_id"] for r in rep["results"] if r["gate"] != "PASS"
    ]


def test_vacuity_check_would_catch_phase1_style_fixture():
    """The check itself is validated: a Phase-1-style vacuous fixture fails it."""
    vacuous = "def test_x():\n    d = {'a': 1}\n    assert d['a'] == 1\ntest_x()\n"
    stems = {"models", "services"}
    assert not any(
        re.search(r"\b" + re.escape(s) + r"\b", vacuous) for s in stems
    )
