"""Tests for CompletionGuard and Stop Hook."""

import subprocess
import pytest
from dafg.gates import ApprovalStore, Gate, GateLedger
from dafg.hook import CompletionGuard, StopDecision


def test_stop_hook_blocks_when_gates_pending():
    text = """
- [ ] G1: First gate
  CHECK: echo 1
  EXPECT: 1

- [x] G2: Second gate
  CHECK: echo 2
  EXPECT: 2
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='2'
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()

    assert not decision.allowed
    assert decision.decision == "block"
    assert "G1" in decision.pending_gates
    assert "Completion blocked" in decision.reason


def test_stop_hook_blocks_when_evidence_missing_on_checked_gate():
    text = """
- [x] G1: Marked checked without evidence
  CHECK: echo 1
  EXPECT: 1
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()

    assert not decision.allowed
    assert decision.decision == "block"
    assert "G1" in decision.unverified_gates


def test_stop_hook_blocks_unapproved_commands():
    text = """
- [x] G1: Gate with unapproved command
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='1'
"""
    ledger = GateLedger.parse(text)
    store = ApprovalStore()
    # G1 is not approved in store
    guard = CompletionGuard(ledger=ledger, approval_store=store)
    decision = guard.evaluate()

    assert not decision.allowed
    assert decision.decision == "block"
    assert "G1" in decision.unapproved_gates


def test_stop_hook_allows_when_all_met_with_evidence():
    text = """
- [x] G1: First gate
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='1'

- [x] G2: Second gate
  CHECK: echo 2
  EXPECT: 2
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='2'
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()

    assert decision.allowed
    assert decision.decision == "allow"
    assert "All acceptance gates are met" in decision.reason


def test_stop_hook_allows_validly_abandoned_gates():
    text = """
- [x] G1: First gate
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='1'

- [-] G2: Dropped gate
  ABANDON: Not needed for this release
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()

    assert decision.allowed
    assert decision.decision == "allow"
    assert "G2" in decision.abandoned_gates


def test_stop_hook_blocks_empty_abandonment_reason():
    text = """
- [-] G1: Abandoned with empty reason
  ABANDON:    
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()

    assert not decision.allowed
    assert decision.decision == "block"
    assert "abandoned without reason" in decision.reason


def test_progress_guard_releases_after_stagnation(tmp_path):
    text = """
- [ ] G1: Pending gate
  CHECK: echo 1
  EXPECT: 1
"""
    ledger = GateLedger.parse(text)
    state_file = tmp_path / "hook_state.json"
    guard = CompletionGuard(
        ledger=ledger,
        state_file=state_file,
        max_stagnant_blocks=3,
    )

    # Attempts 1, 2 should block
    d1 = guard.evaluate()
    assert d1.decision == "block"
    d2 = guard.evaluate()
    assert d2.decision == "block"

    # Attempt 3 reaches threshold 3 -> progress guard releases
    d3 = guard.evaluate()
    assert d3.decision == "allow"
    assert d3.progress_guard_released
    assert "Progress guard released" in d3.reason


def test_cli_stop_hook(tmp_path):
    f = tmp_path / "GATES.md"
    f.write_text("- [ ] G1: Unmet\n  CHECK: echo 1\n  EXPECT: 1\n", encoding="utf-8")

    # Run CLI stop-hook via subprocess: should exit code 1
    cmd = ["python", "-m", "dafg.hook", str(f), "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 1
    assert '"decision": "block"' in proc.stdout


def test_stop_hook_blocks_pending_evidence():
    text = """
- [x] G1: Checked gate with pending evidence
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: pending
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()

    assert not decision.allowed
    assert decision.decision == "block"
    assert "G1" in decision.unverified_gates


def test_stop_hook_blocks_failed_exit_code_in_evidence():
    text = """
- [x] G1: Checked gate with failing exit code in evidence
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=1 match='failed'
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()

    assert not decision.allowed
    assert decision.decision == "block"
    assert "G1" in decision.unverified_gates


def test_cli_dafg_subcommands(tmp_path):
    f = tmp_path / "GATES.md"
    f.write_text("""# Test
- [ ] G1: Check
  CHECK: python -c "print('hello')"
  EXPECT: hello
""", encoding="utf-8")

    # Test dafg gates --lint
    res_lint = subprocess.run(
        ["python", "-m", "dafg.cli", "gates", "--lint", str(f)],
        capture_output=True,
        text=True,
    )
    assert res_lint.returncode == 0
    assert "Ledger lint passed" in res_lint.stdout

    # Test dafg stop-hook
    res_hook = subprocess.run(
        ["python", "-m", "dafg.cli", "stop-hook", str(f), "--json"],
        capture_output=True,
        text=True,
    )
    assert res_hook.returncode == 1
    assert '"decision": "block"' in res_hook.stdout

    # Test dfag.py entrypoint shim
    res_dfag = subprocess.run(
        ["python", "dfag.py", "gates", "--lint", str(f)],
        capture_output=True,
        text=True,
    )
    assert res_dfag.returncode == 0
    assert "Ledger lint passed" in res_dfag.stdout


def test_stop_hook_blocks_on_duplicate_ids():
    text = """
- [x] G1: First
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='1'

- [x] G1: Duplicate G1
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='1'
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()
    assert decision.allowed is False
    assert "duplicate gate IDs detected" in decision.reason


def test_stop_hook_blocks_on_syntax_errors():
    text = """
- [x] G1: First
  CHECK: echo 1
  EXPECT: 1
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='1'

- [] G2: Malformed empty bracket
  CHECK: echo 2
  EXPECT: 2
"""
    ledger = GateLedger.parse(text)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()
    assert decision.allowed is False
    assert "syntax errors in gate ledger" in decision.reason


def test_stop_hook_allows_manual_gate_without_check_in_approval_store():
    text = """
- [x] G_manual: Manual visual check
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='verified manually'
"""
    ledger = GateLedger.parse(text)
    store = ApprovalStore()  # empty approval store
    guard = CompletionGuard(ledger=ledger, approval_store=store)
    decision = guard.evaluate()
    assert decision.allowed is True
    assert decision.decision == "allow"


def test_cli_dafg_run(tmp_path):
    gates_file = tmp_path / "GATES.md"
    gates_file.write_text("""
- [ ] G1: First check
  CHECK: python -c "print('hello from dafg')"
  EXPECT: hello from dafg
""", encoding="utf-8")
    state_file = tmp_path / "state.json"

    res = subprocess.run(
        [
            "python", "-m", "dafg.cli", "run",
            "--gates", str(gates_file),
            "--state", str(state_file),
            "--auto-approve",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "DAFG run status: COMPLETED" in res.stdout
    assert state_file.exists()


def test_stop_hook_blocks_on_tautological_expect_and_lint_errors():
    """CompletionGuard must block completion if gates have tautological regex or empty titles."""
    text_tautological = """
- [x] G1: Tautological gate
  CHECK: echo ok
  EXPECT: .*
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='ok'
"""
    ledger = GateLedger.parse(text_tautological)
    guard = CompletionGuard(ledger=ledger)
    decision = guard.evaluate()
    assert decision.allowed is False
    assert decision.decision == "block"
    assert "tautological EXPECT pattern" in decision.reason

    text_broken_regex = """
- [x] G1: Broken regex gate
  CHECK: echo ok
  EXPECT: [unclosed
  EVIDENCE: exit_code=0 timestamp=2026-09-10T00:00:00Z match='ok'
"""
    ledger2 = GateLedger.parse(text_broken_regex)
    guard2 = CompletionGuard(ledger=ledger2)
    decision2 = guard2.evaluate()
    assert decision2.allowed is False
    assert "invalid regex pattern" in decision2.reason


def test_stop_hook_blocks_unapproved_commands_on_unmet_gates():
    """Unapproved commands on unmet gates must be surfaced in decision.unapproved_gates."""
    text = """
- [ ] G1: Unmet and unapproved
  CHECK: echo sensitive
  EXPECT: sensitive
"""
    ledger = GateLedger.parse(text)
    store = ApprovalStore()
    guard = CompletionGuard(ledger=ledger, approval_store=store)
    decision = guard.evaluate()
    assert decision.allowed is False
    assert "G1" in decision.unapproved_gates
    assert "G1" in decision.pending_gates


