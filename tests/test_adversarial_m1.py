"""Adversarial stress-testing suite for GateMutator.mutate with SOURCE_SABOTAGE.

Probes:
1. Deep AST nesting: nested functions, closures, decorators, generator functions, async generators, lambdas.
2. Complex from __future__ imports combined with module docstrings, multiline comments, and top-level type comments.
3. High-concurrency and rapid back-to-back mutation cycles on owned files.
4. Evidence strength classification and promotion integrity under survivor and adversarial evidence strings.
"""
from __future__ import annotations
import ast
import asyncio
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


# ============================================================================
# Category 1: Deep AST Nesting
# ============================================================================

def test_deeply_nested_sync_functions(tmp_path: Path):
    """Deeply nested function hierarchies (outer -> mid -> inner -> innermost)."""
    src_file = tmp_path / "nested.py"
    src_content = (
        "def level1(x):\n"
        "    def level2(y):\n"
        "        def level3(z):\n"
        "            def level4(w):\n"
        "                return x + y + z + w\n"
        "            return level4(z * 2)\n"
        "        return level3(y * 2)\n"
        "    return level2(x * 2)\n"
    )
    src_file.write_text(src_content, encoding="utf-8")
    original_bytes = src_file.read_bytes()

    gate = Gate(
        id="G_NESTED",
        title="Nested function execution",
        status="MET",
        check=f'{sys.executable} -c "import nested; assert nested.level1(1) == 15; print(\'NESTED_OK\')"',
        expect="NESTED_OK",
        owns="nested.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='NESTED_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert gate.mutation_tested is True
    assert src_file.read_bytes() == original_bytes
    assert classify_evidence(gate) == EvidenceStrength.EXECUTABLE_PROOF


def test_closures_with_captured_state(tmp_path: Path):
    """Closures capturing outer state must be sabotaged so inner invocation fails."""
    src_file = tmp_path / "closure.py"
    src_content = (
        "def make_counter(start):\n"
        "    count = start\n"
        "    def inc(step=1):\n"
        "        nonlocal count\n"
        "        count += step\n"
        "        return count\n"
        "    return inc\n"
    )
    src_file.write_text(src_content, encoding="utf-8")
    original_bytes = src_file.read_bytes()

    # Check only calls the inner closure function returned by make_counter
    gate = Gate(
        id="G_CLOSURE",
        title="Closure execution",
        status="MET",
        check=f'{sys.executable} -c "import closure; c = closure.make_counter(10); assert c(5) == 15; print(\'CLOSURE_OK\')"',
        expect="CLOSURE_OK",
        owns="closure.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='CLOSURE_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert src_file.read_bytes() == original_bytes


def test_decorators_definition_and_runtime(tmp_path: Path):
    """Function and class decorators, properties, staticmethods, and classmethods."""
    src_file = tmp_path / "decorated.py"
    src_content = (
        "def audit_deco(fn):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return fn(*args, **kwargs)\n"
        "    return wrapper\n\n"
        "class Engine:\n"
        "    _val = 100\n\n"
        "    @audit_deco\n"
        "    def compute(self, x):\n"
        "        return x * 2\n\n"
        "    @property\n"
        "    def state(self):\n"
        "        return self._val\n\n"
        "    @classmethod\n"
        "    def get_val(cls):\n"
        "        return cls._val\n\n"
        "    @staticmethod\n"
        "    def ping():\n"
        "        return 'PONG'\n"
    )
    src_file.write_text(src_content, encoding="utf-8")
    original_bytes = src_file.read_bytes()

    gate = Gate(
        id="G_DECO",
        title="Decorator and method execution",
        status="MET",
        check=f'{sys.executable} -c "import decorated; e = decorated.Engine(); assert e.compute(5) == 10 and e.state == 100 and decorated.Engine.get_val() == 100 and decorated.Engine.ping() == \'PONG\'; print(\'DECO_OK\')"',
        expect="DECO_OK",
        owns="decorated.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='DECO_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert src_file.read_bytes() == original_bytes


def test_generator_and_async_generator(tmp_path: Path):
    """Sync generator functions and async generator functions."""
    src_file = tmp_path / "generators.py"
    src_content = (
        "def number_stream(n):\n"
        "    for i in range(n):\n"
        "        yield i * 2\n\n"
        "async def async_stream(n):\n"
        "    for i in range(n):\n"
        "        yield i * 3\n"
    )
    src_file.write_text(src_content, encoding="utf-8")
    original_bytes = src_file.read_bytes()

    gate = Gate(
        id="G_GEN",
        title="Stream verification",
        status="MET",
        check=f'{sys.executable} -c "import asyncio, generators; assert list(generators.number_stream(3)) == [0, 2, 4]; g = generators.async_stream(3); assert asyncio.run(g.__anext__()) == 0; print(\'GEN_OK\')"',
        expect="GEN_OK",
        owns="generators.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='GEN_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert src_file.read_bytes() == original_bytes


def test_pure_lambda_module_sabotaged(tmp_path: Path):
    """Module containing only lambdas and constants (no FunctionDef)."""
    src_file = tmp_path / "lambdas_only.py"
    src_content = (
        "square = lambda x: x * x\n"
        "cube = lambda x: x * x * x\n"
        "CONST = 42\n"
    )
    src_file.write_text(src_content, encoding="utf-8")
    original_bytes = src_file.read_bytes()

    gate = Gate(
        id="G_LAMBDA",
        title="Lambda verification",
        status="MET",
        check=f'{sys.executable} -c "import lambdas_only; assert lambdas_only.square(4) == 16; print(\'LAMBDA_OK\')"',
        expect="LAMBDA_OK",
        owns="lambdas_only.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='LAMBDA_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert src_file.read_bytes() == original_bytes


# ============================================================================
# Category 2: Complex __future__ imports, docstrings, and type comments
# ============================================================================

def test_complex_future_imports_and_multiline_docstrings(tmp_path: Path):
    """Multiple __future__ imports, multiline docstring, type comments, no functions."""
    src_file = tmp_path / "future_complex.py"
    src_content = (
        '"""\n'
        'This is a complex module header.\n'
        'It has multiple lines of explanation.\n'
        '"""\n'
        'from __future__ import annotations\n'
        'from __future__ import (\n'
        '    division,\n'
        '    absolute_import,\n'
        ')\n'
        '# Top-level type comment\n'
        'from typing import Dict, List, Tuple\n'
        '# Another comment line\n'
        'CONFIG: Dict[str, int] = {"rate": 42, "limit": 100}\n'
    )
    src_file.write_text(src_content, encoding="utf-8")
    original_bytes = src_file.read_bytes()

    mutator = GateMutator(timeout=5.0)
    sabotaged = mutator._sabotage_file(src_file, original_bytes)
    sabotaged_str = sabotaged.decode("utf-8")

    # Sabotaged code must parse cleanly without SyntaxError regarding __future__
    parsed = ast.parse(sabotaged_str)
    # The __future__ imports must precede the injected raise statement
    future_positions = [i for i, s in enumerate(parsed.body) if isinstance(s, ast.ImportFrom) and s.module == "__future__"]
    raise_positions = [i for i, s in enumerate(parsed.body) if isinstance(s, ast.Raise)]

    assert len(future_positions) >= 2
    assert len(raise_positions) >= 1
    assert min(raise_positions) > max(future_positions)

    gate = Gate(
        id="G_FUTURE",
        title="Future script verification",
        status="MET",
        check=f'{sys.executable} -c "import future_complex; assert future_complex.CONFIG[\'rate\'] == 42; print(\'FUTURE_OK\')"',
        expect="FUTURE_OK",
        owns="future_complex.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='FUTURE_OK'",
    )

    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert src_file.read_bytes() == original_bytes


def test_future_imports_with_functions_retains_future_at_top(tmp_path: Path):
    """When functions exist alongside __future__, functions are sabotaged, keeping __future__ valid."""
    src_file = tmp_path / "future_fn.py"
    src_content = (
        '"""Docstring."""\n'
        'from __future__ import annotations\n'
        'import sys\n\n'
        'def get_version() -> str:\n'
        '    return "1.0.0"\n'
    )
    src_file.write_text(src_content, encoding="utf-8")
    original_bytes = src_file.read_bytes()

    gate = Gate(
        id="G_FUTURE_FN",
        title="Future fn verification",
        status="MET",
        check=f'{sys.executable} -c "import future_fn; assert future_fn.get_version() == \'1.0.0\'; print(\'VER_OK\')"',
        expect="VER_OK",
        owns="future_fn.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='VER_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert src_file.read_bytes() == original_bytes


# ============================================================================
# Category 3: Rapid Cycles and Concurrency
# ============================================================================

def test_rapid_mutation_cycles(tmp_path: Path):
    """50 rapid sequential mutate() calls on the same file must guarantee 100% byte fidelity."""
    src_file = tmp_path / "rapid.py"
    src_content = (
        "def calculate(n: int) -> int:\n"
        "    return n * 10 + 7\n"
    )
    src_file.write_text(src_content, encoding="utf-8")
    original_bytes = src_file.read_bytes()

    gate = Gate(
        id="G_RAPID",
        title="Rapid cycles",
        status="MET",
        check=f'{sys.executable} -c "import rapid; assert rapid.calculate(3) == 37; print(\'RAPID_OK\')"',
        expect="RAPID_OK",
        owns="rapid.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='RAPID_OK'",
    )

    mutator = GateMutator(timeout=5.0)

    for i in range(50):
        res = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
        assert res.killed is True, f"Failed kill on cycle {i}"
        current_bytes = src_file.read_bytes()
        assert current_bytes == original_bytes, f"Corrupted file on cycle {i}"

    assert gate.mutation_tested is True


def test_concurrent_disjoint_mutations(tmp_path: Path):
    """10 concurrent threads mutating disjoint owned files."""
    num_threads = 10
    mutator = GateMutator(timeout=5.0)

    gates = []
    files = []
    for i in range(num_threads):
        f = tmp_path / f"worker_mod_{i}.py"
        f.write_text(f"def get_id(): return {i}\n", encoding="utf-8")
        files.append((f, f.read_bytes()))

        g = Gate(
            id=f"G_WORKER_{i}",
            title=f"Worker {i}",
            status="MET",
            check=f'{sys.executable} -c "import worker_mod_{i}; assert worker_mod_{i}.get_id() == {i}; print(\'WORKER_{i}_OK\')"',
            expect=f"WORKER_{i}_OK",
            owns=f"worker_mod_{i}.py",
            cwd=str(tmp_path),
            evidence=f"exit_code=0 match='WORKER_{i}_OK'",
        )
        gates.append(g)

    results = [None] * num_threads

    def run_worker(idx):
        results[idx] = mutator.mutate(gates[idx], MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        list(executor.map(run_worker, range(num_threads)))

    for i in range(num_threads):
        res = results[i]
        assert res is not None
        assert res.killed is True, f"Thread {i} failed kill"
        assert res.mutant_passed is False
        f_path, orig_b = files[i]
        assert f_path.read_bytes() == orig_b, f"Thread {i} file mismatch"


# ============================================================================
# Category 4: Evidence Strength Classification & Promotion Integrity
# ============================================================================

def test_evidence_strength_strictly_denied_on_survival(tmp_path: Path):
    """When mutant survives, mutation_tested MUST be False and strength MUST NOT be EXECUTABLE_PROOF."""
    src_file = tmp_path / "survivor.py"
    src_file.write_text("def unused_fn(): return 42\n", encoding="utf-8")
    orig_bytes = src_file.read_bytes()

    # Tautological check ignores survivor.py
    gate = Gate(
        id="G_SURVIVE",
        title="Tautological survivor",
        status="MET",
        check=f'{sys.executable} -c "print(\'IMMUNE\')"',
        expect="IMMUNE",
        owns="survivor.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='IMMUNE'",
    )

    mutator = GateMutator(timeout=5.0)
    res = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert res.original_passed is True
    assert res.mutant_passed is True
    assert res.killed is False
    assert gate.mutation_tested is False

    strength = classify_evidence(gate)
    assert strength == EvidenceStrength.STRING_MATCH
    assert strength != EvidenceStrength.EXECUTABLE_PROOF


def test_classify_evidence_false_promotion_on_failed_mutation():
    """VERIFIED REMEDIATION: classify_evidence does not promote gate when evidence has mutation_tested=false.

    Ensures that gates recording 'mutation_tested=false' or 'mutation_tested=failed'
    are correctly classified as STRING_MATCH and not EXECUTABLE_PROOF.
    """
    gate_failed = Gate(
        id="G_FAIL_STR",
        title="Failed mutation gate",
        status="MET",
        check=f"{sys.executable} -c 'print(\"OK\")'",
        expect="OK",
        evidence="exit_code=0 match='OK' mutation_tested=false",
        mutation_tested=False,
    )
    strength = classify_evidence(gate_failed)
    assert strength == EvidenceStrength.STRING_MATCH
    assert strength != EvidenceStrength.EXECUTABLE_PROOF


def test_classify_evidence_false_promotion_on_coincidental_match():
    """VERIFIED REMEDIATION: classify_evidence does not promote gate on coincidental test filename match.

    If a gate check runs tests on a file named 'test_mutation_tested.py', its match preview
    contains 'mutation_tested', but lacks 'mutation_tested=true', so it must remain STRING_MATCH.
    """
    gate_coincidental = Gate(
        id="G_COINCIDENCE",
        title="Coincidental match",
        status="MET",
        check="pytest tests/test_mutation_tested.py",
        expect="PASSED",
        evidence="exit_code=0 match='tests/test_mutation_tested.py PASSED'",
        mutation_tested=False,
    )
    strength = classify_evidence(gate_coincidental)
    assert strength == EvidenceStrength.STRING_MATCH
    assert strength != EvidenceStrength.EXECUTABLE_PROOF

