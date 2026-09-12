import pytest
from pathlib import Path
from dafg.gates import Gate, GateLedger, GateLinter, LintIssue

def test_build_dependency_graph_empty():
    ledger = GateLedger.parse("")
    graph = GateLinter.build_dependency_graph(ledger)
    assert graph == {}

def test_build_dependency_graph_no_deps():
    md = """
- [ ] G1: First
  CHECK: echo "hello"
  EXPECT: hello
- [ ] G2: Second
  CHECK: echo "world"
  EXPECT: world
"""
    ledger = GateLedger.parse(md.strip())
    graph = GateLinter.build_dependency_graph(ledger)
    assert graph == {"G1": set(), "G2": set()}

def test_build_dependency_graph_with_deps():
    md = """
- [ ] G1: First
  CHECK: cat file.txt
  EXPECT: data
- [ ] G2: Second
  CHECK: python script.py G1
  EXPECT: ok
- [ ] G3: Third
  CHECK: grep G2 state.json G1
  EXPECT: done
"""
    ledger = GateLedger.parse(md.strip())
    graph = GateLinter.build_dependency_graph(ledger)
    assert graph == {
        "G1": set(),
        "G2": {"G1"},
        "G3": {"G1", "G2"}
    }

def test_build_dependency_graph_self_edge():
    md = """
- [ ] G1: First
  CHECK: grep G1 GATES.md
  EXPECT: .*
"""
    ledger = GateLedger.parse(md.strip())
    graph = GateLinter.build_dependency_graph(ledger)
    assert graph == {"G1": {"G1"}}

def test_detect_cycles_empty():
    assert GateLinter.detect_cycles({}) == []

def test_detect_cycles_none():
    graph = {
        "A": {"B"},
        "B": {"C"},
        "C": set()
    }
    assert GateLinter.detect_cycles(graph) == []

def test_detect_cycles_simple():
    graph = {
        "A": {"B"},
        "B": {"A"}
    }
    cycles = GateLinter.detect_cycles(graph)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B"}

def test_detect_cycles_three_way():
    graph = {
        "A": {"B"},
        "B": {"C"},
        "C": {"A"}
    }
    cycles = GateLinter.detect_cycles(graph)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B", "C"}

def test_detect_cycles_self_loop():
    graph = {
        "A": {"A"}
    }
    cycles = GateLinter.detect_cycles(graph)
    assert len(cycles) == 1
    assert cycles[0] == ["A"]

def test_detect_cycles_multiple():
    graph = {
        "A": {"B"},
        "B": {"A"},
        "C": {"D"},
        "D": {"E"},
        "E": {"C"}
    }
    cycles = GateLinter.detect_cycles(graph)
    assert len(cycles) == 2

def test_detect_self_reference_grep_own_id_ledger():
    md = """
- [ ] G1: Self ref
  CHECK: grep G1 GATES.md
  EXPECT: ok
"""
    ledger = GateLedger.parse(md.strip())
    gate = ledger.gates["G1"]
    assert GateLinter.detect_self_reference(gate, ledger) == True

def test_detect_self_reference_grep_other_id_ledger():
    md = """
- [ ] G1: Other ref
  CHECK: grep G2 GATES.md
  EXPECT: ok
- [ ] G2: Second
  CHECK: echo ok
  EXPECT: ok
"""
    ledger = GateLedger.parse(md.strip())
    gate = ledger.gates["G1"]
    assert GateLinter.detect_self_reference(gate, ledger) == False

def test_detect_self_reference_status():
    md = """
- [ ] G1: Status ref
  CHECK: gates --status | grep G1
  EXPECT: ok
"""
    ledger = GateLedger.parse(md.strip())
    gate = ledger.gates["G1"]
    assert GateLinter.detect_self_reference(gate, ledger) == True

def test_detect_self_reference_evidence():
    md = """
- [ ] G1: Evidence ref
  CHECK: check_evidence.sh G1 EVIDENCE
  EXPECT: ok
"""
    ledger = GateLedger.parse(md.strip())
    gate = ledger.gates["G1"]
    assert GateLinter.detect_self_reference(gate, ledger) == True

def test_detect_self_reference_no_ledger():
    md = """
- [ ] G1: No ledger
  CHECK: echo G1
  EXPECT: ok
"""
    ledger = GateLedger.parse(md.strip())
    gate = ledger.gates["G1"]
    assert GateLinter.detect_self_reference(gate, ledger) == False

def test_lint_self_reference():
    md = """
- [ ] G1: Deadlock
  CHECK: grep G1 GATES.md
  EXPECT: ok
"""
    ledger = GateLedger.parse(md.strip())
    issues = GateLinter.lint(ledger)
    assert any(i.severity == "ERROR" and "self-reference deadlock" in i.message for i in issues)

def test_lint_cyclic():
    md = """
- [ ] G1: First
  CHECK: check G2
  EXPECT: ok
- [ ] G2: Second
  CHECK: check G1
  EXPECT: ok
"""
    ledger = GateLedger.parse(md.strip())
    issues = GateLinter.lint(ledger)
    assert any(i.severity == "ERROR" and "Circular dependency" in i.message for i in issues)

def test_lint_ledger_coupling():
    md = """
- [ ] G1: Coupling
  CHECK: grep something GATES.md
  EXPECT: ok
"""
    ledger = GateLedger.parse(md.strip())
    issues = GateLinter.lint(ledger)
    assert any(i.severity == "WARNING" and "potential ledger-state coupling" in i.message for i in issues)

def test_lint_clean():
    md = """
- [ ] G1: First
  CHECK: echo hello
  EXPECT: hello
- [ ] G2: Second
  CHECK: echo G1
  EXPECT: G1
"""
    ledger = GateLedger.parse(md.strip())
    issues = GateLinter.lint(ledger)
    # Filter out WARNINGs for unfalsifiable commands if any, but we shouldn't have errors about cycles
    errors = [i for i in issues if i.severity == "ERROR"]
    assert len(errors) == 0

def test_detect_cycles_complex():
    graph = {
        "A": {"B", "C"},
        "B": {"C"},
        "C": {"A"}
    }
    cycles = GateLinter.detect_cycles(graph)
    assert len(cycles) > 0
