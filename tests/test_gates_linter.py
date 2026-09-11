"""Tests for GateLinter catching syntax, duplicate IDs, missing tokens, and tautologies."""

import pytest
from dafg.gates import GateLedger, GateLinter


def test_lint_duplicate_ids():
    text = """
- [ ] G1: First gate
  CHECK: echo 1
  EXPECT: 1

- [ ] G1: Duplicate gate
  CHECK: echo 2
  EXPECT: 2
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    dup_errors = [i for i in issues if "Duplicate gate ID 'G1'" in i.message]
    assert len(dup_errors) == 1
    assert dup_errors[0].severity == "ERROR"


def test_lint_empty_title():
    text = """
- [ ] G1: 
  CHECK: echo 1
  EXPECT: 1
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    empty_title_errors = [i for i in issues if "empty title" in i.message]
    assert len(empty_title_errors) == 1


def test_lint_missing_tokens():
    text = """
- [ ] G1: Gate without expect
  CHECK: echo 1

- [ ] G2: Gate without check
  EXPECT: 1

- [ ] G3: Gate completely empty
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("missing EXPECT pattern" in m for m in messages)
    assert any("missing CHECK command" in m for m in messages)
    assert any("empty: missing CHECK command" in m for m in messages)


def test_lint_invalid_and_tautological_expect():
    text = """
- [ ] G1: Broken regex
  CHECK: echo 1
  EXPECT: [unclosed

- [ ] G2: Tautological regex
  CHECK: echo 2
  EXPECT: .*

- [ ] G3: Empty expect
  CHECK: echo 3
  EXPECT: 
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("invalid regex pattern in EXPECT" in m for m in messages)
    assert any("tautological EXPECT pattern" in m for m in messages)
    assert any("empty EXPECT pattern" in m for m in messages)


def test_lint_abandonment_errors():
    text = """
- [-] G1: Abandoned gate with no reason

ABANDON: G2 
ABANDON: G99 Non existent gate
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("marked abandoned without a non-empty reason" in m for m in messages)
    assert any("unknown gate ID 'G99'" in m for m in messages)


def test_clean_ledger_passes_lint():
    text = """# Clean Ledger
- [ ] G1: Clean gate
  CHECK: echo "hello world"
  EXPECT: hello
  CWD: .

- [x] G2: Passed gate
  CHECK: python -c "print(123)"
  EXPECT: 123
  EVIDENCE: exit_code=0 timestamp=2026-09-10T12:00:00Z match='123'
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    errors = [i for i in issues if i.severity == "ERROR"]
    assert len(errors) == 0


def test_lint_abandon_without_reason_parsed():
    # ABANDON: G1 with NO trailing space or reason must be parsed and flagged
    text = """
- [ ] G1: First
  CHECK: echo 1
  EXPECT: 1

ABANDON: G1
"""
    ledger = GateLedger.parse(text)
    assert "G1" in ledger.abandonments
    assert ledger.abandonments["G1"] == ""

    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("missing non-empty reason" in m for m in messages)


def test_lint_advanced_tautological_patterns():
    text = """
- [ ] G1: Dotall match-all
  CHECK: echo 1
  EXPECT: (?s).*

- [ ] G2: Character class match-all
  CHECK: echo 2
  EXPECT: [\\s\\S]*
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("tautological EXPECT pattern '(?s).*'" in m for m in messages)
    assert any("tautological EXPECT pattern '[\\s\\S]*'" in m for m in messages)


def test_lint_catches_malformed_gate_headers():
    text = """
- [ ] G1: First valid
  CHECK: echo 1
  EXPECT: 1

- [] G2: Malformed empty bracket
  CHECK: echo 2
  EXPECT: 2

- [?] G3: Unsupported checkbox mark
  CHECK: echo 3
  EXPECT: 3
"""
    ledger = GateLedger.parse(text)
    assert len(ledger.syntax_errors) >= 2
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("Malformed gate header syntax" in m for m in messages)


def test_lint_catches_orphaned_properties():
    text = """
# Some header without gates
  CHECK: echo orphaned
  EXPECT: orphaned

- [ ] G1: First valid
  CHECK: echo 1
  EXPECT: 1
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("Orphaned gate property" in m for m in messages)


def test_lint_catches_invalid_timeout_and_empty_cwd():
    text = """
- [ ] G1: Invalid timeout
  CHECK: echo 1
  EXPECT: 1
  TIMEOUT: -2

- [ ] G2: Empty CWD
  CHECK: echo 2
  EXPECT: 2
  CWD:   
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("invalid non-positive TIMEOUT" in m for m in messages)
    assert any("empty CWD" in m for m in messages)


def test_lint_flagged_tautological_patterns():
    text = """
- [ ] G1: Case-insensitive dotall
  CHECK: echo 1
  EXPECT: (?is).*

- [ ] G2: Word char class match-all
  CHECK: echo 2
  EXPECT: [\\w\\W]*
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("tautological EXPECT pattern '(?is).*'" in m for m in messages)
    assert any("tautological EXPECT pattern '[\\w\\W]*'" in m for m in messages)


def test_lint_catches_unindented_orphaned_properties():
    """Unindented properties (column 0) without preceding gate must be caught as orphaned errors."""
    text = """CHECK: echo orphaned
EXPECT: orphaned

- [ ] G1: First gate
  CHECK: echo 1
  EXPECT: 1
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("Orphaned gate property 'CHECK'" in m for m in messages)
    assert any("Orphaned gate property 'EXPECT'" in m for m in messages)


def test_lint_catches_parenthesized_and_plus_tautological_patterns():
    """Parenthesized match-all or plus-quantified match-all patterns must be caught as tautological."""
    text = """
- [ ] G1: Capturing match-all
  CHECK: echo 1
  EXPECT: (.*)

- [ ] G2: Non-capturing match-all
  CHECK: echo 2
  EXPECT: (?:.*)

- [ ] G3: Plus quantified match-all
  CHECK: echo 3
  EXPECT: [\\s\\S]+
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    messages = [i.message for i in issues]
    assert any("tautological EXPECT pattern '(.*)'" in m for m in messages)
    assert any("tautological EXPECT pattern '(?:.*)'" in m for m in messages)
    assert any("tautological EXPECT pattern '[\\s\\S]+'" in m for m in messages)


