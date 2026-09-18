"""Tests for PersonaArchetype enum, archetype factory methods, and ArchetypeDeriver."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from dafg.persona import (
    ArchetypeDeriver,
    PersonaArchetype,
    PersonaCompiler,
    PersonaProfile,
)


# ---------------------------------------------------------------------------
# Helpers — lightweight stubs for task and ledger objects
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str = "T1",
    title: str = "Implement feature",
    role: str = "Developer",
    assigned_gates: Optional[List[str]] = None,
    owns: Optional[List[str]] = None,
) -> SimpleNamespace:
    """Create a minimal task-like object for testing."""
    return SimpleNamespace(
        id=task_id,
        title=title,
        role=role,
        assigned_gates=assigned_gates or [],
        owns=owns or [],
    )


def _make_gate(
    gate_id: str = "G1",
    title: str = "Gate",
    check: Optional[str] = None,
    owns: Optional[str] = None,
    author: Optional[str] = None,
) -> SimpleNamespace:
    """Create a minimal gate-like object for testing."""
    return SimpleNamespace(
        id=gate_id,
        title=title,
        check=check,
        owns=owns,
        author=author,
    )


def _make_ledger(
    gates: Optional[Dict[str, Any]] = None,
    mode: str = "standard",
    abandon_threshold: Optional[float] = None,
) -> SimpleNamespace:
    """Create a minimal ledger-like object for testing."""
    return SimpleNamespace(
        gates=gates or {},
        mode=mode,
        abandon_threshold=abandon_threshold,
    )


# ===========================================================================
# 1. PersonaArchetype enum
# ===========================================================================


class TestPersonaArchetypeEnum:
    """Verify the PersonaArchetype enum has all expected members."""

    def test_has_all_five_values(self) -> None:
        expected = {"explorer", "worker", "reviewer", "challenger", "auditor"}
        actual = {member.value for member in PersonaArchetype}
        assert actual == expected

    def test_is_string_enum(self) -> None:
        for member in PersonaArchetype:
            assert isinstance(member, str)
            assert member == member.value

    def test_enum_member_names(self) -> None:
        names = {member.name for member in PersonaArchetype}
        assert names == {"EXPLORER", "WORKER", "REVIEWER", "CHALLENGER", "AUDITOR"}


# ===========================================================================
# 2. Archetype factory methods on PersonaCompiler
# ===========================================================================


class TestCompileExplorer:
    """Tests for PersonaCompiler.compile_explorer."""

    def test_returns_persona_profile(self) -> None:
        compiler = PersonaCompiler()
        task = _make_task()
        profile = compiler.compile_explorer(task)
        assert isinstance(profile, PersonaProfile)

    def test_persona_id_contains_explorer(self) -> None:
        compiler = PersonaCompiler()
        task = _make_task(task_id="T42")
        profile = compiler.compile_explorer(task)
        assert "explorer" in profile.persona_id
        assert "T42" in profile.persona_id

    def test_role_is_explorer(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_explorer(_make_task())
        assert profile.role == "Explorer"

    def test_review_focus_has_explorer_items(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_explorer(_make_task())
        assert "missing dependencies" in profile.review_focus
        assert "architectural boundaries" in profile.review_focus
        assert "hidden coupling" in profile.review_focus

    def test_method_has_survey_steps(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_explorer(_make_task())
        assert "Survey owned files and their imports" in profile.method
        assert "Map dependency graph" in profile.method

    def test_metadata_contains_archetype(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_explorer(_make_task())
        assert profile.metadata["archetype"] == "explorer"


class TestCompileWorker:
    """Tests for PersonaCompiler.compile_worker — delegates to compile()."""

    def test_returns_persona_profile(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_worker(_make_task())
        assert isinstance(profile, PersonaProfile)

    def test_metadata_contains_worker_archetype(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_worker(_make_task())
        assert profile.metadata["archetype"] == "worker"

    def test_persona_id_contains_worker(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_worker(_make_task(task_id="T7"), attempt=3)
        assert "worker" in profile.persona_id
        assert "T7" in profile.persona_id
        assert "v3" in profile.persona_id

    def test_previous_feedback_is_threaded(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_worker(
            _make_task(), previous_feedback="Fix the import"
        )
        assert any("Fix the import" in step for step in profile.method)


class TestCompileReviewer:
    """Tests for PersonaCompiler.compile_reviewer."""

    def test_returns_persona_profile(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_reviewer(_make_task())
        assert isinstance(profile, PersonaProfile)

    def test_review_focus_has_reviewer_items(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_reviewer(_make_task())
        assert "off-by-one errors" in profile.review_focus
        assert "error handling gaps" in profile.review_focus
        assert "API contract violations" in profile.review_focus
        assert "missing edge cases" in profile.review_focus

    def test_expertise_includes_code_review(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_reviewer(_make_task())
        assert "code review" in profile.expertise
        assert "correctness analysis" in profile.expertise

    def test_method_has_review_steps(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_reviewer(_make_task())
        assert "Read implementation against specification" in profile.method
        assert "Trace error paths" in profile.method
        assert "Verify interface contracts" in profile.method

    def test_metadata_contains_archetype(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_reviewer(_make_task())
        assert profile.metadata["archetype"] == "reviewer"


class TestCompileChallenger:
    """Tests for PersonaCompiler.compile_challenger."""

    def test_returns_persona_profile(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_challenger(_make_task())
        assert isinstance(profile, PersonaProfile)

    def test_review_focus_has_challenger_items(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_challenger(_make_task())
        assert "concurrency races" in profile.review_focus
        assert "resource exhaustion" in profile.review_focus
        assert "boundary inputs" in profile.review_focus
        assert "error injection" in profile.review_focus

    def test_expertise_includes_adversarial(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_challenger(_make_task())
        assert "adversarial testing" in profile.expertise
        assert "concurrency analysis" in profile.expertise

    def test_method_has_stress_steps(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_challenger(_make_task())
        assert "Design adversarial test scenarios" in profile.method
        assert "Stress test with concurrent load" in profile.method
        assert "Inject faults and verify recovery" in profile.method

    def test_metadata_contains_archetype(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_challenger(_make_task())
        assert profile.metadata["archetype"] == "challenger"


class TestCompileAuditor:
    """Tests for PersonaCompiler.compile_auditor."""

    def test_returns_persona_profile(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_auditor(_make_task())
        assert isinstance(profile, PersonaProfile)

    def test_review_focus_has_auditor_items(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_auditor(_make_task())
        assert "test adequacy" in profile.review_focus
        assert "evidence authenticity" in profile.review_focus
        assert "gate coverage gaps" in profile.review_focus

    def test_expertise_includes_forensic(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_auditor(_make_task())
        assert "forensic auditing" in profile.expertise
        assert "evidence verification" in profile.expertise

    def test_method_has_audit_steps(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_auditor(_make_task())
        assert "Independently run all verification commands" in profile.method
        assert "Cross-reference evidence with source" in profile.method
        assert "Verify no fabricated or stub artifacts" in profile.method

    def test_metadata_contains_archetype(self) -> None:
        compiler = PersonaCompiler()
        profile = compiler.compile_auditor(_make_task())
        assert profile.metadata["archetype"] == "auditor"


# ===========================================================================
# 3. compile_for_archetype dispatch
# ===========================================================================


class TestCompileForArchetype:
    """Tests for PersonaCompiler.compile_for_archetype dispatch."""

    @pytest.mark.parametrize(
        "archetype,expected_role",
        [
            (PersonaArchetype.EXPLORER, "Explorer"),
            (PersonaArchetype.REVIEWER, "Reviewer"),
            (PersonaArchetype.CHALLENGER, "Challenger"),
            (PersonaArchetype.AUDITOR, "Auditor"),
        ],
    )
    def test_dispatches_to_correct_archetype(
        self, archetype: PersonaArchetype, expected_role: str
    ) -> None:
        compiler = PersonaCompiler()
        task = _make_task()
        profile = compiler.compile_for_archetype(archetype, task)
        assert profile.role == expected_role
        assert profile.metadata["archetype"] == archetype.value

    def test_dispatches_worker(self) -> None:
        compiler = PersonaCompiler()
        task = _make_task()
        profile = compiler.compile_for_archetype(PersonaArchetype.WORKER, task)
        assert profile.metadata["archetype"] == "worker"

    def test_worker_passes_feedback_and_attempt(self) -> None:
        compiler = PersonaCompiler()
        task = _make_task()
        profile = compiler.compile_for_archetype(
            PersonaArchetype.WORKER,
            task,
            previous_feedback="Needs retry",
            attempt=2,
        )
        assert "v2" in profile.persona_id
        assert any("Needs retry" in step for step in profile.method)

    def test_raises_on_unknown_archetype(self) -> None:
        compiler = PersonaCompiler()
        task = _make_task()
        with pytest.raises(ValueError, match="Unknown archetype"):
            compiler.compile_for_archetype("bogus", task)  # type: ignore[arg-type]


# ===========================================================================
# 4. ArchetypeDeriver.from_ledger
# ===========================================================================


class TestArchetypeDeriver:
    """Tests for ArchetypeDeriver.from_ledger signal-based derivation."""

    @staticmethod
    def _archetypes(result: list) -> set:
        """Extract the set of archetype enums from from_ledger output."""
        return {arch for arch, _ in result}

    def test_always_includes_worker_and_reviewer(self) -> None:
        ledger = _make_ledger()
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.WORKER in archetypes
        assert PersonaArchetype.REVIEWER in archetypes

    def test_includes_explorer_when_gates_have_owns(self) -> None:
        gates = {
            "G1": _make_gate("G1", owns="src/module.py"),
            "G2": _make_gate("G2"),
        }
        ledger = _make_ledger(gates=gates)
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.EXPLORER in archetypes
        # Context should reference the gate with owns
        explorer_ctx = next(ctx for a, ctx in result if a == PersonaArchetype.EXPLORER)
        assert "G1" in explorer_ctx["gate_ids"]

    def test_excludes_explorer_when_no_owns(self) -> None:
        gates = {"G1": _make_gate("G1"), "G2": _make_gate("G2")}
        ledger = _make_ledger(gates=gates)
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.EXPLORER not in archetypes

    def test_includes_challenger_when_check_has_pytest(self) -> None:
        gates = {
            "G1": _make_gate("G1", check="uv run pytest tests/ -v"),
        }
        ledger = _make_ledger(gates=gates)
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.CHALLENGER in archetypes

    def test_includes_challenger_when_check_has_test(self) -> None:
        gates = {
            "G1": _make_gate("G1", check="python -m unittest test_foo"),
        }
        ledger = _make_ledger(gates=gates)
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.CHALLENGER in archetypes

    def test_excludes_challenger_when_no_test_commands(self) -> None:
        gates = {"G1": _make_gate("G1", check="echo hello")}
        ledger = _make_ledger(gates=gates)
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.CHALLENGER not in archetypes

    def test_includes_auditor_when_mode_is_strict(self) -> None:
        ledger = _make_ledger(mode="strict")
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.AUDITOR in archetypes

    def test_excludes_auditor_when_mode_is_standard(self) -> None:
        gates = {"G1": _make_gate("G1", check="echo ok")}
        ledger = _make_ledger(gates=gates, mode="standard")
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.AUDITOR not in archetypes

    def test_includes_auditor_when_author_is_implementer(self) -> None:
        gates = {
            "G1": _make_gate("G1", author="implementer"),
        }
        ledger = _make_ledger(gates=gates)
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.AUDITOR in archetypes
        auditor_ctx = next(ctx for a, ctx in result if a == PersonaArchetype.AUDITOR)
        assert "G1" in auditor_ctx["gate_ids"]

    def test_includes_auditor_when_abandon_threshold_set(self) -> None:
        ledger = _make_ledger(abandon_threshold=0.3)
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert PersonaArchetype.AUDITOR in archetypes

    def test_no_duplicate_archetypes(self) -> None:
        """Even when multiple signals fire for AUDITOR, it appears only once."""
        gates = {
            "G1": _make_gate("G1", author="implementer"),
        }
        ledger = _make_ledger(gates=gates, mode="strict", abandon_threshold=0.5)
        result = ArchetypeDeriver.from_ledger(ledger)
        archetype_list = [a for a, _ in result]
        assert len(archetype_list) == len(set(archetype_list))

    def test_returns_list_of_tuples(self) -> None:
        ledger = _make_ledger()
        result = ArchetypeDeriver.from_ledger(ledger)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], PersonaArchetype)
            assert isinstance(item[1], dict)
            assert "gate_ids" in item[1]

    def test_combined_signals(self) -> None:
        """Full scenario: owns, test check, strict mode → all 5 archetypes."""
        gates = {
            "G1": _make_gate("G1", owns="src/foo.py", check="uv run pytest"),
            "G2": _make_gate("G2", author="implementer"),
        }
        ledger = _make_ledger(gates=gates, mode="strict")
        result = ArchetypeDeriver.from_ledger(ledger)
        archetypes = self._archetypes(result)
        assert archetypes == {
            PersonaArchetype.EXPLORER,
            PersonaArchetype.WORKER,
            PersonaArchetype.REVIEWER,
            PersonaArchetype.CHALLENGER,
            PersonaArchetype.AUDITOR,
        }
