"""OS Containment Sandbox for Subprocess Execution.

Provides containment boundaries for executing autonomously authored checks and
agent commands. Isolates working directories, strips sensitive credentials,
confines filesystem access, sets resource limits, and manages process groups.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import resource
except ImportError:
    resource = None  # Windows support fallback


class SandboxSecurityViolation(Exception):
    """Raised when an execution violates sandbox containment boundaries."""
    pass


class SubprocessSandbox:
    """Encapsulates OS-level execution containment."""

    SENSITIVE_ENV_PATTERNS = (
        re.compile(r".*(KEY|SECRET|TOKEN|CREDENTIAL|PASSWORD|AUTH).*", re.IGNORECASE),
        re.compile(r"^(AWS_|GITHUB_|SSH_|DAFG_|OPENAI_|ANTHROPIC_|GEMINI_).*", re.IGNORECASE),
    )

    ALLOWED_ENV_VARS: Set[str] = {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "VIRTUAL_ENV",
        "PYTHONDONTWRITEBYTECODE",
    }

    FORBIDDEN_PATH_PREFIXES: Tuple[str, ...] = (
        "/proc",
        "/dev",
        "/etc",
        "/sys",
        "/private/etc",
    )

    def __init__(
        self,
        workdir: Path,
        timeout: float = 30.0,
        cpu_time_limit: int = 30,
        max_output_bytes: int = 50 * 1024 * 1024,  # 50MB
        max_processes: int = 64,
        allow_network: bool = False,
    ):
        self.workdir = Path(workdir).resolve()
        self.timeout = timeout
        self.cpu_time_limit = cpu_time_limit
        self.max_output_bytes = max_output_bytes
        self.max_processes = max_processes
        self.allow_network = allow_network
        self._sandbox_home: Optional[Path] = None
        self._sandbox_tmp: Optional[Path] = None

    def _get_or_create_sandbox_home(self) -> Path:
        if self._sandbox_home is None or not self._sandbox_home.exists():
            sb_dir = self.workdir / ".sandbox_home"
            sb_dir.mkdir(parents=True, exist_ok=True)
            self._sandbox_home = sb_dir
        return self._sandbox_home

    def _get_or_create_sandbox_tmp(self) -> Path:
        if self._sandbox_tmp is None or not self._sandbox_tmp.exists():
            sb_dir = self.workdir / ".sandbox_tmp"
            sb_dir.mkdir(parents=True, exist_ok=True)
            self._sandbox_tmp = sb_dir
        return self._sandbox_tmp

    def build_sanitized_env(self, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Construct a clean, credential-free environment dictionary."""
        clean_env: Dict[str, str] = {}

        # 1. Pull strictly allowed system variables (deny ambient by default)
        for k in self.ALLOWED_ENV_VARS:
            if k in os.environ:
                clean_env[k] = os.environ[k]

        # 2. Add safe essentials if missing
        if "PATH" not in clean_env and "PATH" in os.environ:
            clean_env["PATH"] = os.environ["PATH"]

        # 3. Strip any leaked sensitive patterns
        keys_to_remove = []
        for k in clean_env:
            if any(p.match(k) for p in self.SENSITIVE_ENV_PATTERNS):
                keys_to_remove.append(k)
        for k in keys_to_remove:
            del clean_env[k]

        # 4. Redirect $HOME and temporary directories to isolated disposable sandbox paths
        sb_home = str(self._get_or_create_sandbox_home().resolve())
        sb_tmp = str(self._get_or_create_sandbox_tmp().resolve())
        clean_env["HOME"] = sb_home
        clean_env["USERPROFILE"] = sb_home
        clean_env["TMPDIR"] = sb_tmp
        clean_env["TEMP"] = sb_tmp
        clean_env["TMP"] = sb_tmp
        clean_env["PWD"] = str(self.workdir.resolve())

        # 5. Network Isolation: null-route outbound proxy & package index callouts
        if not self.allow_network:
            clean_env["HTTP_PROXY"] = "http://127.0.0.1:0"
            clean_env["HTTPS_PROXY"] = "http://127.0.0.1:0"
            clean_env["ALL_PROXY"] = "socks5://127.0.0.1:0"
            clean_env["NO_PROXY"] = ""
            clean_env["PIP_NO_INDEX"] = "1"
            clean_env["NPM_CONFIG_OFFLINE"] = "true"

        # 6. Disable telemetry/network callouts from common tools where possible
        clean_env["DO_NOT_TRACK"] = "1"
        clean_env["NEXT_TELEMETRY_DISABLED"] = "1"
        clean_env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"

        if extra_env:
            for k, v in extra_env.items():
                if not any(p.match(k) for p in self.SENSITIVE_ENV_PATTERNS):
                    clean_env[k] = v

        return clean_env

    def validate_target_path(self, target_path: Path) -> Path:
        """Ensure target path does not escape sandbox workdir via symlinks, hardlinks, or traversal."""
        path_str = str(target_path)
        for forbidden in self.FORBIDDEN_PATH_PREFIXES:
            if path_str == forbidden or path_str.startswith(forbidden + "/"):
                raise SandboxSecurityViolation(
                    f"Forbidden system path blocked: target '{target_path}' resides in protected OS hierarchy"
                )

        resolved = target_path.resolve()
        try:
            resolved.relative_to(self.workdir)
        except ValueError:
            raise SandboxSecurityViolation(
                f"Path traversal blocked: target '{target_path}' resolves outside sandbox root '{self.workdir}'"
            )

        # Check for hardlink escaping to external inodes
        if resolved.exists():
            stat = resolved.stat()
            if stat.st_nlink > 1 and stat.st_dev != self.workdir.stat().st_dev:
                raise SandboxSecurityViolation(
                    f"Hardlink escape blocked: target '{target_path}' links across filesystem devices"
                )

        return resolved

    def run(
        self,
        command: str,
        cwd: Optional[Path] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> subprocess.CompletedProcess[str]:
        """Execute command contained inside the sandbox."""
        exec_cwd = (cwd or self.workdir).resolve()
        self.validate_target_path(exec_cwd)

        clean_env = self.build_sanitized_env(extra_env)

        def _preexec():
            os.setsid()
            if resource is not None:
                try:
                    resource.setrlimit(resource.RLIMIT_CPU, (self.cpu_time_limit, self.cpu_time_limit + 5))
                except (ValueError, OSError):
                    pass
                try:
                    resource.setrlimit(resource.RLIMIT_FSIZE, (self.max_output_bytes, self.max_output_bytes))
                except (ValueError, OSError):
                    pass
                if sys.platform != "darwin" and hasattr(resource, "RLIMIT_NPROC") and self.max_processes > 0:
                    try:
                        resource.setrlimit(resource.RLIMIT_NPROC, (self.max_processes, self.max_processes))
                    except (ValueError, OSError):
                        pass

        proc = None
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=str(exec_cwd),
                env=clean_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=_preexec if os.name != 'nt' else None,
            )
            stdout, stderr = proc.communicate(timeout=self.timeout)
            return subprocess.CompletedProcess(
                args=command,
                returncode=proc.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired:
            if proc is not None:
                try:
                    if os.name != 'nt':
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                except OSError:
                    pass
                proc.communicate()
            raise TimeoutError(f"Sandboxed command exceeded timeout of {self.timeout}s: '{command}'")
        except Exception as e:
            if proc is not None:
                try:
                    if os.name != 'nt':
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                except OSError:
                    pass
            raise e
