import ast
from dafg.eval import EvaluationHarness


def test_phase1_pilot_tasks():
    harness = EvaluationHarness()
    tasks = harness.load_phase1_pilot_tasks()

    # Assert 1: 20 tasks
    assert len(tasks) == 20

    # Assert 2: 5/cohort
    assert {c: sum(1 for t in tasks if t.cohort == c) for c in ["multifile", "protocol", "concurrency", "impossible"]} == {
        "multifile": 5,
        "protocol": 5,
        "concurrency": 5,
        "impossible": 5,
    }

    # Assert 3: fixtures ast.parse OK
    assert all(ast.parse(t.test_fixture) is not None for t in tasks)

    # Assert 4: impossible infeasible
    assert all(not t.is_feasible for t in tasks if t.cohort == "impossible") and all(
        t.is_feasible for t in tasks if t.cohort != "impossible"
    )
