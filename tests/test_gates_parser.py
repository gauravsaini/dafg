"""Tests for GATES.md parser and serializer."""

import pytest
from pathlib import Path
from dafg.gates import GateLedger, Gate


SAMPLE_LEDGER = """# Project Acceptance Gates

Some preliminary context text.

- [ ] G1: Project builds cleanly
  CHECK: python -c "print('build ok')"
  EXPECT: build ok
  CWD: .

- [x] G2: Unit tests pass
  CHECK: pytest
  EXPECT: passed
  EVIDENCE: exit_code=0 timestamp=2026-09-10T12:00:00Z match='passed'

- [ ] G3: Performance criteria
  CHECK: python -c "print('perf 42ms')"
  EXPECT: perf
  OWNS: src/perf.py

ABANDON: G4 Legacy feature dropped
"""


def test_parse_sample_ledger():
    ledger = GateLedger.parse(SAMPLE_LEDGER)
    assert len(ledger.gates) == 3
    assert "G1" in ledger.gates
    assert "G2" in ledger.gates
    assert "G3" in ledger.gates

    g1 = ledger.gates["G1"]
    assert g1.id == "G1"
    assert g1.title == "Project builds cleanly"
    assert g1.status == "UNMET"
    assert g1.check == 'python -c "print(\'build ok\')"'
    assert g1.expect == "build ok"
    assert g1.cwd == "."
    assert g1.evidence is None

    g2 = ledger.gates["G2"]
    assert g2.id == "G2"
    assert g2.status == "MET"
    assert g2.evidence == "exit_code=0 timestamp=2026-09-10T12:00:00Z match='passed'"

    g3 = ledger.gates["G3"]
    assert g3.id == "G3"
    assert g3.owns == "src/perf.py"

    assert "G4" in ledger.abandonments
    assert ledger.abandonments["G4"] == "Legacy feature dropped"


def test_update_gate_evidence_preserves_formatting():
    ledger = GateLedger.parse(SAMPLE_LEDGER)
    ev_str = "exit_code=0 timestamp=2026-09-11T00:00:00Z match='build ok'"
    ledger.update_gate_evidence("G1", ev_str, met=True)

    g1 = ledger.gates["G1"]
    assert g1.status == "MET"
    assert g1.evidence == ev_str

    serialized = ledger.serialize()
    # Check that G1 is now [x]
    assert "- [x] G1: Project builds cleanly" in serialized
    # Check that EVIDENCE was inserted
    assert f"EVIDENCE: {ev_str}" in serialized
    # Check that other gates and headers were preserved intact
    assert "# Project Acceptance Gates" in serialized
    assert "Some preliminary context text." in serialized
    assert "- [x] G2: Unit tests pass" in serialized
    assert "- [ ] G3: Performance criteria" in serialized
    assert "ABANDON: G4 Legacy feature dropped" in serialized


def test_demote_gate_evidence():
    ledger = GateLedger.parse(SAMPLE_LEDGER)
    # Demote G2
    ledger.update_gate_evidence("G2", None, met=False)
    g2 = ledger.gates["G2"]
    assert g2.status == "UNMET"
    assert g2.evidence is None

    serialized = ledger.serialize()
    assert "- [ ] G2: Unit tests pass" in serialized
    # Previous evidence line is removed
    assert "timestamp=2026-09-10T12:00:00Z" not in serialized


def test_abandon_gate():
    ledger = GateLedger.parse(SAMPLE_LEDGER)
    ledger.abandon_gate("G3", "Not applicable in sandbox")
    g3 = ledger.gates["G3"]
    assert g3.status == "ABANDONED"
    assert g3.abandon_reason == "Not applicable in sandbox"

    serialized = ledger.serialize()
    assert "- [-] G3: Performance criteria" in serialized
    assert "ABANDON: Not applicable in sandbox" in serialized


def test_file_save_and_load(tmp_path):
    f = tmp_path / "GATES.md"
    f.write_text(SAMPLE_LEDGER, encoding="utf-8")

    ledger = GateLedger.load(f)
    assert len(ledger.gates) == 3

    ledger.update_gate_evidence("G1", "exit_code=0 timestamp=now match='ok'", met=True)
    ledger.save()

    reloaded = GateLedger.load(f)
    assert reloaded.gates["G1"].status == "MET"
    assert reloaded.gates["G1"].evidence == "exit_code=0 timestamp=now match='ok'"


def test_contiguous_evidence_formatting():
    text = """- [ ] G1: First gate
  CHECK: echo 1
  EXPECT: 1

- [ ] G2: Second gate
  CHECK: echo 2
  EXPECT: 2
"""
    ledger = GateLedger.parse(text)
    ledger.update_gate_evidence("G1", "exit_code=0 timestamp=2026-09-11 match='1'", met=True)

    expected = """- [x] G1: First gate
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-11 match='1'

- [ ] G2: Second gate
  CHECK: echo 2
  EXPECT: 2
"""
    assert ledger.serialize() == expected


def test_unindented_properties_parsed_under_gate():
    """Unindented properties (column 0) directly following a gate header must attach to the gate."""
    text = """- [ ] G1: First gate
CHECK: echo unindented
EXPECT: unindented
OWNS: src/foo.py
"""
    ledger = GateLedger.parse(text)
    g1 = ledger.gates["G1"]
    assert g1.check == "echo unindented"
    assert g1.expect == "unindented"
    assert g1.owns == "src/foo.py"


def test_abandon_gate_clears_prior_evidence():
    """Abandoning a previously MET gate must remove its EVIDENCE line and mark [-]."""
    text = """- [x] G1: Completed gate
  CHECK: echo ok
  EXPECT: ok
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='ok'
"""
    ledger = GateLedger.parse(text)
    ledger.abandon_gate("G1", "dropped due to change in scope")
    g1 = ledger.gates["G1"]
    assert g1.status == "ABANDONED"
    assert g1.abandon_reason == "dropped due to change in scope"
    assert g1.evidence is None

    serialized = ledger.serialize()
    assert "- [-] G1: Completed gate" in serialized
    assert "ABANDON: dropped due to change in scope" in serialized
    assert "EVIDENCE:" not in serialized


