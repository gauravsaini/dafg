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


def test_lint_low_specificity_expect_tokens():
    text = """
- [ ] G1: Bare zero
  CHECK: echo 0
  EXPECT: 0
  OWNS: src/foo.py

- [ ] G2: Lowercase ok
  CHECK: echo ok
  EXPECT: ok
  OWNS: src/foo.py

- [ ] G3: Uppercase OK
  CHECK: echo OK
  EXPECT: OK
  OWNS: src/foo.py

- [ ] G4: Bare one
  CHECK: echo 1
  EXPECT: 1
  OWNS: src/foo.py

- [ ] G5: Boolean true
  CHECK: echo true
  EXPECT: true
  OWNS: src/foo.py

- [ ] G6: Pass token
  CHECK: echo pass
  EXPECT: pass
  OWNS: src/foo.py

- [ ] G7: Yes token
  CHECK: echo yes
  EXPECT: yes
  OWNS: src/foo.py
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    warn_gates = {i.gate_id for i in issues if i.severity == "WARNING" and "low-specificity EXPECT token" in i.message}
    assert warn_gates == {"G1", "G2", "G3", "G4", "G5", "G6", "G7"}


def test_lint_high_specificity_expect_no_warning():
    text = """
- [ ] G1: Passed status
  CHECK: pytest
  EXPECT: passed
  OWNS: src/foo.py

- [ ] G2: Specific test count
  CHECK: pytest
  EXPECT: OK (tests=15)
  OWNS: src/foo.py

- [ ] G3: Exit code pattern
  CHECK: ./run.sh
  EXPECT: exit_code=0
  OWNS: src/foo.py

- [ ] G4: Long success string
  CHECK: make build
  EXPECT: build_successful
  OWNS: src/foo.py
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    low_spec_warnings = [i for i in issues if "low-specificity EXPECT token" in i.message]
    assert len(low_spec_warnings) == 0


def test_lint_missing_owns_on_runnable_gate_warning():
    text = """
- [ ] G1: Runnable without owns
  CHECK: echo "hello world"
  EXPECT: hello world

- [ ] G2: Runnable with whitespace owns
  CHECK: echo "hello world"
  EXPECT: hello world
  OWNS:   

- [ ] G3: Runnable with valid owns
  CHECK: echo "hello world"
  EXPECT: hello world
  OWNS: src/foo.py
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    owns_warnings = {i.gate_id for i in issues if i.severity == "WARNING" and "declares no OWNS: files" in i.message}
    assert owns_warnings == {"G1", "G2"}
    assert "G3" not in owns_warnings


def test_lint_manual_gate_no_owns_no_warning():
    text = """
- [ ] G1: Manual gate without owns
  EVIDENCE: verified by architect
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    owns_warnings = [i for i in issues if "declares no OWNS: files" in i.message]
    assert len(owns_warnings) == 0


def test_lint_empty_match_regexes():
    text = """
- [ ] G1: Empty line anchor
  CHECK: echo ""
  EXPECT: ^$
  OWNS: src/foo.py

- [ ] G2: Match star
  CHECK: echo ""
  EXPECT: .*
  OWNS: src/foo.py

- [ ] G3: Whitespace star
  CHECK: echo ""
  EXPECT: \\s*
  OWNS: src/foo.py

- [ ] G4: Non-empty specific regex
  CHECK: echo "hello"
  EXPECT: hello+
  OWNS: src/foo.py
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    empty_warnings = {i.gate_id for i in issues if i.severity == "WARNING" and "matches empty/trivial output" in i.message}
    assert "G1" in empty_warnings
    assert "G2" in empty_warnings
    assert "G3" in empty_warnings
    assert "G4" not in empty_warnings


def test_parse_author_property():
    text = """
- [ ] G1: Human gate
  CHECK: echo "verified"
  EXPECT: verified
  AUTHOR: human

- [ ] G2: Planner gate
  CHECK: echo "planned"
  EXPECT: planned
  AUTHOR: Planner

- [ ] G3: Implementer gate
  CHECK: echo "done"
  EXPECT: done
  AUTHOR:   Implementer  

- [ ] G4: External gate
  CHECK: echo "tested"
  EXPECT: tested
  AUTHOR: EXTERNAL

- [ ] G5: Unspecified author
  CHECK: echo "default"
  EXPECT: default
"""
    ledger = GateLedger.parse(text)
    assert ledger.gates["G1"].author == "human"
    assert ledger.gates["G2"].author == "planner"
    assert ledger.gates["G3"].author == "implementer"
    assert ledger.gates["G4"].author == "external"
    assert ledger.gates["G5"].author is None


def test_lint_authorship_separation_standard_and_strict():
    text_standard = """
- [ ] G1: Implementer authored
  CHECK: echo "deliverable"
  EXPECT: deliverable
  OWNS: src/foo.py
  AUTHOR: implementer

- [ ] G2: Human authored
  CHECK: echo "deliverable"
  EXPECT: deliverable
  OWNS: src/foo.py
  AUTHOR: human
"""
    # Standard mode: WARNING
    ledger_std = GateLedger.parse(text_standard)
    issues_std = GateLinter.lint(ledger_std)
    auth_issues_std = [i for i in issues_std if "violates authorship separation" in i.message]
    assert len(auth_issues_std) == 1
    assert auth_issues_std[0].gate_id == "G1"
    assert auth_issues_std[0].severity == "WARNING"

    # Strict mode: ERROR
    text_strict = """MODE: strict
- [ ] G1: Implementer authored
  CHECK: echo "deliverable"
  EXPECT: deliverable
  OWNS: src/foo.py
  AUTHOR: implementer

- [ ] G2: Planner authored
  CHECK: echo "deliverable"
  EXPECT: deliverable
  OWNS: src/foo.py
  AUTHOR: planner
"""
    ledger_strict = GateLedger.parse(text_strict)
    issues_strict = GateLinter.lint(ledger_strict)
    auth_issues_strict = [i for i in issues_strict if "violates authorship separation" in i.message]
    assert len(auth_issues_strict) == 1
    assert auth_issues_strict[0].gate_id == "G1"
    assert auth_issues_strict[0].severity == "ERROR"


def test_lint_quick_mode_suppresses_warnings():
    text = """MODE: quick
- [ ] G1: Bare low-spec token without owns
  CHECK: echo ok
  EXPECT: ok
  AUTHOR: implementer
"""
    ledger = GateLedger.parse(text)
    issues = GateLinter.lint(ledger)
    assert len(issues) == 0

    # But errors are still retained
    text_err = """MODE: quick
- [ ] G1: 
  CHECK: echo ok
  EXPECT: ok
"""
    ledger_err = GateLedger.parse(text_err)
    issues_err = GateLinter.lint(ledger_err)
    assert len(issues_err) == 1
    assert issues_err[0].severity == "ERROR"
    assert "empty title" in issues_err[0].message


def test_mode_header_formats():
    text1 = "<!-- MODE: quick -->\n- [ ] G1: T\n  CHECK: echo ok\n  EXPECT: ok\n"
    assert GateLedger.parse(text1).mode == "quick"

    text2 = "# MODE: strict\n- [ ] G1: T\n  CHECK: echo ok\n  EXPECT: ok\n"
    assert GateLedger.parse(text2).mode == "strict"

    text3 = "mode: standard\n- [ ] G1: T\n  CHECK: echo ok\n  EXPECT: ok\n"
    assert GateLedger.parse(text3).mode == "standard"




