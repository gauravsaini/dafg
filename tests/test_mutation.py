from __future__ import annotations
import ast
import os
import sys
from pathlib import Path
import pytest

from dafg.mutation import (
    GateMutator,
    MutationStrategy,
    MutationResult,
    AdequacyReport,
)
from dafg.gates import (
    Gate,
    classify_evidence,
    EvidenceStrength,
)


def test_mutation_strategy_enum():
    """Ensure SOURCE_SABOTAGE exists in MutationStrategy enum."""
    assert MutationStrategy.SOURCE_SABOTAGE == "SOURCE_SABOTAGE"
    assert MutationStrategy.SOURCE_SABOTAGE.value == "SOURCE_SABOTAGE"


def test_source_sabotage_genuine_kill(tmp_path: Path):
    """A gate testing genuine module functions must kill the mutant when sabotaged."""
    mod_file = tmp_path / "calc.py"
    mod_content = (
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "def subtract(a: int, b: int) -> int:\n"
        "    return a - b\n"
    )
    mod_file.write_text(mod_content, encoding="utf-8")
    original_bytes = mod_file.read_bytes()

    gate = Gate(
        id="G1",
        title="Test addition and subtraction",
        status="MET",
        check=f'{sys.executable} -c "import calc; assert calc.add(2, 3) == 5; print(\'CALC_OK\')"',
        expect="CALC_OK",
        owns="calc.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='CALC_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    # Mutant must be killed because calc.add raised RuntimeError("MUTATION_SABOTAGE")
    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert result.strategy == MutationStrategy.SOURCE_SABOTAGE
    assert gate.mutation_tested is True

    # File must be safely and exactly restored byte-for-byte
    assert mod_file.read_bytes() == original_bytes

    # Evidence promotion
    strength = classify_evidence(gate)
    assert strength == EvidenceStrength.EXECUTABLE_PROOF


def test_source_sabotage_tautological_survival(tmp_path: Path):
    """A gate with a tautological check (doesn't exercise source code) must survive mutation."""
    mod_file = tmp_path / "dummy.py"
    mod_content = (
        "def important_function():\n"
        "    return 'real_value'\n"
    )
    mod_file.write_text(mod_content, encoding="utf-8")
    original_bytes = mod_file.read_bytes()

    # Tautological check ignores dummy.py entirely
    gate = Gate(
        id="G2",
        title="Tautological verification",
        status="MET",
        check=f'{sys.executable} -c "print(\'ALWAYS_OK\')"',
        expect="ALWAYS_OK",
        owns="dummy.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='ALWAYS_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    # Mutant survived because check succeeded despite source being sabotaged!
    assert result.original_passed is True
    assert result.mutant_passed is True
    assert result.killed is False
    assert gate.mutation_tested is False

    # File restored byte-for-byte
    assert mod_file.read_bytes() == original_bytes

    # Evidence strength remains STRING_MATCH (not promoted to EXECUTABLE_PROOF)
    strength = classify_evidence(gate)
    assert strength == EvidenceStrength.STRING_MATCH


def test_restoration_safety_under_timeout(tmp_path: Path):
    """Harness must guarantee byte-for-byte restoration even if check times out."""
    worker_file = tmp_path / "worker.py"
    worker_content = (
        "def do_work():\n"
        "    return 42\n"
    )
    worker_file.write_text(worker_content, encoding="utf-8")
    original_bytes = worker_file.read_bytes()

    # Command that sleeps longer than mutator timeout
    gate = Gate(
        id="G3",
        title="Timeout check",
        status="MET",
        check=f'{sys.executable} -c "import time; time.sleep(2); print(\'DONE\')"',
        expect="DONE",
        owns="worker.py",
        cwd=str(tmp_path),
    )

    mutator = GateMutator(timeout=0.3)
    # Original evaluate will fail due to timeout -> mutate returns killed=False, original_passed=False
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    assert result.original_passed is False
    assert worker_file.read_bytes() == original_bytes


def test_restoration_safety_under_exception_during_evaluation(tmp_path: Path, monkeypatch):
    """Harness must guarantee byte-for-byte restoration if an exception is raised in evaluate."""
    target_file = tmp_path / "service.py"
    target_content = (
        "def serve():\n"
        "    return True\n"
    )
    target_file.write_text(target_content, encoding="utf-8")
    original_bytes = target_file.read_bytes()

    gate = Gate(
        id="G4",
        title="Exception check",
        status="MET",
        check=f'{sys.executable} -c "import service; print(\'OK\')"',
        expect="OK",
        owns="service.py",
        cwd=str(tmp_path),
    )

    mutator = GateMutator(timeout=5.0)

    # First call to _evaluate passes (original_passed = True)
    # Second call raises unexpected exception
    original_eval = mutator._evaluate
    call_count = 0

    def mock_eval(check, expect, env, cwd):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return True
        raise RuntimeError("Simulated crash during mutant evaluation")

    monkeypatch.setattr(mutator, "_evaluate", mock_eval)

    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    # File must be restored despite exception in mutant evaluation
    assert target_file.read_bytes() == original_bytes
    assert result.killed is False
    assert result.error is not None
    assert "Simulated crash" in (result.error or "")
    assert getattr(gate, "mutation_tested", False) is False


def test_future_imports_and_docstring_syntactic_validity(tmp_path: Path):
    """AST injection on script with from __future__ imports must inject AFTER future imports."""
    script_file = tmp_path / "future_script.py"
    script_content = (
        '"""Module docstring explaining the script."""\n'
        "from __future__ import annotations\n"
        "from __future__ import division\n"
        "import sys\n\n"
        "CONFIG_VAL = 100\n"
        "print(f'CONFIG={CONFIG_VAL}')\n"
    )
    script_file.write_text(script_content, encoding="utf-8")
    original_bytes = script_file.read_bytes()

    # Direct test of _sabotage_file
    mutator = GateMutator(timeout=5.0)
    sabotaged_bytes = mutator._sabotage_file(script_file, original_bytes)
    sabotaged_text = sabotaged_bytes.decode("utf-8")

    # Sabotaged code must be syntactically valid (no SyntaxError about __future__ location)
    tree = ast.parse(sabotaged_text)

    # Verify that from __future__ imports come before any non-docstring code
    future_indices = [
        i for i, stmt in enumerate(tree.body)
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"
    ]
    raise_indices = [
        i for i, stmt in enumerate(tree.body)
        if isinstance(stmt, ast.Raise)
    ]

    assert len(future_indices) == 2
    assert len(raise_indices) >= 1
    # Raise must occur strictly after the last __future__ import
    assert raise_indices[0] > max(future_indices)

    # Gate verification: running python on the sabotaged script must raise RuntimeError, not SyntaxError
    gate = Gate(
        id="G5",
        title="Future script verification",
        status="MET",
        check=f"{sys.executable} future_script.py",
        expect="CONFIG=100",
        owns="future_script.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='CONFIG=100'",
    )

    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True

    # File restored byte-for-byte
    assert script_file.read_bytes() == original_bytes


def test_async_and_class_functions_sabotaged(tmp_path: Path):
    """AST injection must inject sabotage into all FunctionDef and AsyncFunctionDef nodes."""
    mod_file = tmp_path / "async_service.py"
    mod_content = (
        "import asyncio\n\n"
        "class Worker:\n"
        "    def sync_compute(self, x: int) -> int:\n"
        "        return x * 10\n\n"
        "    async def async_fetch(self) -> str:\n"
        "        return 'fetched'\n"
    )
    mod_file.write_text(mod_content, encoding="utf-8")
    original_bytes = mod_file.read_bytes()

    gate = Gate(
        id="G6",
        title="Async class verification",
        status="MET",
        check=f'{sys.executable} -c "from async_service import Worker; assert Worker().sync_compute(5) == 50; print(\'WORKER_OK\')"',
        expect="WORKER_OK",
        owns="async_service.py",
        cwd=str(tmp_path),
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.killed is True
    assert result.mutant_passed is False
    assert mod_file.read_bytes() == original_bytes


def test_multiple_owned_files_restored(tmp_path: Path):
    """Harness must handle comma-separated OWNS files and restore all of them."""
    mod_a = tmp_path / "pkg_a.py"
    mod_b = tmp_path / "pkg_b.py"

    mod_a.write_text("def a(): return 'a'\n", encoding="utf-8")
    mod_b.write_text("def b(): return 'b'\n", encoding="utf-8")

    bytes_a = mod_a.read_bytes()
    bytes_b = mod_b.read_bytes()

    gate = Gate(
        id="G7",
        title="Multi-file verification",
        status="MET",
        check=f'{sys.executable} -c "import pkg_a, pkg_b; assert pkg_a.a() == \'a\' and pkg_b.b() == \'b\'; print(\'BOTH_OK\')"',
        expect="BOTH_OK",
        owns="pkg_a.py, pkg_b.py",
        cwd=str(tmp_path),
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.killed is True
    assert mod_a.read_bytes() == bytes_a
    assert mod_b.read_bytes() == bytes_b


def test_test_file_filtering_prioritizes_source_files(tmp_path: Path):
    """When both source and test files are declared in OWNS, source files are prioritized."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    source_file = src_dir / "core.py"
    source_file.write_text("def run_core(): return 'core_value'\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_core.py"
    test_file.write_text("def test_ok(): assert True\n", encoding="utf-8")

    src_bytes = source_file.read_bytes()
    test_bytes = test_file.read_bytes()

    gate = Gate(
        id="G8",
        title="Prioritization check",
        status="MET",
        check=f'{sys.executable} -c "import sys; sys.path.insert(0, \'src\'); from core import run_core; assert run_core() == \'core_value\'; print(\'OK\')"',
        expect="OK",
        owns="src/core.py, tests/test_core.py",
        cwd=str(tmp_path),
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.killed is True
    assert source_file.read_bytes() == src_bytes
    assert test_file.read_bytes() == test_bytes


def test_test_file_filtering_with_host_test_directory_in_path(tmp_path: Path):
    """Parent directories named 'test' or 'tests' on the host system must not cause source files to be misidentified as test files."""
    host_dir = tmp_path / "tests_environment" / "project"
    host_dir.mkdir(parents=True)

    src_dir = host_dir / "src"
    src_dir.mkdir()
    source_file = src_dir / "service.py"
    source_file.write_text("def run(): return 'service_ok'\n", encoding="utf-8")

    tests_dir = host_dir / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_service.py"
    test_file.write_text("def test(): pass\n", encoding="utf-8")

    src_bytes = source_file.read_bytes()
    test_bytes = test_file.read_bytes()

    gate = Gate(
        id="G_HOST_DIR",
        title="Host dir filtering check",
        status="MET",
        check=f'{sys.executable} -c "import sys; sys.path.insert(0, \'src\'); from service import run; assert run() == \'service_ok\'; print(\'OK\')"',
        expect="OK",
        owns="src/service.py, tests/test_service.py",
        cwd=str(host_dir),
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=host_dir)

    assert result.killed is True
    # Only source_file should have been sabotaged, test_file untouched
    assert source_file.read_bytes() == src_bytes
    assert test_file.read_bytes() == test_bytes


def test_non_existent_owned_files(tmp_path: Path):
    """If declared OWNS files do not exist, mutant is not killed."""
    gate = Gate(
        id="G9",
        title="Missing files",
        status="MET",
        check=f'{sys.executable} -c "print(\'OK\')"',
        expect="OK",
        owns="ghost_file.py",
        cwd=str(tmp_path),
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.killed is False
    assert result.error is not None
    assert "No existing owned files" in result.error


def test_test_adequacy_integration_with_owns(tmp_path: Path):
    """GateMutator.test_adequacy includes SOURCE_SABOTAGE when gate.owns is specified."""
    mod_file = tmp_path / "calc_adv.py"
    mod_file.write_text("def multiply(x: int, y: int) -> int: return x * y\n", encoding="utf-8")

    # Strong gate: tests genuine logic
    strong_gate = Gate(
        id="G10_STRONG",
        title="Strong gate with owns",
        status="MET",
        check=f'{sys.executable} -c "import calc_adv; assert calc_adv.multiply(3, 4) == 12; print(\'PASS\')"',
        expect="PASS",
        owns="calc_adv.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='PASS'",
    )

    mutator = GateMutator(timeout=5.0)
    report = mutator.test_adequacy(strong_gate, cwd=tmp_path)

    # Strategies tested should include NEGATE_EXIT, CORRUPT_EXPECT, and SOURCE_SABOTAGE
    tested_strats = [r.strategy for r in report.results]
    assert MutationStrategy.SOURCE_SABOTAGE in tested_strats
    assert MutationStrategy.NEGATE_EXIT in tested_strats
    assert MutationStrategy.CORRUPT_EXPECT in tested_strats
    assert report.weak is False
    assert report.kill_rate == 1.0
    assert strong_gate.mutation_tested is True
    assert classify_evidence(strong_gate) == EvidenceStrength.EXECUTABLE_PROOF

    # Weak gate: has owns, but check is tautological
    weak_gate = Gate(
        id="G10_WEAK",
        title="Weak gate with owns",
        status="MET",
        check=f'{sys.executable} -c "print(\'PASS\')"',
        expect="PASS",
        owns="calc_adv.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='PASS'",
    )

    report_weak = mutator.test_adequacy(weak_gate, cwd=tmp_path)
    assert report_weak.weak is True
    assert report_weak.kill_rate < 1.0
    assert weak_gate.mutation_tested is False
    assert classify_evidence(weak_gate) == EvidenceStrength.STRING_MATCH


def test_test_adequacy_without_owns(tmp_path: Path):
    """GateMutator.test_adequacy excludes SOURCE_SABOTAGE when gate.owns is absent."""
    gate = Gate(
        id="G11",
        title="No owns gate",
        status="MET",
        check=f'{sys.executable} -c "print(\'HELLO\')"',
        expect="HELLO",
        owns=None,
        cwd=str(tmp_path),
    )

    mutator = GateMutator(timeout=5.0)
    report = mutator.test_adequacy(gate, cwd=tmp_path)

    tested_strats = [r.strategy for r in report.results]
    assert MutationStrategy.SOURCE_SABOTAGE not in tested_strats


def test_non_python_file_sabotage(tmp_path: Path):
    """Harness must handle non-Python files (shell and javascript) with syntax-appropriate defects."""
    sh_file = tmp_path / "run.sh"
    sh_file.write_text("#!/bin/sh\necho 'BUILD_OK'\n", encoding="utf-8")
    sh_bytes = sh_file.read_bytes()

    js_file = tmp_path / "app.js"
    js_file.write_text("console.log('APP_OK');\n", encoding="utf-8")
    js_bytes = js_file.read_bytes()

    mutator = GateMutator(timeout=5.0)
    sabotaged_sh = mutator._sabotage_file(sh_file, sh_bytes)
    sabotaged_js = mutator._sabotage_file(js_file, js_bytes)

    assert b"exit 1" in sabotaged_sh
    assert b"throw new Error" in sabotaged_js


def test_classify_evidence_matrix():
    """classify_evidence must accurately handle all tiers and mutation promotion."""
    # 1. Abandoned -> NONE
    g_abandoned = Gate(id="G_AB", title="T", status="ABANDONED", evidence="exit_code=0")
    assert classify_evidence(g_abandoned) == EvidenceStrength.NONE

    # 2. No evidence -> NONE
    g_no_ev = Gate(id="G_NONE", title="T", evidence=None)
    assert classify_evidence(g_no_ev) == EvidenceStrength.NONE

    # 3. Pending evidence -> PENDING
    g_pending = Gate(id="G_PEND", title="T", evidence="pending")
    assert classify_evidence(g_pending) == EvidenceStrength.PENDING

    # 4. Manual gate without check -> MODEL_JUDGMENT
    g_manual = Gate(id="G_MAN", title="T", check=None, evidence="Reviewed and confirmed")
    assert classify_evidence(g_manual) == EvidenceStrength.MODEL_JUDGMENT

    # 5. String match (exit_code=0 without mutation tested) -> STRING_MATCH
    g_string = Gate(id="G_STR", title="T", check="echo OK", evidence="exit_code=0 match='OK'")
    assert classify_evidence(g_string) == EvidenceStrength.STRING_MATCH

    # 6. Executable proof via attribute mutation_tested=True
    g_proof_attr = Gate(
        id="G_PROOF1",
        title="T",
        check="echo OK",
        evidence="exit_code=0 match='OK'",
        mutation_tested=True,
    )
    assert classify_evidence(g_proof_attr) == EvidenceStrength.EXECUTABLE_PROOF

    # 7. Executable proof via evidence string
    g_proof_str = Gate(
        id="G_PROOF2",
        title="T",
        check="echo OK",
        evidence="exit_code=0 match='OK' mutation_tested=true",
        mutation_tested=False,
    )
    assert classify_evidence(g_proof_str) == EvidenceStrength.EXECUTABLE_PROOF

    # 8. Failed mutation recorded in evidence string -> STRING_MATCH
    g_proof_false = Gate(
        id="G_PROOF_FAIL",
        title="T",
        check="echo OK",
        evidence="exit_code=0 match='OK' mutation_tested=false",
        mutation_tested=False,
    )
    assert classify_evidence(g_proof_false) == EvidenceStrength.STRING_MATCH

    # 9. Coincidental substring in match output -> STRING_MATCH
    g_proof_coinc = Gate(
        id="G_PROOF_COINC",
        title="T",
        check="echo OK",
        evidence="exit_code=0 match='test_mutation_tested.py PASSED'",
        mutation_tested=False,
    )
    assert classify_evidence(g_proof_coinc) == EvidenceStrength.STRING_MATCH
