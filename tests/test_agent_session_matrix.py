"""Tests for empirical agent session matrix aggregation."""
from pathlib import Path
import pytest

from scripts.run_agent_session_matrix import AgentSessionMatrix


def test_agent_session_matrix_analysis():
    report = AgentSessionMatrix.analyze_sessions()
    groups = report["groups"]

    assert "raw_llm_agent_sessions" in groups
    assert "autonomous_organism_runs" in groups

    llm_grp = groups["raw_llm_agent_sessions"]
    org_grp = groups["autonomous_organism_runs"]

    assert llm_grp["sample_size"] == 3
    assert org_grp["sample_size"] == 2

    # Verify real empirical variance in raw LLM sessions
    assert llm_grp["domain_deferrals"]["std_dev"] > 0.0
    assert llm_grp["avg_concurrency_ratio"]["std_dev"] > 0.0
    assert llm_grp["domain_deferrals"]["min_val"] == 3.0
    assert llm_grp["domain_deferrals"]["max_val"] == 28.0

    # Verify organism zero-domain-deferrals
    assert org_grp["domain_deferrals"]["mean"] == 0.0

    # Verify markdown rendering
    md = AgentSessionMatrix.render_markdown(report)
    assert "# DAFG Empirical Agent Session Matrix Report" in md
    assert "| `raw_llm_agent_sessions` |" in md
    assert "| `autonomous_organism_runs` |" in md
