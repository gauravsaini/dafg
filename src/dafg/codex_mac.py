"""Mac-codex runner for DAFG evaluation: gpt-6-luna via guarded Mac SSH.

Coverage: real-model backend for the codex pilot
(scripts/run_codex_pilot.py). ``CodexMacRunner.runner_fn(prompt, node)``
is adapter-compatible (same dict shape as ``GeminiRunner.runner_fn``) and
returns TRUE token usage parsed from ``codex exec --json`` event streams, so
CPAD is computed from real numbers.

Transport: every Mac command goes through ``~/workspace/bin/macssh.sh``
(the macssh-guard shim — it refuses unless the remote identifies as
EktaAir.local, guarding the 2026-10-08 local-execution flake). Prompts
travel base64-over-argv because the guard's preflight slurps stdin, and the
model recipe is baked into ``/Users/Shared/dafg-eval/codex_run.sh`` on the
Mac (``codex exec --skip-git-repo-check -m gpt-6-luna
-c 'model_reasoning_effort="max"'`` with stdin=/dev/null; a python watchdog
enforces the timeout since macOS has no ``timeout(1)``).

Concurrency: a process-wide semaphore caps concurrent Mac codex calls
(default 2) — the DAFG graph can dispatch parallel waves inside one trial,
and the pilot runs trials in threads; the semaphore keeps total Mac load
bounded regardless. Kernel tracks on the Mac take priority.

API/transport failures return FAILED dicts, never raise.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

MACSSH = os.path.expanduser("~/workspace/bin/macssh.sh")
MAC_EVAL_DIR = "/Users/Shared/dafg-eval"
CODEX_RUN_SH = f"{MAC_EVAL_DIR}/codex_run.sh"
DEFAULT_MODEL = "gpt-6-luna"
# Per-node codex call budget. Probe (trivial prompt) took ~6s; pilot tasks
# are small stdlib exercises — 600s is generous without inviting hangs.
DEFAULT_TIMEOUT_S = 600
# Extra headroom for SSH handshake + guard preflight on top of the remote
# watchdog (which kills codex at timeout_s).
LOCAL_TIMEOUT_SLACK_S = 180
# Keep eval load well under the Mac's 6-agent ceiling; kernel tracks first.
DEFAULT_MAX_CONCURRENT = 2


def _parse_jsonl_events(text: str) -> Tuple[Optional[str], Optional[Dict[str, int]]]:
    """Extract the last agent message and summed token usage from --json events.

    Usage comes from ``turn.completed`` events; multiple turns are summed so
    CPAD reflects the whole call. Returns (text, usage|None).
    """
    last_text: Optional[str] = None
    total_in = total_out = total_cached = total_reasoning = 0
    saw_usage = False
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                last_text = item["text"]
        if ev.get("type") == "turn.completed":
            usage = ev.get("usage") or {}
            if usage:
                saw_usage = True
                total_in += int(usage.get("input_tokens") or 0)
                total_out += int(usage.get("output_tokens") or 0)
                total_cached += int(usage.get("cached_input_tokens") or 0)
                total_reasoning += int(usage.get("reasoning_output_tokens") or 0)
    result_usage: Optional[Dict[str, int]] = None
    if saw_usage:
        result_usage = {
            "prompt_tokens": total_in,
            "completion_tokens": total_out,
            # total = input + output (output_tokens already includes
            # reasoning tokens per the provider's accounting); reasoning
            # kept as a separate field for transparency.
            "total_tokens": total_in + total_out,
            "cached_input_tokens": total_cached,
            "reasoning_output_tokens": total_reasoning,
        }
    return last_text, result_usage


@dataclass
class CodexMacRunner:
    """gpt-6-luna (max reasoning) on the Mac, via guarded SSH."""

    model: str = DEFAULT_MODEL
    timeout_s: int = DEFAULT_TIMEOUT_S
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    calls: int = field(default=0, init=False)
    timeouts: int = field(default=0, init=False)
    failures: int = field(default=0, init=False)
    total_prompt_tokens: int = field(default=0, init=False)
    total_completion_tokens: int = field(default=0, init=False)
    _sem: threading.Semaphore = field(default=None, init=False, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._sem = threading.Semaphore(self.max_concurrent)

    def _macssh(self, remote_cmd: str, timeout_s: int) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.run(
            [MACSSH, remote_cmd],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_s,
        )

    def _upload_prompt(self, prompt: str, prompt_id: str) -> Optional[str]:
        """Ship the prompt base64-over-argv (guard preflight slurps stdin)."""
        b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
        remote_path = f"/tmp/dafg_prompt_{prompt_id}.txt"
        try:
            proc = self._macssh(f"echo {b64} | base64 -D -o {remote_path}", timeout_s=120)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return f"prompt upload transport: {type(exc).__name__}"
        if proc.returncode != 0:
            return f"prompt upload failed rc={proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[:200]}"
        return None

    def _cleanup_prompt(self, prompt_id: str) -> None:
        try:
            self._macssh(f"rm -f /tmp/dafg_prompt_{prompt_id}.txt", timeout_s=60)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    def generate(self, prompt: str) -> Dict[str, Any]:
        """Run one codex call on the Mac. Never raises.

        Returns {"ok": True, "text": str, "usage": {...}|None} or
        {"ok": False, "error": str}.
        """
        prompt_id = uuid.uuid4().hex[:12]
        with self._sem:
            err = self._upload_prompt(prompt, prompt_id)
            if err is not None:
                self.failures += 1
                return {"ok": False, "error": err}
            try:
                remote = f"{CODEX_RUN_SH} --json /tmp/dafg_prompt_{prompt_id}.txt {self.timeout_s}"
                try:
                    proc = self._macssh(remote, timeout_s=self.timeout_s + LOCAL_TIMEOUT_SLACK_S)
                except subprocess.TimeoutExpired:
                    self.timeouts += 1
                    self.failures += 1
                    return {"ok": False, "error": f"local timeout after {self.timeout_s + LOCAL_TIMEOUT_SLACK_S}s (remote watchdog kills codex at {self.timeout_s}s)"}
                except OSError as exc:
                    self.failures += 1
                    return {"ok": False, "error": f"transport: {exc}"}
                stdout = proc.stdout.decode("utf-8", "replace")
                if proc.returncode == 124:
                    self.timeouts += 1
                    self.failures += 1
                    return {"ok": False, "error": f"codex timed out on Mac after {self.timeout_s}s", "partial_output": stdout[:2000]}
                if proc.returncode != 0:
                    self.failures += 1
                    stderr = proc.stderr.decode("utf-8", "replace")[:500]
                    return {"ok": False, "error": f"codex rc={proc.returncode}: {stderr}", "partial_output": stdout[:2000]}
                text, usage = _parse_jsonl_events(stdout)
                if not text:
                    self.failures += 1
                    return {"ok": False, "error": "no agent_message in codex --json stream", "partial_output": stdout[:2000]}
                self.calls += 1
                if usage:
                    self.total_prompt_tokens += usage["prompt_tokens"]
                    self.total_completion_tokens += usage["completion_tokens"]
                result: Dict[str, Any] = {"ok": True, "text": text}
                if usage is not None:
                    result["usage"] = usage
                return result
            finally:
                self._cleanup_prompt(prompt_id)

    def runner_fn(self, prompt: str, node: Any) -> Dict[str, Any]:
        """Adapter-compatible entry: ``runner_fn(prompt, node) -> dict``.

        Same dict shape as ``GeminiRunner.runner_fn``: output/status/
        files_modified/metadata plus true ``usage`` when the --json stream
        carried it (else the adapter falls back to its stub formula).
        """
        started = time.time()
        result = self.generate(prompt)
        elapsed = round(time.time() - started, 1)
        if not result["ok"]:
            return {
                "output": f"model call failed: {result['error']}",
                "status": "FAILED",
                "files_modified": [],
                "metadata": {
                    "adapter": "iterative-cli",
                    "model": self.model,
                    "backend": "mac-codex",
                    "error": result["error"],
                    "elapsed_s": elapsed,
                },
            }
        payload: Dict[str, Any] = {
            "output": result["text"],
            "status": "COMPLETED",
            "files_modified": [],
            "metadata": {
                "adapter": "iterative-cli",
                "model": self.model,
                "backend": "mac-codex",
                "elapsed_s": elapsed,
            },
        }
        if "usage" in result:
            payload["usage"] = result["usage"]
        return payload


def build_node_prompt(task: Any, node: Any) -> str:
    """Per-node prompt: the adapter invokes runner_fn once per node, so each
    call carries only its own work item (disjoint OWNS). Mirrors the fenced
    `````path:````` block + REFUSE: convention from dafg.baseline."""
    files = "\n".join(f"- {p}" for p in (node.owns or [])) or "- (no files declared)"
    return (
        f"You are an autonomous coding agent. Complete ONLY the work item below,\n"
        f"which is one part of a larger task. Do not attempt other parts.\n\n"
        f"Task: {task.title}\n\n"
        f"Your work item: {node.id}: {node.title}\n\n"
        f"Files you must produce (relative paths, all of them):\n{files}\n\n"
        f"Acceptance fixture for the FULL task (your files must be compatible\n"
        f"with the other files of the task):\n"
        f"```python\n{task.test_fixture}\n```\n\n"
        f"Output ONLY fenced code blocks, one per file, in this exact form:\n"
        f"```path:<relative/path.py>\n<code>\n```\n"
        f"No prose outside the fences. Every file listed above must have\n"
        f"exactly one block.\n\n"
        f"If the work item is impossible, contradictory, or requires APIs that\n"
        f"do not exist, output exactly one line:\n"
        f"REFUSE: <one-line reason>\n"
        f"and no code blocks."
    )
