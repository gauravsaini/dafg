"""Tests for the Mac-codex eval backend (dafg.codex_mac).

Coverage: CodexMacRunner arg construction, FAILED mapping, --json usage
parsing, and the per-node prompt builder. All Mac SSH is mocked — no real
Mac calls in unit tests.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dafg.codex_mac import (  # noqa: E402
    CODEX_RUN_SH,
    DEFAULT_MAX_CONCURRENT,
    MACSSH,
    CodexMacRunner,
    _parse_jsonl_events,
    build_node_prompt,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

SAMPLE_JSONL = "\n".join([
    json.dumps({"type": "thread.started", "thread_id": "t1"}),
    json.dumps({"type": "turn.started"}),
    json.dumps({"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": "first draft"}}),
    json.dumps({"type": "item.completed", "item": {"id": "i1", "type": "reasoning", "text": "thinking"}}),
    json.dumps({"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "```path:a.py\nX=1\n```"}}),
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20,
                                                    "cached_input_tokens": 10, "reasoning_output_tokens": 5}}),
    json.dumps({"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 10,
                                                    "cached_input_tokens": 0, "reasoning_output_tokens": 2}}),
])


def _ok_completed_process(stdout=b"", stderr=b"", returncode=0):
    return subprocess.CompletedProcess(args=["macssh"], returncode=returncode, stdout=stdout, stderr=stderr)


def _node():
    return SimpleNamespace(id="n1", title="Write models", owns=["src/m.py"])


def _task():
    return SimpleNamespace(title="T", test_fixture="assert True")


# --- arg construction -------------------------------------------------------

def test_remote_command_uses_json_runner_and_no_approve_for_me():
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return _ok_completed_process(stdout=SAMPLE_JSONL.encode())

    runner = CodexMacRunner()
    with mock.patch("dafg.codex_mac.subprocess.run", side_effect=fake_run):
        out = runner.generate("hello")
    assert out["ok"] is True
    # argv[0] is the guarded ssh shim, argv[1] the remote command
    remote_cmds = [c[1] for c in seen]
    assert any(CODEX_RUN_SH in c and "--json" in c for c in remote_cmds), remote_cmds
    assert all("--approve-for-me" not in c for c in remote_cmds)
    assert all(c[0] == MACSSH for c in seen)


def test_prompt_shipped_base64_no_stdin():
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return _ok_completed_process(stdout=SAMPLE_JSONL.encode())

    runner = CodexMacRunner()
    with mock.patch("dafg.codex_mac.subprocess.run", side_effect=fake_run):
        runner.generate("prompt with $pecial `chars`")
    upload_cmd = seen[0][0][1]
    assert "base64 -D -o /tmp/dafg_prompt_" in upload_cmd
    # prompt bytes recoverable from the argv (no shell metachars survive raw)
    b64 = upload_cmd.split("echo ", 1)[1].split(" |", 1)[0]
    assert base64.b64decode(b64).decode() == "prompt with $pecial `chars`"
    # stdin is DEVNULL everywhere, never a pipe (guard preflight slurps pipes)
    assert all(k.get("stdin") == subprocess.DEVNULL for _, k in seen)


def test_installed_recipe_matches_standing_model_rule():
    """The Mac-side recipe must pin gpt-6-luna + max reasoning, no approve-for-me."""
    text = (REPO_ROOT / "assets" / "mac" / "codex_run.sh").read_text()
    code_lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    code = "\n".join(code_lines)
    assert "--skip-git-repo-check" in code
    assert "gpt-6-luna" in code
    assert "model_reasoning_effort" in code and "max" in code
    assert "DEVNULL" in code  # stdin=/dev/null: bare codex exec hangs otherwise
    assert "--approve-for-me" not in code


# --- FAILED mapping ----------------------------------------------------------

def test_nonzero_exit_maps_to_failed():
    def fake_run(cmd, **kwargs):
        if "codex_run.sh" in cmd[1]:
            return _ok_completed_process(stdout=b"partial", stderr=b"boom", returncode=1)
        return _ok_completed_process(stdout=SAMPLE_JSONL.encode())

    runner = CodexMacRunner()
    with mock.patch("dafg.codex_mac.subprocess.run", side_effect=fake_run):
        res = runner.runner_fn("p", _node())
    assert res["status"] == "FAILED"
    assert "rc=1" in res["output"]


def test_timeout_exit_124_maps_to_failed_and_counts():
    def fake_run(cmd, **kwargs):
        if "codex_run.sh" in cmd[1]:
            return _ok_completed_process(stdout=b"", returncode=124)
        return _ok_completed_process(stdout=SAMPLE_JSONL.encode())

    runner = CodexMacRunner()
    with mock.patch("dafg.codex_mac.subprocess.run", side_effect=fake_run):
        res = runner.runner_fn("p", _node())
    assert res["status"] == "FAILED"
    assert "timed out" in res["output"]
    assert runner.timeouts == 1


def test_local_subprocess_timeout_maps_to_failed():
    def fake_run(cmd, **kwargs):
        if "codex_run.sh" in cmd[1]:
            raise subprocess.TimeoutExpired(cmd, timeout=1)
        return _ok_completed_process(stdout=SAMPLE_JSONL.encode())

    runner = CodexMacRunner()
    with mock.patch("dafg.codex_mac.subprocess.run", side_effect=fake_run):
        res = runner.runner_fn("p", _node())
    assert res["status"] == "FAILED"
    assert "local timeout" in res["output"]


def test_no_agent_message_maps_to_failed():
    no_text = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})

    def fake_run(cmd, **kwargs):
        if "codex_run.sh" in cmd[1]:
            return _ok_completed_process(stdout=no_text.encode())
        return _ok_completed_process(stdout=b"")

    runner = CodexMacRunner()
    with mock.patch("dafg.codex_mac.subprocess.run", side_effect=fake_run):
        res = runner.runner_fn("p", _node())
    assert res["status"] == "FAILED"
    assert "no agent_message" in res["output"]


# --- usage parsing -----------------------------------------------------------

def test_parse_jsonl_takes_last_message_and_sums_usage():
    text, usage = _parse_jsonl_events(SAMPLE_JSONL)
    assert text == "```path:a.py\nX=1\n```"
    assert usage == {
        "prompt_tokens": 150,
        "completion_tokens": 30,
        "total_tokens": 180,
        "cached_input_tokens": 10,
        "reasoning_output_tokens": 7,
    }


def test_parse_jsonl_skips_garbage_lines():
    text, usage = _parse_jsonl_events("not json\n" + SAMPLE_JSONL + "\n[broken")
    assert text == "```path:a.py\nX=1\n```"
    assert usage["total_tokens"] == 180


def test_no_usage_events_means_no_usage_key():
    no_usage = json.dumps({"type": "item.completed",
                           "item": {"id": "i", "type": "agent_message", "text": "hi"}})

    def fake_run(cmd, **kwargs):
        if "codex_run.sh" in cmd[1]:
            return _ok_completed_process(stdout=no_usage.encode())
        return _ok_completed_process(stdout=b"")

    runner = CodexMacRunner()
    with mock.patch("dafg.codex_mac.subprocess.run", side_effect=fake_run):
        res = runner.runner_fn("p", _node())
    assert res["status"] == "COMPLETED"
    assert "usage" not in res  # adapter falls back to its stub formula; CPAD unavailable


def test_success_shape_mirrors_real_model():
    def fake_run(cmd, **kwargs):
        return _ok_completed_process(stdout=SAMPLE_JSONL.encode())

    runner = CodexMacRunner()
    with mock.patch("dafg.codex_mac.subprocess.run", side_effect=fake_run):
        res = runner.runner_fn("p", _node())
    assert res["status"] == "COMPLETED"
    assert res["output"] == "```path:a.py\nX=1\n```"
    assert res["files_modified"] == []
    assert res["metadata"]["model"] == "gpt-6-luna"
    assert res["metadata"]["backend"] == "mac-codex"
    assert res["usage"]["total_tokens"] == 180
    assert runner.calls == 1
    assert runner.total_prompt_tokens == 150
    assert runner.total_completion_tokens == 30


# --- misc --------------------------------------------------------------------

def test_default_max_concurrent_is_two():
    assert DEFAULT_MAX_CONCURRENT == 2
    assert CodexMacRunner().max_concurrent == 2


def test_build_node_prompt_has_fence_and_refuse_convention():
    prompt = build_node_prompt(_task(), _node())
    assert "```path:<relative/path.py>" in prompt
    assert "src/m.py" in prompt
    assert "Write models" in prompt
    assert prompt.strip().startswith("You are an autonomous coding agent")
    assert "REFUSE:" in prompt
