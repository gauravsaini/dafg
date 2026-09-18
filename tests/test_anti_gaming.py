"""Tests for anti-gaming features: gate regression detector, AUTHOR:implementer
blocking in strict mode, and per-gate GATE_MODE overrides."""

import pytest
from dafg.gates import Gate, GateLedger, GateLinter, LintIssue, classify_evidence, EvidenceStrength
from dafg.hook import CompletionGuard, StopDecision


# ── F1: Gate Regression Detector ──────────────────────────────────────


class TestGateRegressionDetector:
    """GateLinter.detect_regressions(old, new) flags weakened gates."""

    def test_no_regressions_on_identical_ledgers(self):
        text = (
            "- [ ] G1: Test gate\n"
            "  CHECK: echo hello\n"
            "  EXPECT: hello\n"
            "  OWNS: src/foo.py\n"
        )
        old = GateLedger.parse(text)
        new = GateLedger.parse(text)
        issues = GateLinter.detect_regressions(old, new)
        assert issues == []

    def test_shortened_expect_pattern_warns(self):
        old = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo hello_world\n"
            "  EXPECT: hello_world\n"
        )
        new = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo hello_world\n"
            "  EXPECT: hello\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert len(issues) == 1
        assert issues[0].severity == "WARNING"
        assert "shortened" in issues[0].message
        assert "possible weakening" in issues[0].message

    def test_removed_expect_pattern_errors(self):
        old = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        new = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert any(i.severity == "ERROR" and "EXPECT pattern removed" in i.message for i in issues)

    def test_removed_owns_warns(self):
        old = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  OWNS: src/foo.py\n"
        )
        new = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert any("OWNS declaration removed" in i.message for i in issues)

    def test_deleted_gate_without_abandon_errors(self):
        old = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "- [ ] G2: Other\n"
            "  CHECK: echo yes\n"
            "  EXPECT: yes\n"
        )
        new = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert any(i.severity == "ERROR" and "removed without ABANDON" in i.message and i.gate_id == "G2" for i in issues)

    def test_deleted_abandoned_gate_is_fine(self):
        old = GateLedger.parse(
            "- [-] G1: Old gate\n"
            "  ABANDON: G1 No longer relevant after refactor\n"
        )
        new = GateLedger.parse(
            "- [ ] G2: New gate\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert not any(i.gate_id == "G1" for i in issues)

    def test_removed_check_command_errors(self):
        old = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: uv run pytest\n"
            "  EXPECT: passed\n"
        )
        new = GateLedger.parse(
            "- [ ] G1: Test\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert any(i.severity == "ERROR" and "CHECK command removed" in i.message for i in issues)

    def test_downgraded_gate_mode_warns(self):
        old = GateLedger.parse(
            "- [ ] G1: Critical\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: strict\n"
        )
        new = GateLedger.parse(
            "- [ ] G1: Critical\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: quick\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert any("GATE_MODE downgraded" in i.message for i in issues)

    def test_removed_gate_mode_warns(self):
        old = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: strict\n"
        )
        new = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert any("GATE_MODE removed" in i.message for i in issues)

    def test_lengthened_expect_is_not_regression(self):
        """Strengthening a pattern (making it longer/more specific) is fine."""
        old = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo hello\n"
            "  EXPECT: hello\n"
        )
        new = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo hello\n"
            "  EXPECT: hello_world_full_check\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert issues == []

    def test_empty_old_ledger(self):
        old = GateLedger.parse("")
        new = GateLedger.parse(
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
        )
        issues = GateLinter.detect_regressions(old, new)
        assert issues == []


# ── F2: AUTHOR:implementer Blocking in Strict Mode ───────────────────


class TestImplementerBlocking:
    """CompletionGuard blocks AUTHOR:implementer gates in strict mode."""

    def test_implementer_blocked_in_strict_ledger(self):
        text = (
            "MODE: strict\n"
            "- [x] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  AUTHOR: implementer\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='ok'\n"
        )
        ledger = GateLedger.parse(text)
        guard = CompletionGuard(ledger=ledger)
        decision = guard.evaluate()
        assert decision.decision == "block"
        assert "IMPLEMENTER_AUTHORSHIP_BLOCKED" == decision.outcome_status

    def test_implementer_allowed_in_standard_ledger(self):
        """In standard mode, AUTHOR:implementer is a lint warning, not a blocker."""
        text = (
            "MODE: standard\n"
            "- [x] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  AUTHOR: implementer\n"
            "  OWNS: src/foo.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='ok'\n"
        )
        ledger = GateLedger.parse(text)
        guard = CompletionGuard(ledger=ledger)
        decision = guard.evaluate()
        # Not blocked by implementer authorship in standard mode
        assert "IMPLEMENTER_AUTHORSHIP_BLOCKED" != decision.outcome_status

    def test_implementer_blocked_by_per_gate_strict(self):
        """Even in a standard ledger, a gate with GATE_MODE: strict blocks
        AUTHOR:implementer."""
        text = (
            "MODE: standard\n"
            "- [x] G1: Safe gate\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  AUTHOR: external\n"
            "  OWNS: src/foo.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='ok'\n"
            "\n"
            "- [x] G2: Critical gate\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  AUTHOR: implementer\n"
            "  GATE_MODE: strict\n"
            "  OWNS: src/bar.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='ok'\n"
        )
        ledger = GateLedger.parse(text)
        guard = CompletionGuard(ledger=ledger)
        decision = guard.evaluate()
        assert decision.decision == "block"
        assert "IMPLEMENTER_AUTHORSHIP_BLOCKED" == decision.outcome_status
        assert "G2" in decision.reason

    def test_external_author_passes_strict(self):
        text = (
            "MODE: strict\n"
            "- [x] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  AUTHOR: external\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='ok' mutation_tested=true\n"
        )
        ledger = GateLedger.parse(text)
        guard = CompletionGuard(ledger=ledger)
        decision = guard.evaluate()
        assert decision.decision == "allow"

    def test_abandoned_implementer_gate_not_blocked(self):
        """Abandoned gates should not trigger the implementer blocker."""
        text = (
            "MODE: strict\n"
            "- [-] G1: Abandoned gate\n"
            "  AUTHOR: implementer\n"
            "  ABANDON: G1 No longer needed after architectural change to event-driven model\n"
        )
        ledger = GateLedger.parse(text)
        guard = CompletionGuard(ledger=ledger)
        decision = guard.evaluate()
        assert decision.outcome_status != "IMPLEMENTER_AUTHORSHIP_BLOCKED"


# ── F3: Per-Gate GATE_MODE Override ───────────────────────────────────


class TestPerGateModeOverride:
    """GATE_MODE: property allows strict on individual gates in any ledger."""

    def test_gate_mode_parsed(self):
        text = (
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: strict\n"
        )
        ledger = GateLedger.parse(text)
        assert ledger.gates["G1"].gate_mode == "strict"

    def test_gate_mode_case_insensitive(self):
        text = (
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: Strict\n"
        )
        ledger = GateLedger.parse(text)
        assert ledger.gates["G1"].gate_mode == "strict"

    def test_gate_mode_invalid_value_ignored(self):
        text = (
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: invalid\n"
        )
        ledger = GateLedger.parse(text)
        assert ledger.gates["G1"].gate_mode is None

    def test_gate_mode_quick(self):
        text = (
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: quick\n"
        )
        ledger = GateLedger.parse(text)
        assert ledger.gates["G1"].gate_mode == "quick"

    def test_per_gate_strict_enforces_executable_proof(self):
        """A gate with GATE_MODE: strict in a standard ledger blocks completion
        without EXECUTABLE_PROOF."""
        text = (
            "MODE: standard\n"
            "- [x] G1: Normal gate\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  AUTHOR: external\n"
            "  OWNS: src/foo.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='ok'\n"
            "\n"
            "- [x] G2: Critical gate\n"
            "  CHECK: echo critical\n"
            "  EXPECT: critical\n"
            "  AUTHOR: external\n"
            "  GATE_MODE: strict\n"
            "  OWNS: src/bar.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='critical'\n"
        )
        ledger = GateLedger.parse(text)
        guard = CompletionGuard(ledger=ledger)
        decision = guard.evaluate()
        # G2 is strict but only has STRING_MATCH, not EXECUTABLE_PROOF
        assert decision.decision == "block"
        assert "G2" in str(decision.unverified_gates)

    def test_per_gate_strict_with_mutation_passes(self):
        """A gate with GATE_MODE: strict passes if it has EXECUTABLE_PROOF."""
        text = (
            "MODE: standard\n"
            "- [x] G1: Normal gate\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  AUTHOR: external\n"
            "  OWNS: src/foo.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='ok'\n"
            "\n"
            "- [x] G2: Critical gate\n"
            "  CHECK: echo critical\n"
            "  EXPECT: critical\n"
            "  AUTHOR: external\n"
            "  GATE_MODE: strict\n"
            "  OWNS: src/bar.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='critical' mutation_tested=true\n"
        )
        ledger = GateLedger.parse(text)
        guard = CompletionGuard(ledger=ledger)
        decision = guard.evaluate()
        assert decision.decision == "allow"

    def test_per_gate_strict_authorship_lint(self):
        """GATE_MODE: strict on a gate enforces authorship linting."""
        text = (
            "MODE: standard\n"
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: strict\n"
            "  OWNS: src/foo.py\n"
        )
        ledger = GateLedger.parse(text)
        issues = GateLinter.lint(ledger)
        # Should have ERROR for missing AUTHOR in strict gate
        assert any(
            i.severity == "ERROR" and "missing AUTHOR:" in i.message and i.gate_id == "G1"
            for i in issues
        )

    def test_per_gate_strict_implementer_lint(self):
        """GATE_MODE: strict + AUTHOR: implementer is an ERROR."""
        text = (
            "MODE: standard\n"
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  GATE_MODE: strict\n"
            "  AUTHOR: implementer\n"
            "  OWNS: src/foo.py\n"
        )
        ledger = GateLedger.parse(text)
        issues = GateLinter.lint(ledger)
        # Should have ERROR (not just WARNING) for implementer in strict gate
        assert any(
            i.severity == "ERROR" and "AUTHOR: implementer" in i.message and i.gate_id == "G1"
            for i in issues
        )

    def test_standard_gate_in_standard_ledger_implementer_is_warning(self):
        """Without GATE_MODE override, AUTHOR: implementer is WARNING in standard mode."""
        text = (
            "MODE: standard\n"
            "- [ ] G1: Test\n"
            "  CHECK: echo ok\n"
            "  EXPECT: ok\n"
            "  AUTHOR: implementer\n"
            "  OWNS: src/foo.py\n"
        )
        ledger = GateLedger.parse(text)
        issues = GateLinter.lint(ledger)
        author_issues = [i for i in issues if "AUTHOR: implementer" in i.message]
        assert len(author_issues) == 1
        assert author_issues[0].severity == "WARNING"

    def test_multiple_gates_mixed_modes(self):
        """Mix of gates with different GATE_MODE overrides."""
        text = (
            "MODE: standard\n"
            "- [x] G1: Quick gate\n"
            "  CHECK: echo fast\n"
            "  EXPECT: fast\n"
            "  GATE_MODE: quick\n"
            "  AUTHOR: external\n"
            "  OWNS: src/a.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='fast'\n"
            "\n"
            "- [x] G2: Strict gate\n"
            "  CHECK: echo critical\n"
            "  EXPECT: critical\n"
            "  GATE_MODE: strict\n"
            "  AUTHOR: external\n"
            "  OWNS: src/b.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='critical' mutation_tested=true\n"
            "\n"
            "- [x] G3: Standard gate\n"
            "  CHECK: echo normal\n"
            "  EXPECT: normal\n"
            "  AUTHOR: external\n"
            "  OWNS: src/c.py\n"
            "  EVIDENCE: exit_code=0 timestamp=2026-01-01T00:00:00Z match='normal'\n"
        )
        ledger = GateLedger.parse(text)
        assert ledger.gates["G1"].gate_mode == "quick"
        assert ledger.gates["G2"].gate_mode == "strict"
        assert ledger.gates["G3"].gate_mode is None

        guard = CompletionGuard(ledger=ledger)
        decision = guard.evaluate()
        # G2 has mutation_tested=true so should pass
        assert decision.decision == "allow"
