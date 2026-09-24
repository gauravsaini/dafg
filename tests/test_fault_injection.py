"""Deterministic unit tests for fault injection operators and public API exports."""

import unittest
from dataclasses import is_dataclass

import dafg
from dafg import (
    CLASS_1_SYNTAX_PACKAGING,
    CLASS_2_SUBTLE_LOGIC,
    CLASS_3_CONCURRENCY_RACES,
    CLASS_4_MOCK_FACADES,
    CLASS_5_SECURITY_VIOLATIONS,
    CLASS_6_UNSATISFIABLE_CONSTRAINTS,
    ConcurrencyRace,
    FacadeStub,
    FaultOperator,
    FaultResult,
    LogicFlip,
    ScopeViolation,
    SyntaxBreak,
    UnsatisfiableConstraint,
    concurrency_race,
    facade_stub,
    logic_flip,
    scope_violation,
    syntax_break,
    unsatisfiable_constraint,
)


class TestFaultInjection(unittest.TestCase):
    """Test suite for deterministic fault operators."""

    def test_syntax_break_operator(self) -> None:
        """Test Class 1: syntax_break produces AST/syntax errors and is gate-detectable."""
        res_default = syntax_break()
        self.assertIsInstance(res_default, FaultResult)
        self.assertEqual(res_default.class_name, CLASS_1_SYNTAX_PACKAGING)
        self.assertEqual(res_default.class_name, "Syntax & Packaging")
        self.assertTrue(res_default.detectable_by_gate)
        self.assertIn("SyntaxError", res_default.expected_failure)
        with self.assertRaises(SyntaxError):
            compile(res_default.after, "<test_syntax>", "exec")

        custom_input = "def compute(x: int) -> int:\n    return (x * 2)\n"
        input_copy = custom_input[:]
        res_custom = syntax_break(custom_input)
        self.assertEqual(custom_input, input_copy, "Input must not be mutated")
        self.assertNotEqual(res_custom.before, res_custom.after)
        with self.assertRaises(SyntaxError):
            compile(res_custom.after, "<test_custom_syntax>", "exec")

        op = SyntaxBreak()
        res_op = op(custom_input)
        self.assertEqual(res_op.after, res_custom.after)

    def test_logic_flip_operator(self) -> None:
        """Test Class 2: logic_flip inverts predicate conditions deterministically."""
        res_default = logic_flip()
        self.assertIsInstance(res_default, FaultResult)
        self.assertEqual(res_default.class_name, CLASS_2_SUBTLE_LOGIC)
        self.assertEqual(res_default.class_name, "Subtle Logic & Regressions")
        self.assertTrue(res_default.detectable_by_gate)
        self.assertIn("AssertionError", res_default.expected_failure)
        self.assertIn("<=", res_default.after)
        self.assertIn("-> bool:", res_default.after)

        custom_input = "def is_authorized(role: str) -> bool:\n    return role == 'admin'\n"
        input_copy = custom_input[:]
        res_custom = logic_flip(custom_input)
        self.assertEqual(custom_input, input_copy, "Input must not be mutated")
        self.assertIn("!=", res_custom.after)
        self.assertNotIn("==", res_custom.after)
        self.assertIn("-> bool:", res_custom.after)

        op = LogicFlip()
        res_op = op(custom_input)
        self.assertEqual(res_op.after, res_custom.after)

        # Regression: ensure type annotations such as '-> bool' or ': bool' are not selected
        annotated_code = (
            "def check_permission(user: str, active: bool) -> bool:\n"
            "    is_admin: bool = user == 'admin'\n"
            "    return active and is_admin\n"
        )
        res_ann = logic_flip(annotated_code)
        self.assertIn("-> bool:", res_ann.after)
        self.assertIn("is_admin: bool =", res_ann.after)
        self.assertIn("user != 'admin'", res_ann.after)

    def test_concurrency_race_operator(self) -> None:
        """Test Class 3: concurrency_race introduces uncoordinated mutable state access."""
        res_default = concurrency_race()
        self.assertIsInstance(res_default, FaultResult)
        self.assertEqual(res_default.class_name, CLASS_3_CONCURRENCY_RACES)
        self.assertEqual(res_default.class_name, "Concurrency Races")
        self.assertTrue(res_default.detectable_by_gate)
        self.assertIn("ConcurrencyConflictError", res_default.expected_failure)

        custom_input = "def increment(self):\n    with self.lock:\n        self.val += 1\n"
        input_copy = custom_input[:]
        res_custom = concurrency_race(custom_input)
        self.assertEqual(custom_input, input_copy, "Input must not be mutated")
        self.assertIn("LOCK REMOVED", res_custom.after)

        op = ConcurrencyRace()
        res_op = op(custom_input)
        self.assertEqual(res_op.after, res_custom.after)

    def test_facade_stub_operator(self) -> None:
        """Test Class 4: facade_stub replaces functional code with mock static return."""
        res_default = facade_stub()
        self.assertIsInstance(res_default, FaultResult)
        self.assertEqual(res_default.class_name, CLASS_4_MOCK_FACADES)
        self.assertEqual(res_default.class_name, "Mock Saturation & Facades")
        self.assertTrue(res_default.detectable_by_gate)
        self.assertIn("MockSaturationError", res_default.expected_failure)
        self.assertIn("return True", res_default.after)

        custom_input = (
            "def query_database(query: str) -> list:\n"
            "    cursor = db.execute(query)\n"
            "    return cursor.fetchall()\n"
        )
        input_copy = custom_input[:]
        res_custom = facade_stub(custom_input)
        self.assertEqual(custom_input, input_copy, "Input must not be mutated")
        self.assertIn("def query_database(query: str) -> list:\n", res_custom.after)
        self.assertIn("return True", res_custom.after)
        self.assertNotIn("cursor.fetchall()", res_custom.after)

        op = FacadeStub()
        res_op = op(custom_input)
        self.assertEqual(res_op.after, res_custom.after)

    def test_scope_violation_operator(self) -> None:
        """Test Class 5: scope_violation introduces unauthorized path traversal/escape."""
        res_default = scope_violation()
        self.assertIsInstance(res_default, FaultResult)
        self.assertEqual(res_default.class_name, CLASS_5_SECURITY_VIOLATIONS)
        self.assertEqual(res_default.class_name, "Security & Boundary Violations")
        self.assertTrue(res_default.detectable_by_gate)
        self.assertIn("SandboxSecurityViolation", res_default.expected_failure)
        self.assertIn("/etc/passwd", res_default.after)

        custom_input = "def write_log(msg: str) -> None:\n    with open('log.txt', 'w') as f: f.write(msg)\n"
        input_copy = custom_input[:]
        res_custom = scope_violation(custom_input)
        self.assertEqual(custom_input, input_copy, "Input must not be mutated")
        self.assertIn("/etc/passwd", res_custom.after)

        op = ScopeViolation()
        res_op = op(custom_input)
        self.assertEqual(res_op.after, res_custom.after)

    def test_unsatisfiable_constraint_operator(self) -> None:
        """Test Class 6: unsatisfiable_constraint injects contradictory assertions."""
        res_default = unsatisfiable_constraint()
        self.assertIsInstance(res_default, FaultResult)
        self.assertEqual(res_default.class_name, CLASS_6_UNSATISFIABLE_CONSTRAINTS)
        self.assertEqual(res_default.class_name, "Unsatisfiable Constraints")
        self.assertTrue(res_default.detectable_by_gate)
        self.assertIn("UnsatisfiableConstraintError", res_default.expected_failure)
        self.assertIn("budget > 100", res_default.after)
        self.assertIn("budget < 10", res_default.after)

        custom_input = "def validate_port(port: int) -> None:\n    assert port > 1024\n"
        input_copy = custom_input[:]
        res_custom = unsatisfiable_constraint(custom_input)
        self.assertEqual(custom_input, input_copy, "Input must not be mutated")
        self.assertIn("budget > 100", res_custom.after)

        op = UnsatisfiableConstraint()
        res_op = op(custom_input)
        self.assertEqual(res_op.after, res_custom.after)

    def test_api_exports(self) -> None:
        """Test public API exports from dafg and dafg.faults, and pure determinism."""
        import dafg.faults as faults_mod

        operators = [
            syntax_break,
            logic_flip,
            concurrency_race,
            facade_stub,
            scope_violation,
            unsatisfiable_constraint,
        ]

        classes = [
            SyntaxBreak,
            LogicFlip,
            ConcurrencyRace,
            FacadeStub,
            ScopeViolation,
            UnsatisfiableConstraint,
        ]

        self.assertTrue(is_dataclass(FaultResult))

        # Check export presence in package namespace and __all__
        for op in operators:
            self.assertTrue(callable(op))
            self.assertTrue(hasattr(dafg, op.__name__))
            self.assertIn(op.__name__, dafg.__all__)
            self.assertTrue(hasattr(faults_mod, op.__name__))
            self.assertIn(op.__name__, faults_mod.__all__)

        for cls in classes:
            self.assertTrue(issubclass(cls, FaultOperator))
            self.assertTrue(hasattr(dafg, cls.__name__))
            self.assertIn(cls.__name__, dafg.__all__)
            self.assertTrue(hasattr(faults_mod, cls.__name__))
            self.assertIn(cls.__name__, faults_mod.__all__)

        constant_names = [
            "CLASS_1_SYNTAX_PACKAGING",
            "CLASS_2_SUBTLE_LOGIC",
            "CLASS_3_CONCURRENCY_RACES",
            "CLASS_4_MOCK_FACADES",
            "CLASS_5_SECURITY_VIOLATIONS",
            "CLASS_6_UNSATISFIABLE_CONSTRAINTS",
        ]
        for const_name in constant_names:
            self.assertTrue(hasattr(dafg, const_name))
            self.assertIn(const_name, dafg.__all__)
            self.assertTrue(hasattr(faults_mod, const_name))
            self.assertIn(const_name, faults_mod.__all__)

        # Verify determinism and input non-mutation across repeated invocations
        test_source = "def example(val):\n    return val == 42\n"
        for op in operators:
            run_1 = op(test_source)
            run_2 = op(test_source)
            self.assertEqual(run_1, run_2, f"Operator {op.__name__} must be deterministic")
            self.assertIsInstance(run_1, FaultResult)
            self.assertIsInstance(run_1.class_name, str)
            self.assertIsInstance(run_1.before, str)
            self.assertIsInstance(run_1.after, str)
            self.assertIsInstance(run_1.detectable_by_gate, bool)
            self.assertIsInstance(run_1.expected_failure, str)

        # Verify container input immutability
        mutable_input = ["def foo(): return 1"]
        original_snapshot = list(mutable_input)
        for op in operators:
            op(mutable_input[0])
            self.assertEqual(mutable_input, original_snapshot, "Mutable input altered")


if __name__ == "__main__":
    unittest.main()
