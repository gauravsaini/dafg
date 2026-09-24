import ast
from dafg.eval import EvaluationHarness


def test_phase1_pilot_tasks():
    harness = EvaluationHarness()
    tasks = harness.load_phase1_pilot_tasks()

    # Assert 1: 75 tasks
    assert len(tasks) == 75

    # Assert 2: per-cohort numbers
    assert {c: sum(1 for t in tasks if t.cohort == c) for c in ["multifile", "protocol", "concurrency", "impossible"]} == {
        "multifile": 20,
        "protocol": 20,
        "concurrency": 15,
        "impossible": 20,
    }

    # Assert 3: fixtures ast.parse OK
    assert all(ast.parse(t.test_fixture) is not None for t in tasks)

    # Assert 4: impossible infeasible
    assert all(not t.is_feasible for t in tasks if t.cohort == "impossible") and all(
        t.is_feasible for t in tasks if t.cohort != "impossible"
    )

    # Assert 5: disjoint OWNS per cohort
    for cohort in ["multifile", "protocol", "concurrency", "impossible"]:
        seen_owns = set()
        for t in tasks:
            if t.cohort == cohort:
                for path in t.all_owns:
                    assert path not in seen_owns, f"Duplicate OWNS {path} in cohort {cohort}"
                    seen_owns.add(path)
