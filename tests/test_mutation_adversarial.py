from __future__ import annotations
import os
import signal
import sys
import tempfile
from pathlib import Path
import pytest

from dafg.mutation import (
    GateMutator,
    MutationStrategy,
    MutationResult,
)
from dafg.gates import (
    Gate,
    classify_evidence,
    EvidenceStrength,
)


def test_adversarial_restoration_under_keyboard_interrupt(tmp_path: Path):
    """File must be 100% restored byte-for-byte even when KeyboardInterrupt occurs during mutant evaluation."""
    target_file = tmp_path / "ki_target.py"
    original_bytes = b"def core_calc():\n    return 100\n"
    target_file.write_bytes(original_bytes)

    gate = Gate(
        id="G_ADV_KI",
        title="KeyboardInterrupt stress",
        status="MET",
        check=f"{sys.executable} -c 'import ki_target; print(ki_target.core_calc())'",
        expect="100",
        owns="ki_target.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='100'",
    )

    mutator = GateMutator(timeout=5.0)
    orig_eval = mutator._evaluate
    calls = [0]

    def mock_eval_ki(check, expect, env, cwd):
        calls[0] += 1
        if calls[0] == 1:
            return True  # Original evaluation passes
        raise KeyboardInterrupt("Simulated SIGINT / Ctrl+C")

    mutator._evaluate = mock_eval_ki
    caught = False
    try:
        mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    except KeyboardInterrupt:
        caught = True
    finally:
        mutator._evaluate = orig_eval

    assert caught is True, "KeyboardInterrupt must propagate out of mutate"
    assert target_file.read_bytes() == original_bytes, "Target file must be restored despite KeyboardInterrupt"


def test_adversarial_restoration_under_system_exit(tmp_path: Path):
    """File must be 100% restored byte-for-byte even when SystemExit occurs during mutant evaluation."""
    target_file = tmp_path / "exit_target.py"
    original_bytes = b"def do_exit_work():\n    return 'ACTIVE'\n"
    target_file.write_bytes(original_bytes)

    gate = Gate(
        id="G_ADV_EXIT",
        title="SystemExit stress",
        status="MET",
        check=f"{sys.executable} -c 'import exit_target; print(exit_target.do_exit_work())'",
        expect="ACTIVE",
        owns="exit_target.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='ACTIVE'",
    )

    mutator = GateMutator(timeout=5.0)
    orig_eval = mutator._evaluate
    calls = [0]

    def mock_eval_exit(check, expect, env, cwd):
        calls[0] += 1
        if calls[0] == 1:
            return True
        sys.exit(33)

    mutator._evaluate = mock_eval_exit
    exit_code = None
    try:
        mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    except SystemExit as e:
        exit_code = e.code
    finally:
        mutator._evaluate = orig_eval

    assert exit_code == 33, "SystemExit must propagate out with exact exit code"
    assert target_file.read_bytes() == original_bytes, "Target file must be restored despite SystemExit"


def test_adversarial_restoration_under_subprocess_sigkill(tmp_path: Path):
    """File must be restored and mutant killed when the check subprocess aborts via SIGKILL."""
    target_file = tmp_path / "crash_target.py"
    original_bytes = b"def compute():\n    return 'COMPUTED'\n"
    target_file.write_bytes(original_bytes)

    # Under mutation, compute() raises RuntimeError, which triggers os.kill(SIGKILL)
    gate = Gate(
        id="G_ADV_SIGKILL",
        title="Subprocess abort stress",
        status="MET",
        check=f"""{sys.executable} -c "import sys, os, signal; sys.path.insert(0, '.'); import crash_target;
try:
    crash_target.compute()
    print('PASS')
except RuntimeError:
    os.kill(os.getpid(), signal.SIGKILL)
" """,
        expect="PASS",
        owns="crash_target.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='PASS'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert target_file.read_bytes() == original_bytes


def test_adversarial_restoration_under_partial_write_failure(tmp_path: Path):
    """When multiple files are owned and writing the 2nd file fails, the 1st file must still be restored."""
    f1 = tmp_path / "multi_a.py"
    f2 = tmp_path / "multi_b.py"
    bytes1 = b"def a(): return 'a'\n"
    bytes2 = b"def b(): return 'b'\n"
    f1.write_bytes(bytes1)
    f2.write_bytes(bytes2)

    gate = Gate(
        id="G_ADV_PARTIAL",
        title="Partial write failure",
        status="MET",
        check=f"{sys.executable} -c 'import multi_a, multi_b; print(\"OK\")'",
        expect="OK",
        owns="multi_a.py, multi_b.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='OK'",
    )

    mutator = GateMutator(timeout=5.0)
    orig_sabotage = mutator._sabotage_file

    def mock_sabotage(p, b):
        if "multi_b" in str(p):
            raise IOError("Simulated disk error while sabotaging multi_b")
        return orig_sabotage(p, b)

    mutator._sabotage_file = mock_sabotage
    try:
        mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    finally:
        mutator._sabotage_file = orig_sabotage

    # Both files must be restored to original bytes
    assert f1.read_bytes() == bytes1, "multi_a.py was written with sabotage, but must be restored!"
    assert f2.read_bytes() == bytes2, "multi_b.py must remain original bytes"


def test_adversarial_empty_file_sabotage_and_restoration(tmp_path: Path):
    """Empty files (0 bytes) must be sabotaged so imports fail, and restored back to 0 bytes."""
    empty_file = tmp_path / "empty_mod.py"
    empty_file.write_bytes(b"")

    gate = Gate(
        id="G_ADV_EMPTY",
        title="Empty file sabotage",
        status="MET",
        check=f"""{sys.executable} -c "import sys; sys.path.insert(0, '.'); import empty_mod; print('EMPTY_LOADED')" """,
        expect="EMPTY_LOADED",
        owns="empty_mod.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='EMPTY_LOADED'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert empty_file.read_bytes() == b""


def test_adversarial_comments_and_docstrings_only_files(tmp_path: Path):
    """Files with only comments or docstrings must be sabotaged and restored."""
    comments_file = tmp_path / "only_comments.py"
    docstring_file = tmp_path / "only_docstring.py"
    c_bytes = b"# Comment 1\n# Comment 2\n"
    d_bytes = b'"""Module-level documentation only."""\n'
    comments_file.write_bytes(c_bytes)
    docstring_file.write_bytes(d_bytes)

    mutator = GateMutator(timeout=5.0)

    # Test comments file
    gate_c = Gate(
        id="G_ADV_COMM",
        title="Comments only",
        status="MET",
        check=f"""{sys.executable} -c "import sys; sys.path.insert(0, '.'); import only_comments; print('COMM_OK')" """,
        expect="COMM_OK",
        owns="only_comments.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='COMM_OK'",
    )
    res_c = mutator.mutate(gate_c, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    assert res_c.killed is True
    assert comments_file.read_bytes() == c_bytes

    # Test docstring file
    gate_d = Gate(
        id="G_ADV_DOCS",
        title="Docstring only",
        status="MET",
        check=f"""{sys.executable} -c "import sys; sys.path.insert(0, '.'); import only_docstring; print('DOC_OK')" """,
        expect="DOC_OK",
        owns="only_docstring.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='DOC_OK'",
    )
    res_d = mutator.mutate(gate_d, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)
    assert res_d.killed is True
    assert docstring_file.read_bytes() == d_bytes


def test_adversarial_syntax_broken_file_handling(tmp_path: Path):
    """A file with preexisting syntax errors must survive mutation if the gate explicitly tests for syntax error."""
    broken_file = tmp_path / "bad_syntax.py"
    b_bytes = b"def invalid_syntax(:\n    pass\n"
    broken_file.write_bytes(b_bytes)

    gate = Gate(
        id="G_ADV_SYNTAX",
        title="Syntax error check",
        status="MET",
        check=f"""{sys.executable} -c "import sys; sys.path.insert(0, '.');
try:
    import bad_syntax
except SyntaxError:
    print('CAUGHT_SYNTAX')
" """,
        expect="CAUGHT_SYNTAX",
        owns="bad_syntax.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='CAUGHT_SYNTAX'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    # Mutant survives because the syntax error is still raised during compilation
    assert result.mutant_passed is True
    assert result.killed is False
    assert broken_file.read_bytes() == b_bytes


def test_adversarial_multi_file_one_valid_one_missing(tmp_path: Path):
    """Gate declaring one existing file and one missing file must sabotage the existing one and restore it."""
    valid_file = tmp_path / "valid_code.py"
    v_bytes = b"def get_data(): return 'DATA_OK'\n"
    valid_file.write_bytes(v_bytes)
    missing_path = tmp_path / "non_existent.py"
    assert not missing_path.exists()

    gate = Gate(
        id="G_ADV_MISSING_ONE",
        title="Multi-file partial presence",
        status="MET",
        check=f"""{sys.executable} -c "import sys; sys.path.insert(0, '.'); import valid_code; assert valid_code.get_data() == 'DATA_OK'; print('ALL_MET')" """,
        expect="ALL_MET",
        owns="valid_code.py, non_existent.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='ALL_MET'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert valid_file.read_bytes() == v_bytes
    assert not missing_path.exists()


def test_adversarial_multi_file_all_missing(tmp_path: Path):
    """When all declared OWNS files are missing, mutant is not killed and not promoted."""
    gate = Gate(
        id="G_ADV_ALL_GHOST",
        title="All ghost files",
        status="MET",
        check="echo GHOST",
        expect="GHOST",
        owns="ghost1.py, ghost2.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='GHOST'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.killed is False
    assert result.error == "No existing owned files found to sabotage"
    assert gate.mutation_tested is False
    assert classify_evidence(gate) == EvidenceStrength.STRING_MATCH


@pytest.mark.parametrize(
    "name,check_cmd,expect_val",
    [
        ("echo_const", "echo TAUTOLOGY_OK", "TAUTOLOGY_OK"),
        ("python_print", f"{sys.executable} -c \"print('PRINT_OK')\"", "PRINT_OK"),
        ("file_test", "test -f normal_core.py && echo FILE_EXISTS", "FILE_EXISTS"),
        ("py_compile", f"{sys.executable} -m py_compile normal_core.py && echo COMPILES", "COMPILES"),
        (
            "swallow_exc",
            f"""{sys.executable} -c "import sys; sys.path.insert(0, '.');
try:
    import normal_core
    normal_core.active_fn()
except Exception:
    pass
print('SWALLOWED_OK')
" """,
            "SWALLOWED_OK",
        ),
    ],
)
def test_adversarial_tautology_resistance(tmp_path: Path, name: str, check_cmd: str, expect_val: str):
    """Tautological check commands that do not depend on code execution must NOT achieve killed=True."""
    target_file = tmp_path / "normal_core.py"
    original_bytes = b"def active_fn(): return 'REAL_RESULT'\n"
    target_file.write_bytes(original_bytes)

    gate = Gate(
        id=f"G_TAUT_{name}",
        title=f"Tautology {name}",
        status="MET",
        check=check_cmd,
        expect=expect_val,
        owns="normal_core.py",
        cwd=str(tmp_path),
        evidence=f"exit_code=0 match='{expect_val}'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True, "Original check should pass for tautology"
    assert result.mutant_passed is True, "Mutant must survive because check is tautological"
    assert result.killed is False, "Tautology must NOT be marked killed"
    assert gate.mutation_tested is False, "Tautology must NOT be marked mutation_tested"
    assert classify_evidence(gate) == EvidenceStrength.STRING_MATCH
    assert target_file.read_bytes() == original_bytes


def test_adversarial_unicode_and_encoding_resilience(tmp_path: Path):
    """Files containing multi-byte UTF-8 characters must parse, mutate, and restore without corruption."""
    utf8_file = tmp_path / "unicode_app.py"
    content = (
        "# 🚀 日本語コメント\n"
        "def get_greeting() -> str:\n"
        "    return 'こんにちは世界 🌍'\n"
    )
    original_bytes = content.encode("utf-8")
    utf8_file.write_bytes(original_bytes)

    gate = Gate(
        id="G_ADV_UTF8",
        title="Unicode support",
        status="MET",
        check=f"""{sys.executable} -c "import sys; sys.path.insert(0, '.'); import unicode_app; assert unicode_app.get_greeting() == 'こんにちは世界 🌍'; print('UNICODE_OK')" """,
        expect="UNICODE_OK",
        owns="unicode_app.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='UNICODE_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert utf8_file.read_bytes() == original_bytes


def test_adversarial_python_match_case_ast_integrity(tmp_path: Path):
    """Python 3.10+ match/case syntax must be parsed and mutated without AST syntax errors."""
    match_file = tmp_path / "pattern_matcher.py"
    content = (
        "def categorize(val: int) -> str:\n"
        "    match val:\n"
        "        case 1:\n"
        "            return 'ONE'\n"
        "        case _:\n"
        "            return 'OTHER'\n"
    )
    original_bytes = content.encode("utf-8")
    match_file.write_bytes(original_bytes)

    gate = Gate(
        id="G_ADV_MATCH",
        title="Match case support",
        status="MET",
        check=f"""{sys.executable} -c "import sys; sys.path.insert(0, '.'); import pattern_matcher; assert pattern_matcher.categorize(1) == 'ONE'; print('MATCH_OK')" """,
        expect="MATCH_OK",
        owns="pattern_matcher.py",
        cwd=str(tmp_path),
        evidence="exit_code=0 match='MATCH_OK'",
    )

    mutator = GateMutator(timeout=5.0)
    result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

    assert result.original_passed is True
    assert result.mutant_passed is False
    assert result.killed is True
    assert match_file.read_bytes() == original_bytes


def test_adversarial_flaw_permission_denied_causes_false_kill(tmp_path: Path):
    """VERIFIED REMEDIATION: If a file cannot be written (chmod 444), mutate() sets killed=False.
    
    A robust harness reports killed=False, mutation_tested=False, and denies EXECUTABLE_PROOF.
    """
    ro_file = tmp_path / "readonly_lib.py"
    ro_file.write_text("def important_fn(): return 42\n", encoding="utf-8")
    os.chmod(ro_file, 0o444)

    try:
        # Tautological check: prints OK without importing readonly_lib
        gate = Gate(
            id="G_ADV_RO_TAUT",
            title="Read-only tautology vulnerability",
            status="MET",
            check=f"{sys.executable} -c 'print(\"TAUT_OK\")'",
            expect="TAUT_OK",
            owns="readonly_lib.py",
            cwd=str(tmp_path),
            evidence="exit_code=0 match='TAUT_OK'",
        )

        mutator = GateMutator(timeout=5.0)
        result = mutator.mutate(gate, MutationStrategy.SOURCE_SABOTAGE, cwd=tmp_path)

        assert result.killed is False, f"Harness failure must not mark mutant as killed: {result}"
        assert result.error is not None and "Permission denied" in result.error
        assert gate.mutation_tested is False, "Gate must not be marked mutation_tested=True when PermissionError occurs!"
        assert classify_evidence(gate) != EvidenceStrength.EXECUTABLE_PROOF, "Must not be promoted to EXECUTABLE_PROOF without test running against sabotage!"
        assert classify_evidence(gate) == EvidenceStrength.STRING_MATCH
    finally:
        os.chmod(ro_file, 0o644)
