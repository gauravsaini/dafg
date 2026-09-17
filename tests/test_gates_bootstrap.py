"""Tests for automated test bootstrapping (bootstrap_ledger & CLI gates --bootstrap).

Validates:
- Test file discovery across Python and JS/TS test naming conventions.
- AST import extraction resolving concrete internal source deliverables for OWNS:.
- Synthesis of clean, lint-compliant GATES.md with 0 errors and 0 warnings.
- Fallback OWNS: resolution when tests do not import internal modules.
- CLI execution via gates --bootstrap <target>.
"""

from pathlib import Path
import pytest

from dafg.gates import (
    GateLedger,
    GateLinter,
    bootstrap_ledger,
    main as gates_main,
)


def test_bootstrap_ledger_discovers_python_tests_and_resolves_owns(tmp_path):
    # Setup sample project layout:
    # tmp_path/
    #   src/
    #     mathlib/
    #       __init__.py
    #       calc.py
    #       geometry.py
    #   tests/
    #     test_calc.py
    #     test_geometry.py
    src_dir = tmp_path / "src" / "mathlib"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "calc.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (src_dir / "geometry.py").write_text("def area(w, h): return w * h\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_calc.py").write_text(
        """import pytest
from mathlib.calc import add

def test_add():
    assert add(1, 2) == 3
""",
        encoding="utf-8",
    )
    (tests_dir / "test_geometry.py").write_text(
        """import mathlib.geometry as mg

def test_area():
    assert mg.area(2, 3) == 6
""",
        encoding="utf-8",
    )

    ledger = bootstrap_ledger(tmp_path)
    assert len(ledger.gates) == 2
    assert ledger.mode == "standard"

    # Verify gates
    g1 = ledger.gates["G1"]
    assert g1.title == "Test suite test_calc.py"
    assert g1.check == "uv run pytest tests/test_calc.py -q"
    assert g1.expect == "passed"
    assert g1.owns == "src/mathlib/calc.py"
    assert g1.author == "external"

    g2 = ledger.gates["G2"]
    assert g2.title == "Test suite test_geometry.py"
    assert g2.check == "uv run pytest tests/test_geometry.py -q"
    assert g2.expect == "passed"
    assert g2.owns == "src/mathlib/geometry.py"
    assert g2.author == "external"

    # Must pass GateLinter with 0 errors and 0 warnings
    issues = GateLinter.lint(ledger)
    assert len(issues) == 0


def test_bootstrap_ledger_fallback_owns_when_no_internal_modules(tmp_path):
    # Setup test file that only imports standard library
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    (tests_dir / "test_stdlib_only.py").write_text(
        """import os
import sys

def test_os():
    assert True
""",
        encoding="utf-8",
    )

    ledger = bootstrap_ledger(tmp_path)
    assert len(ledger.gates) == 1
    g = ledger.gates["G1"]
    assert g.owns == "src/"  # Fallback to src/

    issues = GateLinter.lint(ledger)
    assert len(issues) == 0


def test_bootstrap_ledger_js_test_discovery(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "service.js").write_text("module.exports = { start: () => {} };\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "service.test.js").write_text(
        """const svc = require('../src/service');
test('start', () => {});
""",
        encoding="utf-8",
    )

    ledger = bootstrap_ledger(tmp_path)
    assert len(ledger.gates) == 1
    g = ledger.gates["G1"]
    assert g.check == "node tests/service.test.js"
    assert g.expect == "passed"
    assert g.owns == "src/service.js"

    issues = GateLinter.lint(ledger)
    assert len(issues) == 0


def test_cli_gates_bootstrap(tmp_path, monkeypatch):
    # Setup sample project
    src_dir = tmp_path / "src" / "pkg"
    src_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "core.py").write_text("x = 42\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_core.py").write_text(
        "from pkg.core import x\ndef test_x(): assert x == 42\n",
        encoding="utf-8",
    )

    # Run in tmp_path context
    monkeypatch.chdir(tmp_path)

    draft_file = tmp_path / "GATES_DRAFT.md"
    assert not draft_file.exists()

    ret = gates_main(["--bootstrap", str(draft_file)])
    assert ret == 0
    assert draft_file.exists()

    content = draft_file.read_text(encoding="utf-8")
    assert "MODE: standard" in content
    assert "CHECK: uv run pytest tests/test_core.py -q" in content
    assert "OWNS: src/pkg/core.py" in content
    assert "EXPECT: passed" in content

    # Verify generated draft passes GateLinter
    loaded_ledger = GateLedger.load(draft_file)
    issues = GateLinter.lint(loaded_ledger)
    assert len(issues) == 0


def test_bootstrap_on_current_repository():
    # Run bootstrap_ledger on framework repository root
    ledger = bootstrap_ledger(Path("."))
    assert len(ledger.gates) >= 50
    assert ledger.mode == "standard"

    # Must pass GateLinter with 0 errors and 0 warnings
    issues = GateLinter.lint(ledger)
    assert len(issues) == 0
