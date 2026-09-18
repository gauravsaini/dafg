"""Tests for HandoffReport and PersonaVerdict dataclasses."""

import pytest
from dafg.organism import HandoffReport, PersonaVerdict


class TestHandoffReportToMarkdown:
    """Verify HandoffReport.to_markdown() produces valid structured markdown."""

    def _make_report(self, **overrides):
        defaults = dict(
            persona_id="P-reviewer-G1",
            archetype="reviewer",
            observation="All gates inspected",
            logic_chain=["Step 1: parsed ledger", "Step 2: executed checks"],
            caveats=["Flaky network test skipped"],
            conclusion="Everything checks out",
            verdict="APPROVE",
            verification_commands=["echo success", "pytest tests/"],
        )
        defaults.update(overrides)
        return HandoffReport(**defaults)

    def test_markdown_contains_observation(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "## Observation" in md
        assert "All gates inspected" in md

    def test_markdown_contains_logic_chain(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "## Logic Chain" in md
        assert "1. Step 1: parsed ledger" in md
        assert "2. Step 2: executed checks" in md

    def test_markdown_contains_caveats(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "## Caveats" in md
        assert "- Flaky network test skipped" in md

    def test_markdown_contains_conclusion_and_verdict(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "## Conclusion" in md
        assert "**APPROVE**" in md
        assert "Everything checks out" in md

    def test_markdown_contains_verification_commands(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "## Verification Method" in md
        assert "```bash" in md
        assert "echo success" in md
        assert "pytest tests/" in md

    def test_markdown_header_includes_archetype_and_persona_id(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "# Handoff Report — Reviewer (P-reviewer-G1)" in md

    def test_markdown_omits_caveats_section_when_empty(self):
        report = self._make_report(caveats=[])
        md = report.to_markdown()
        assert "## Caveats" not in md

    def test_markdown_omits_verification_when_empty(self):
        report = self._make_report(verification_commands=[])
        md = report.to_markdown()
        assert "## Verification Method" not in md
        assert "```bash" not in md

    def test_markdown_all_sections_present(self):
        """Complete report has all required sections."""
        report = self._make_report()
        md = report.to_markdown()
        required_sections = [
            "# Handoff Report",
            "## Observation",
            "## Logic Chain",
            "## Caveats",
            "## Conclusion",
            "## Verification Method",
        ]
        for section in required_sections:
            assert section in md, f"Missing section: {section}"


class TestHandoffReportToDict:
    """Verify HandoffReport.to_dict() round-trips correctly."""

    def test_to_dict_contains_all_fields(self):
        report = HandoffReport(
            persona_id="P-auditor-G1",
            archetype="auditor",
            observation="Fresh audit",
            logic_chain=["Verified all gates"],
            caveats=[],
            conclusion="Clean",
            verdict="CLEAN",
        )
        d = report.to_dict()
        assert d["persona_id"] == "P-auditor-G1"
        assert d["archetype"] == "auditor"
        assert d["observation"] == "Fresh audit"
        assert d["logic_chain"] == ["Verified all gates"]
        assert d["caveats"] == []
        assert d["conclusion"] == "Clean"
        assert d["verdict"] == "CLEAN"
        assert "timestamp" in d
        assert d["metadata"] == {}
        assert d["verification_commands"] == []

    def test_to_dict_preserves_metadata(self):
        report = HandoffReport(
            persona_id="P1",
            archetype="explorer",
            observation="obs",
            logic_chain=[],
            caveats=[],
            conclusion="done",
            verdict="APPROVE",
            metadata={"gate_results": {"G1": "pass"}},
        )
        d = report.to_dict()
        assert d["metadata"] == {"gate_results": {"G1": "pass"}}

    def test_to_dict_round_trip_fields(self):
        """All fields survive serialization to dict."""
        report = HandoffReport(
            persona_id="P-challenger-G2",
            archetype="challenger",
            observation="Stress tested",
            logic_chain=["step1", "step2"],
            caveats=["minor issue"],
            conclusion="Passed stress",
            verdict="APPROVE",
            verification_commands=["echo ok"],
        )
        d = report.to_dict()
        # Reconstruct manually and compare key fields
        assert d["persona_id"] == report.persona_id
        assert d["archetype"] == report.archetype
        assert d["observation"] == report.observation
        assert d["logic_chain"] == report.logic_chain
        assert d["caveats"] == report.caveats
        assert d["conclusion"] == report.conclusion
        assert d["verdict"] == report.verdict
        assert d["verification_commands"] == report.verification_commands


class TestPersonaVerdict:
    """Verify PersonaVerdict stores verdict and gate results correctly."""

    def test_stores_verdict_and_gate_results(self):
        handoff = HandoffReport(
            persona_id="P-reviewer-G1",
            archetype="reviewer",
            observation="checked",
            logic_chain=["ran checks"],
            caveats=[],
            conclusion="all good",
            verdict="APPROVE",
        )
        pv = PersonaVerdict(
            archetype="reviewer",
            persona_id="P-reviewer-G1",
            verdict="APPROVE",
            gate_ids=["G1", "G2"],
            handoff=handoff,
            gate_results={"G1": "pass", "G2": "pass"},
        )
        assert pv.archetype == "reviewer"
        assert pv.persona_id == "P-reviewer-G1"
        assert pv.verdict == "APPROVE"
        assert pv.gate_ids == ["G1", "G2"]
        assert pv.gate_results == {"G1": "pass", "G2": "pass"}
        assert pv.handoff is handoff

    def test_default_gate_results_is_empty(self):
        handoff = HandoffReport(
            persona_id="P1",
            archetype="auditor",
            observation="obs",
            logic_chain=[],
            caveats=[],
            conclusion="done",
            verdict="CLEAN",
        )
        pv = PersonaVerdict(
            archetype="auditor",
            persona_id="P1",
            verdict="CLEAN",
            gate_ids=["G1"],
            handoff=handoff,
        )
        assert pv.gate_results == {}

    def test_reject_verdict(self):
        handoff = HandoffReport(
            persona_id="P-challenger-G3",
            archetype="challenger",
            observation="failure found",
            logic_chain=["gate failed"],
            caveats=["G3 failed"],
            conclusion="rejected",
            verdict="REJECT",
        )
        pv = PersonaVerdict(
            archetype="challenger",
            persona_id="P-challenger-G3",
            verdict="REJECT",
            gate_ids=["G3"],
            handoff=handoff,
            gate_results={"G3": "fail"},
        )
        assert pv.verdict == "REJECT"
        assert pv.gate_results["G3"] == "fail"
