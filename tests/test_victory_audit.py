"""Tests for VictoryAudit fresh-context convergence gate."""

import pytest
from pathlib import Path

from dafg.gates import Gate, GateEngine, GateLedger
from dafg.organism import VictoryAudit, HandoffReport


def _make_ledger(text: str) -> GateLedger:
    """Parse a GATES.md-style string into a GateLedger."""
    return GateLedger.parse(text)


class TestVictoryAuditClean:
    """VictoryAudit.audit() returns CLEAN when all gates pass."""

    def test_all_passing_returns_clean(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
            "- [ ] G2: Another check\n"
            "  CHECK: echo hello\n"
            "  EXPECT: hello\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        audit = VictoryAudit(ledger=ledger, engine=engine, workdir=tmp_path)
        report = audit.audit()

        assert report.verdict == "CLEAN"
        assert report.archetype == "auditor"
        assert "All gates independently verified" in report.conclusion

    def test_clean_report_has_verification_commands(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        audit = VictoryAudit(ledger=ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        report = audit.audit()

        assert "echo success" in report.verification_commands

    def test_clean_report_gate_results_in_metadata(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        audit = VictoryAudit(ledger=ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        report = audit.audit()

        assert report.metadata["gate_results"]["G1"] == "pass"


class TestVictoryAuditDirty:
    """VictoryAudit.audit() returns DIRTY when any gate fails."""

    def test_failing_gate_returns_dirty(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
            "- [ ] G2: Failing check\n"
            "  CHECK: echo wrong\n"
            "  EXPECT: right\n"
        )
        ledger = _make_ledger(text)
        engine = GateEngine(auto_approve=True)
        audit = VictoryAudit(ledger=ledger, engine=engine, workdir=tmp_path)
        report = audit.audit()

        assert report.verdict == "DIRTY"
        assert "gate failures" in report.conclusion.lower()

    def test_dirty_report_has_caveats(self, tmp_path):
        text = (
            "- [ ] G1: Failing check\n"
            "  CHECK: echo wrong\n"
            "  EXPECT: right\n"
        )
        ledger = _make_ledger(text)
        audit = VictoryAudit(ledger=ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        report = audit.audit()

        assert len(report.caveats) > 0
        assert any("G1" in c for c in report.caveats)

    def test_dirty_report_marks_failed_gate_in_metadata(self, tmp_path):
        text = (
            "- [ ] G1: Failing check\n"
            "  CHECK: echo wrong\n"
            "  EXPECT: right\n"
        )
        ledger = _make_ledger(text)
        audit = VictoryAudit(ledger=ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        report = audit.audit()

        assert report.metadata["gate_results"]["G1"] == "fail"


class TestVictoryAuditHandoffFile:
    """VictoryAudit writes handoff.md to workdir."""

    def test_writes_handoff_md(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        audit = VictoryAudit(ledger=ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        audit.audit()

        handoff_file = tmp_path / "victory_audit" / "handoff.md"
        assert handoff_file.exists()
        content = handoff_file.read_text(encoding="utf-8")
        assert "# Handoff Report" in content
        assert "Auditor" in content

    def test_handoff_md_contains_verdict(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        audit = VictoryAudit(ledger=ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        audit.audit()

        handoff_file = tmp_path / "victory_audit" / "handoff.md"
        content = handoff_file.read_text(encoding="utf-8")
        assert "**CLEAN**" in content


class TestVictoryAuditArchetype:
    """Victory audit handoff report has correct archetype."""

    def test_archetype_is_auditor(self, tmp_path):
        text = (
            "- [ ] G1: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        audit = VictoryAudit(ledger=ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        report = audit.audit()
        assert report.archetype == "auditor"
        assert report.persona_id == "victory-auditor"


class TestVictoryAuditAbandonedGates:
    """Abandoned gates are skipped during audit."""

    def test_abandoned_gates_skipped(self, tmp_path):
        text = (
            "- [-] G1: Abandoned gate\n"
            "  ABANDON: not needed\n"
            "  CHECK: echo fail\n"
            "  EXPECT: fail\n"
            "- [ ] G2: Echo check\n"
            "  CHECK: echo success\n"
            "  EXPECT: success\n"
        )
        ledger = _make_ledger(text)
        audit = VictoryAudit(ledger=ledger, engine=GateEngine(auto_approve=True), workdir=tmp_path)
        report = audit.audit()

        assert report.verdict == "CLEAN"
        assert report.metadata["gate_results"]["G1"] == "abandoned"
        assert report.metadata["gate_results"]["G2"] == "pass"
