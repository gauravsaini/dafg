"""conftest.py — Server lifecycle management, pytest fixtures, and ground-truth telemetry.

Completely isolated from DAFG internal gates. Standard library only.
"""
from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import pytest


# ---------------------------------------------------------------------------
# 1. Ephemeral Port Binding & Process Helpers
# ---------------------------------------------------------------------------

def get_free_port() -> int:
    """Allocate an ephemeral free port from the OS kernel."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for_health(
    base_url: str,
    proc: Optional[subprocess.Popen] = None,
    timeout: float = 5.0,
    initial_delay: float = 0.05,
    backoff_factor: float = 1.5,
    max_delay: float = 0.5,
) -> None:
    """Poll GET /health with exponential backoff until 200 OK or timeout.

    Fast-fails immediately if proc terminates (e.g. syntax error or early crash).
    """
    start = time.monotonic()
    delay = initial_delay
    last_err: Optional[Exception] = None

    while (time.monotonic() - start) < timeout:
        # Fast-fail if subprocess crashed on startup
        if proc is not None and proc.poll() is not None:
            stderr_out = ""
            try:
                _, errs = proc.communicate(timeout=0.2)
                stderr_out = errs.decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(
                f"Server process terminated prematurely with exit code {proc.returncode}.\n"
                f"Stderr:\n{stderr_out}"
            )

        url = f"{base_url.rstrip('/')}/health"
        req = urllib.request.Request(url, headers={"User-Agent": "pytest-healthcheck"})
        try:
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    try:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("status") in ("ok", "healthy"):
                            return
                    except Exception:
                        return
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, http.client.HTTPException) as e:
            last_err = e

        time.sleep(delay)
        delay = min(delay * backoff_factor, max_delay)

    raise TimeoutError(
        f"KV server at {base_url} failed health check within {timeout}s. Last error: {last_err}"
    )


def teardown_process(proc: subprocess.Popen, timeout: float = 2.0) -> None:
    """Clean process group teardown on test session exit: SIGTERM -> wait -> SIGKILL."""
    if proc.poll() is not None:
        return

    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                proc.terminate()
        else:
            proc.terminate()

        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                proc.kill()
        else:
            proc.kill()
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
    finally:
        for stream in (proc.stdout, proc.stderr, proc.stdin):
            if stream:
                try:
                    stream.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# 2. Machine-Readable Telemetry Output Plugin
# ---------------------------------------------------------------------------

class GroundTruthTelemetryPlugin:
    """Collects test results and persists eval_results/ground_truth.json."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.start_time = time.monotonic()

    @pytest.hookimpl
    def pytest_terminal_summary(self, terminalreporter, exitstatus, config) -> None:
        if getattr(config.option, "collectonly", False):
            return
        if getattr(config, "_gt_telemetry_written", False):
            return
        config._gt_telemetry_written = True

        outcomes: Dict[str, str] = {}
        for category in ("passed", "failed", "error", "skipped"):
            for rep in terminalreporter.stats.get(category, []):
                if not hasattr(rep, "nodeid"):
                    continue
                nid = rep.nodeid
                if category in ("failed", "error"):
                    outcomes[nid] = "failed"
                elif nid not in outcomes:
                    outcomes[nid] = category

        passed = sum(1 for v in outcomes.values() if v == "passed")
        num_collected = getattr(terminalreporter, "_numcollected", 0)
        total = max(len(outcomes), num_collected)
        failed = total - passed
        pass_rate = round(passed / total, 4) if total > 0 else 0.0
        duration = round(time.monotonic() - self.start_time, 2)

        data = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": pass_rate,
            "duration_seconds": duration,
        }

        if os.environ.get("GROUND_TRUTH_JSON_PATH"):
            out_path = Path(os.environ["GROUND_TRUTH_JSON_PATH"]).resolve()
        elif os.environ.get("GROUND_TRUTH_OUTPUT_DIR"):
            out_path = Path(os.environ["GROUND_TRUTH_OUTPUT_DIR"]).resolve() / "ground_truth.json"
        else:
            exp_dir = Path(__file__).resolve().parent.parent
            if (exp_dir / "tests_external").is_dir():
                out_path = exp_dir / "eval_results" / "ground_truth.json"
            else:
                out_path = self.workdir / "eval_results" / "ground_truth.json"

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = out_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(out_path)
            terminalreporter.write_line(f"\n[Ground Truth Oracle] Telemetry saved to {out_path}")
            terminalreporter.write_line(
                f"[Ground Truth Oracle] Score: {passed}/{total} passed ({pass_rate * 100:.1f}%)"
            )
        except Exception as e:
            terminalreporter.write_line(f"\n[Ground Truth Oracle] Failed writing telemetry: {e}")


# ---------------------------------------------------------------------------
# 3. Pytest Session Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def register_telemetry_plugin(request):
    """Autouse session fixture ensuring telemetry is recorded."""
    workdir = Path(request.config.rootdir)
    plugin = GroundTruthTelemetryPlugin(workdir)
    request.config.pluginmanager.register(plugin)
    yield


@pytest.hookimpl
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Direct conftest hook for terminal summary."""
    workdir = Path(config.rootdir)
    plugin = GroundTruthTelemetryPlugin(workdir)
    plugin.pytest_terminal_summary(terminalreporter, exitstatus, config)


@pytest.fixture(scope="session")
def kv_server(request):
    """Lifecycle fixture providing base URL for the KV server.

    Supports:
    1. Pre-existing external server via KV_SERVER_URL (does not terminate on exit).
    2. Subprocess spawning with ephemeral port and process group management.
    """
    env_url = os.environ.get("KV_SERVER_URL", "").strip()
    if env_url:
        base_url = env_url.rstrip("/")
        startup_timeout = float(os.environ.get("KV_SERVER_STARTUP_TIMEOUT", 5.0))
        wait_for_health(base_url, timeout=startup_timeout)
        yield base_url
        return

    port = int(os.environ["KV_SERVER_PORT"]) if "KV_SERVER_PORT" in os.environ else get_free_port()

    workdir_candidates = [
        os.environ.get("KV_SERVER_WORKDIR"),
        Path.cwd(),
        Path(__file__).resolve().parent.parent,
        Path(request.config.rootdir),
    ]
    resolved_workdir = None
    for cand in workdir_candidates:
        if cand and (Path(cand) / "src" / "server.py").is_file():
            resolved_workdir = Path(cand).resolve()
            break
    if resolved_workdir is None:
        resolved_workdir = Path(__file__).resolve().parent.parent

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{resolved_workdir}:{env.get('PYTHONPATH', '')}".rstrip(":")
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [
        sys.executable,
        "-m", "src.server",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=str(resolved_workdir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    base_url = f"http://127.0.0.1:{port}"
    startup_timeout = float(os.environ.get("KV_SERVER_STARTUP_TIMEOUT", 5.0))
    try:
        wait_for_health(base_url, proc=proc, timeout=startup_timeout)
        yield base_url
    finally:
        teardown_process(proc, timeout=2.0)


@pytest.fixture(scope="session")
def base_url(kv_server: str) -> str:
    """Convenience alias for kv_server fixture."""
    return kv_server
