from __future__ import annotations

import os
from pathlib import Path

from dafg.adversarial import (
    AdversarialInspector,
    AdversarialResult,
    Evaluation,
    ParameterSpace,
    SearchStrategy,
)
from dafg.gates import Gate, GateLedger

def test_parameter_space_parse_range():
    space = ParameterSpace.parse("x=0:10:2,y=0.1:0.5:0.2")
    assert space.dimensions["x"] == [0, 2, 4, 6, 8, 10]
    assert space.dimensions["y"] == [0.1, 0.3, 0.5]

def test_parameter_space_parse_explicit():
    space = ParameterSpace.parse("a=red;green;blue,b=1;2")
    assert space.dimensions["a"] == ["red", "green", "blue"]
    assert space.dimensions["b"] == ["1", "2"]

def test_parameter_space_parse_single_value():
    space = ParameterSpace.parse("x=5")
    assert space.dimensions["x"] == ["5"]

def test_parameter_space_parse_empty():
    space = ParameterSpace.parse("")
    assert not space.dimensions
    space2 = ParameterSpace.parse("   ")
    assert not space2.dimensions

def test_parameter_space_parse_malformed():
    space = ParameterSpace.parse("x=0:10,y=,z")
    assert "x" not in space.dimensions
    assert space.dimensions["y"] == [""]
    assert "z" not in space.dimensions

def test_parameter_space_total_combinations():
    assert ParameterSpace(dimensions={"x": [1, 2]}).total_combinations == 2
    assert ParameterSpace(dimensions={"x": [1, 2], "y": [3, 4, 5]}).total_combinations == 6
    assert ParameterSpace(dimensions={}).total_combinations == 0

def test_search_strategy_enum():
    assert SearchStrategy.GRID.value == "GRID"
    assert SearchStrategy.RANDOM.value == "RANDOM"
    assert SearchStrategy.ADAPTIVE.value == "ADAPTIVE"

def test_adversarial_inspector_always_passes():
    gate = Gate(id="g1", title="G", check="exit 0", expect=".*")
    space = ParameterSpace(dimensions={"x": [1, 2]})
    inspector = AdversarialInspector()
    res = inspector.search(gate, space, budget=10)
    assert not res.found_failure
    assert res.budget_used == 2
    assert len(res.all_evaluations) == 2
    assert res.coverage_pct == 100.0
    for ev in res.all_evaluations:
        assert ev.passed

def test_adversarial_inspector_failure_found():
    # Fails if DAFG_ADV_X is 2
    check_cmd = "if [ \"$DAFG_ADV_X\" = \"2\" ]; then exit 1; else exit 0; fi"
    gate = Gate(id="g2", title="G", check=check_cmd)
    space = ParameterSpace(dimensions={"x": [1, 2, 3]})
    inspector = AdversarialInspector()
    res = inspector.search(gate, space, budget=10)
    assert res.found_failure
    assert res.budget_used == 3
    
    failures = [ev for ev in res.all_evaluations if not ev.passed]
    assert len(failures) == 1
    assert failures[0].params["x"] == 2

def test_adversarial_inspector_grid_exhaustive():
    gate = Gate(id="g3", title="G", check="exit 0")
    space = ParameterSpace.parse("x=1:3:1,y=1:2:1")
    inspector = AdversarialInspector()
    res = inspector.search(gate, space, strategy=SearchStrategy.GRID, budget=100)
    assert res.budget_used == 6
    assert res.coverage_pct == 100.0

def test_adversarial_inspector_random():
    gate = Gate(id="g4", title="G", check="exit 0")
    space = ParameterSpace.parse("x=1:100:1")
    inspector = AdversarialInspector()
    res = inspector.search(gate, space, strategy=SearchStrategy.RANDOM, budget=5)
    assert res.budget_used == 5
    assert len(res.all_evaluations) == 5

def test_adversarial_inspector_budget():
    gate = Gate(id="g5", title="G", check="exit 0")
    space = ParameterSpace.parse("x=1:10:1,y=1:10:1") # 100 combos
    inspector = AdversarialInspector()
    res = inspector.search(gate, space, strategy=SearchStrategy.GRID, budget=10)
    assert res.budget_used == 10
    assert res.coverage_pct == 10.0

def test_adversarial_result_to_dict():
    res = AdversarialResult(
        gate_id="g1",
        worst_params={"x": 1},
        worst_score=1.0,
        best_params={"x": 0},
        best_score=0.0,
        all_evaluations=[
            Evaluation(params={"x": 1}, score=1.0, passed=False)
        ]
    )
    d = res.to_dict()
    assert d["gate_id"] == "g1"
    assert d["worst_score"] == 1.0
    assert len(d["all_evaluations"]) == 1
    assert d["all_evaluations"][0]["passed"] is False

def test_gate_ledger_parse_adversarial():
    text = "- [ ] G1: T\n  CHECK: exit 0\n  ADVERSARIAL: x=1:5:1\n  ADVERSARIAL_BUDGET: 10"
    ledger = GateLedger.parse(text)
    gate = ledger.gates["G1"]
    assert gate.adversarial == "x=1:5:1"
    assert gate.adversarial_budget == 10

def test_adversarial_inspector_no_check():
    gate = Gate(id="g6", title="G")
    space = ParameterSpace(dimensions={"x": [1]})
    inspector = AdversarialInspector()
    res = inspector.search(gate, space)
    assert not res.found_failure
    assert res.budget_used == 0

def test_adversarial_inspector_empty_space():
    gate = Gate(id="g7", title="G", check="exit 0")
    space = ParameterSpace(dimensions={})
    inspector = AdversarialInspector()
    res = inspector.search(gate, space)
    assert res.budget_used == 0

def test_generate_nearby():
    inspector = AdversarialInspector()
    space = ParameterSpace(dimensions={"x": [1, 2, 3], "y": ["a", "b"]})
    params = {"x": 2, "y": "a"}
    nearby = inspector._generate_nearby(params, space, count=5)
    assert len(nearby) == 5
    for p in nearby:
        assert p["x"] in [1, 2, 3]
        assert p["y"] in ["a", "b"]

def test_adaptive_search_nearby():
    # Fails if DAFG_ADV_X is 5
    check_cmd = "if [ \"$DAFG_ADV_X\" = \"5\" ]; then exit 1; else exit 0; fi"
    gate = Gate(id="g8", title="G", check=check_cmd)
    space = ParameterSpace(dimensions={"x": [1, 5, 10]})
    inspector = AdversarialInspector()
    res = inspector.search(gate, space, strategy=SearchStrategy.ADAPTIVE, budget=10)
    assert res.budget_used > 0
