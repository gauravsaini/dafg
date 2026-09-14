"""Generative and property-based fuzz testing suite for SafeCommandPolicy sandboxing invariants.

Tests 1,000+ permutations across randomized shell metacharacters, forbidden flags,
dynamic execution calls, path traversals, prefix confusion, and randomized inputs.
"""

import random
import string
import pytest
from dafg.organism import SafeCommandPolicy, SecurityPolicyViolationError


def test_fuzz_forbidden_operators_always_rejected():
    """Fuzz: Any command containing forbidden operators must be rejected."""
    runners = list(SafeCommandPolicy.ALLOWED_COMMAND_PREFIXES)
    operators = list(SafeCommandPolicy.FORBIDDEN_OPERATORS)
    random.seed(42)

    for _ in range(300):
        runner = random.choice(runners)
        op = random.choice(operators)
        target = "".join(random.choices(string.ascii_letters + string.digits, k=6))
        payload = "".join(random.choices(string.ascii_letters, k=8))
        
        # Inject operator in different positions
        templates = [
            f"{runner} {target}{op}{payload}",
            f"{runner} {target} {op} {payload}",
            f"{op} {runner} {target}",
            f"{runner} {op}",
            f"{runner}{op}{target}",
        ]
        cmd = random.choice(templates)
        with pytest.raises(SecurityPolicyViolationError):
            SafeCommandPolicy.validate_command(cmd)


def test_fuzz_forbidden_flags_always_rejected():
    """Fuzz: Any command invoking forbidden interpreter flags must be rejected."""
    flags = list(SafeCommandPolicy.FORBIDDEN_INTERPRETER_FLAGS)
    runners = ["node", "python3", "python", "uv run python"]
    random.seed(43)

    for _ in range(200):
        runner = random.choice(runners)
        flag = random.choice(flags)
        payload = "".join(random.choices(string.ascii_letters + string.digits, k=10))
        quote = random.choice(['"', "'", ""])
        cmd = f"{runner} {flag} {quote}{payload}{quote}"

        with pytest.raises(SecurityPolicyViolationError):
            SafeCommandPolicy.validate_command(cmd)


def test_fuzz_path_traversal_targets_always_rejected():
    """Fuzz: Any path traversal or non-alphanumeric target argument must be rejected."""
    runners = [
        "uv run python test_system.py",
        "node test_system.js",
        "python test_system.py",
        "python3 test_system.py",
    ]
    traversal_elements = [
        "../", "..\\", "/etc/passwd", "/tmp", "\\windows",
        "test.js", "dir/sub", "../secret", "./target",
        "..", "/root", "~/", "target/../escape", "file.py"
    ]
    random.seed(44)

    for _ in range(250):
        runner = random.choice(runners)
        traversal = random.choice(traversal_elements)
        noise = "".join(random.choices(string.ascii_letters + string.digits, k=4))
        target = f"{noise}{traversal}{noise}"
        cmd = f"{runner} {target}"

        with pytest.raises(SecurityPolicyViolationError):
            SafeCommandPolicy.validate_command(cmd)


def test_fuzz_prefix_confusion_always_rejected():
    """Fuzz: Tampered command prefixes or binary name extensions must be rejected."""
    prefixes = list(SafeCommandPolicy.ALLOWED_COMMAND_PREFIXES)
    random.seed(45)

    for _ in range(150):
        prefix = random.choice(prefixes)
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        tampered_prefix = f"{prefix}_{suffix}"
        cmd = f"{tampered_prefix} CORE"

        with pytest.raises(SecurityPolicyViolationError):
            SafeCommandPolicy.validate_command(cmd)


def test_fuzz_random_garbage_never_authorizes_unauthorized():
    """Fuzz: Randomized arbitrary text must be rejected unless strictly conforming."""
    random.seed(46)
    chars = string.ascii_letters + string.digits + string.punctuation + " \t\n\x00"

    for _ in range(200):
        length = random.randint(1, 60)
        random_cmd = "".join(random.choice(chars) for _ in range(length))

        # Unless it accidentally formed a valid authorized command, it must raise
        try:
            SafeCommandPolicy.validate_command(random_cmd)
            # If it succeeded, verify it actually matches an allowed prefix and safe args
            matched = any(
                random_cmd.strip() == p or random_cmd.strip().startswith(p + " ")
                for p in SafeCommandPolicy.ALLOWED_COMMAND_PREFIXES
            )
            assert matched, f"Random command '{random_cmd}' was erroneously authorized"
        except SecurityPolicyViolationError:
            pass


def test_property_valid_commands_always_pass():
    """Property: 100 randomized strictly-valid commands must always be authorized."""
    runners = [
        "uv run python test_system.py",
        "node test_system.js",
        "python test_system.py",
        "python3 test_system.py",
        "uv run python test_service.py",
        "node test_service.js",
    ]
    random.seed(47)

    for _ in range(100):
        runner = random.choice(runners)
        # Valid alphanumeric targets matching ^[a-zA-Z0-9_-]+$
        target_name = "".join(
            random.choices(string.ascii_letters + string.digits + "_-", k=random.randint(2, 12))
        )
        cmd = f"{runner} {target_name}"
        # Must authorize cleanly without error
        SafeCommandPolicy.validate_command(cmd)
