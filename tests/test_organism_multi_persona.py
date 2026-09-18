"""Tests for AutonomousOrganism multi-persona adversarial gate iteration integration."""

import json
from pathlib import Path
import pytest

from dafg.organism import AutonomousOrganism
from dafg.persona import PersonaArchetype


def test_autonomous_organism_multi_persona_init(tmp_path: Path):
    """Verify AutonomousOrganism accepts multi_persona flag and defaults to False."""
    org_default = AutonomousOrganism(goal="Build a cache", workdir=tmp_path / "default")
    assert org_default.multi_persona is False
    assert org_default.derived_archetypes == []

    org_multi = AutonomousOrganism(
        goal="Build a cache",
        workdir=tmp_path / "multi",
        multi_persona=True,
    )
    assert org_multi.multi_persona is True
    assert org_multi.derived_archetypes == []


def test_bootstrap_genesis_populates_derived_archetypes(tmp_path: Path):
    """Verify bootstrap_genesis populates derived_archetypes using ArchetypeDeriver."""
    workdir = tmp_path / "genesis_test"
    org = AutonomousOrganism(
        goal="Build a high performance Redis key-value store with caching",
        workdir=workdir,
        multi_persona=True,
    )
    manifest, ledger, graph = org.bootstrap_genesis()

    assert len(org.derived_archetypes) > 0
    archetypes = [arch for arch, _ in org.derived_archetypes]
    assert PersonaArchetype.WORKER in archetypes
    assert PersonaArchetype.REVIEWER in archetypes
    # Since synthesized gates have OWNS, EXPLORER should be included
    assert PersonaArchetype.EXPLORER in archetypes


def test_evolve_to_completion_with_multi_persona(tmp_path: Path):
    """Verify evolve_to_completion in multi_persona mode runs gate iteration loop and victory audit."""
    workdir = tmp_path / "evolve_multi"
    org = AutonomousOrganism(
        goal="Build a minimal in-memory key-value store",
        workdir=workdir,
        max_generations=1,
        auto_approve=True,
        multi_persona=True,
    )
    lineage = org.evolve_to_completion()

    assert lineage is not None
    # Verify lineage.json persisted with multi_persona info
    lineage_file = workdir / "lineage.json"
    assert lineage_file.exists()
    data = json.loads(lineage_file.read_text(encoding="utf-8"))
    assert data.get("multi_persona") is True
    assert "derived_archetypes" in data
    assert len(data["derived_archetypes"]) > 0

    # Verify iteration handoff reports were written
    iterations_dir = workdir / "iterations" / "gen_1"
    assert iterations_dir.exists()
    handoff_files = list(iterations_dir.glob("*.md"))
    assert len(handoff_files) > 0

    # Verify dashboard output mentions Multi-Persona: Active
    dashboard = org.format_lineage_dashboard()
    assert "Multi-Persona: Active" in dashboard


def test_cli_multi_persona_flag(tmp_path: Path):
    """Verify CLI --multi-persona flag passes to AutonomousOrganism and executes cleanly."""
    from dafg.cli import main

    workdir = tmp_path / "cli_multi"
    exit_code = main([
        "organism",
        "--goal", "Build a minimal dictionary store",
        "--workdir", str(workdir),
        "--generations", "1",
        "--auto-approve",
        "--multi-persona",
        "--json",
    ])
    # The organism runs 1 generation and exits (either 0 if converged or 1 if not yet converged)
    assert exit_code in (0, 1)

    lineage_file = workdir / "lineage.json"
    assert lineage_file.exists()
    data = json.loads(lineage_file.read_text(encoding="utf-8"))
    assert data.get("multi_persona") is True
