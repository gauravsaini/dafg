"""Tests for DAFG Streaming Triad: DuplexSocketAdapter & StreamingTokenInspector.

Validates Milestones 3 & 4 of the Full-Duplex Streaming Triad specification:
- DuplexSocketAdapter over Unix Domain Sockets (UDS) and async streams.
- Out-of-band barge-in abort handling (ControlSignal.ABORT).
- Cooperative cancellation using CancellationToken.
- StreamingTokenInspector early challenger interception (OWNS violations, forbidden imports).
- Sub-15ms early-interception latency benchmarks.
- End-to-end full-duplex streaming triad with challenger cutoff.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import pytest

from dafg import (
    BaseRuntimeAdapter,
    CancellationToken,
    ControlSignal,
    DispatchIdentity,
    DuplexSocketAdapter,
    InterceptionEvent,
    RevisionDirective,
    StreamChannel,
    StreamFrame,
    StreamingTokenInspector,
    TaskNode,
    UnixSocketStreamServer,
    check_token_invariants,
)
from dafg.runtime import AgentResponse, FailureClass


# ---------------------------------------------------------------------------
# Milestone 4 Tests: Pure Invariant Checker & StreamingTokenInspector
# ---------------------------------------------------------------------------


def test_pure_invariant_checker_clean_tokens():
    """Verify clean Python code passes invariant checks without violation."""
    code = (
        "import math\n"
        "from dataclasses import dataclass\n"
        "# OWNS: src/module.py\n"
        "def compute(x: float) -> float:\n"
        "    return math.sqrt(x)\n"
    )
    result = check_token_invariants(
        text=code,
        allowed_owns=["src/module.py"],
        forbidden_imports=["os", "subprocess", "socket"],
    )
    assert result is None


def test_pure_invariant_checker_forbidden_imports():
    """Verify immediate detection of forbidden imports across various syntax forms."""
    # 1. Standard import
    res1 = check_token_invariants("import os\n", forbidden_imports=["os", "subprocess"])
    assert res1 is not None
    assert res1[0] == "FORBIDDEN_IMPORT"
    assert res1[2] == FailureClass.PERMISSION_DENIED

    # 2. From import
    res2 = check_token_invariants("from subprocess import Popen\n", forbidden_imports=["os", "subprocess"])
    assert res2 is not None
    assert res2[0] == "FORBIDDEN_IMPORT"
    assert "subprocess" in res2[1]

    # 3. Dynamic import
    res3 = check_token_invariants("mod = __import__('socket')\n", forbidden_imports=["socket"])
    assert res3 is not None
    assert res3[0] == "FORBIDDEN_IMPORT"

    # 4. Semicolon-delimited import
    res4 = check_token_invariants("x = 1; import pty\n", forbidden_imports=["pty"])
    assert res4 is not None
    assert res4[0] == "FORBIDDEN_IMPORT"


def test_pure_invariant_checker_owns_boundary_violation():
    """Verify early detection of undeclared file mutations (OWNS invariant)."""
    # Declared boundary: only src/allowed.py
    allowed = ["src/allowed.py"]

    # 1. Explicit OWNS comment
    res1 = check_token_invariants("OWNS: src/forbidden.py\n", allowed_owns=allowed)
    assert res1 is not None
    assert res1[0] == "OWNS_VIOLATION"
    assert res1[2] == FailureClass.INTERFACE_MISMATCH
    assert "src/forbidden.py" in res1[1]

    # 2. Target declaration
    res2 = check_token_invariants("TARGET: /etc/shadow\n", allowed_owns=allowed)
    assert res2 is not None
    assert res2[0] == "OWNS_VIOLATION"

    # 3. open() write mode
    res3 = check_token_invariants("with open('other/file.py', 'w') as f: pass\n", allowed_owns=allowed)
    assert res3 is not None
    assert res3[0] == "OWNS_VIOLATION"

    # 4. Allowed file does not violate
    res_ok = check_token_invariants("OWNS: src/allowed.py\n", allowed_owns=allowed)
    assert res_ok is None


def test_streaming_token_inspector_frame_inspection():
    """Verify StreamingTokenInspector produces valid CONTROL ABORT frames."""
    inspector = StreamingTokenInspector(
        allowed_owns=["src/dafg/mod.py"],
        forbidden_imports=["subprocess"],
        stream_id=42,
        epoch=3,
    )

    # Clean frame
    frame1 = StreamFrame(
        stream_id=42,
        channel=StreamChannel.DATA,
        seq=1,
        signal=ControlSignal.NOOP,
        epoch=3,
        payload=b"def calc():\n    return 42\n",
    )
    abort1 = inspector.inspect_frame(frame1)
    assert abort1 is None
    assert inspector.interceptions_count == 0

    # Violating frame (forbidden import)
    frame2 = StreamFrame(
        stream_id=42,
        channel=StreamChannel.DATA,
        seq=2,
        signal=ControlSignal.NOOP,
        epoch=3,
        payload=b"import subprocess\nsubprocess.run('ls')\n",
    )
    abort2 = inspector.inspect_frame(frame2)
    assert abort2 is not None
    assert abort2.channel == StreamChannel.CONTROL
    assert abort2.signal == ControlSignal.ABORT
    assert abort2.stream_id == 42
    assert abort2.epoch == 3
    assert inspector.interceptions_count == 1

    # Verify structured RevisionDirective inside abort payload
    directive_dict = json.loads(abort2.payload.decode("utf-8"))
    assert directive_dict["verdict"] == "ABORT"
    assert directive_dict["failure_class"] == FailureClass.PERMISSION_DENIED.value
    assert "subprocess" in directive_dict["feedback"]


def test_streaming_token_inspector_latency_benchmark():
    """Benchmark early-interception latency against the < 15ms target."""
    inspector = StreamingTokenInspector(
        allowed_owns=["src/allowed.py"],
        forbidden_imports=["os", "subprocess", "pty", "shutil"],
        stream_id=1,
        epoch=1,
    )

    tokens = [
        "def compute_summary(data: list) -> dict:\n",
        "    # Step 1: Initialize accumulators\n",
        "    total = 0\n",
        "    for val in data:\n",
        "        total += val\n",
        "    # Step 2: Write result\n",
        "    OWNS: src/forbidden_output.json\n",
    ]

    latencies = []
    violation_found = False

    for idx, token in enumerate(tokens):
        event = inspector.inspect_delta(token, seq=idx)
        latencies.append(event.latency_ms)
        if event.violated:
            violation_found = True
            break

    assert violation_found is True
    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)

    # Sub-15ms target verification (in reality, sub-1ms in Python)
    assert max_latency < 15.0, f"Max latency {max_latency:.3f}ms exceeded 15ms target"
    assert avg_latency < 5.0, f"Average latency {avg_latency:.3f}ms exceeded threshold"


# ---------------------------------------------------------------------------
# Milestone 3 Tests: DuplexSocketAdapter & Unix Domain Sockets
# ---------------------------------------------------------------------------


def test_duplex_socket_adapter_deterministic_simulation():
    """Verify DuplexSocketAdapter deterministic simulation when no UDS is provided."""
    node = TaskNode(
        id="task_streaming",
        title="Streaming Code Generation",
        owns=["src/generated.py"],
        epoch=2,
    )
    adapter = DuplexSocketAdapter()
    resp = adapter.invoke(node, {})

    assert resp.status == "COMPLETED"
    assert resp.epoch == 2
    assert "src/generated.py" in resp.files_modified
    assert adapter.total_frames_received > 0
    assert adapter.total_tokens_consumed > 0


def test_duplex_socket_adapter_simulated_abort():
    """Verify DuplexSocketAdapter handles out-of-band abort and increments epoch."""
    node = TaskNode(
        id="task_abort",
        title="Aborted Generation",
        owns=["src/code.py"],
        epoch=5,
        metadata={"simulate_abort": True, "abort_reason": "Speculation theta breach"},
    )
    adapter = DuplexSocketAdapter()
    resp = adapter.invoke(node, {})

    assert resp.status == "REVISING"
    assert resp.epoch == 6  # Monotonic epoch increment on abort
    assert resp.metadata["interrupted"] is True
    assert resp.metadata["abort_signal"] == int(ControlSignal.ABORT)
    assert resp.revision_directive is not None
    assert resp.revision_directive.verdict == "ABORT"


def test_duplex_socket_adapter_cancellation_token():
    """Verify cooperative cancellation token interrupts execution immediately."""
    cancel_token = CancellationToken()
    node = TaskNode(
        id="task_cancel",
        title="Long-running Streaming Task",
        owns=["src/long.py"],
        epoch=1,
    )
    adapter = DuplexSocketAdapter(cancel_token=cancel_token)

    # Pre-cancel token
    cancel_token.cancel("User initiated barge-in interrupt")
    resp = adapter.invoke(node, {})

    assert resp.status == "REVISING"
    assert resp.epoch == 2
    assert resp.metadata["interrupted"] is True
    assert "User initiated barge-in" in resp.metadata["abort_reason"]


def test_duplex_socket_adapter_over_real_unix_socket(tmp_path: Path):
    """Verify real full-duplex UDS socket communication with token streaming."""
    sock_path = str(tmp_path / "dafg_uds_test.sock")

    async def _run():
        async def mock_engine_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            req_data = await reader.read(4096)
            if len(req_data) >= 12:
                frame, _ = StreamFrame.decode(req_data)
                tokens = [
                    b"def add(a, b):\n",
                    b"    return a + b\n",
                ]
                for seq, chunk in enumerate(tokens, start=1):
                    resp_frame = StreamFrame(
                        stream_id=frame.stream_id,
                        channel=StreamChannel.DATA,
                        seq=seq,
                        signal=ControlSignal.NOOP,
                        epoch=frame.epoch,
                        payload=chunk,
                    )
                    writer.write(resp_frame.encode())
                    await writer.drain()
            writer.close()
            await writer.wait_closed()

        async with UnixSocketStreamServer(sock_path, mock_engine_server):
            node = TaskNode(
                id="t_uds",
                title="Implement add function",
                owns=["src/math_ops.py"],
                epoch=1,
            )
            adapter = DuplexSocketAdapter(socket_path=sock_path)
            resp = await adapter.invoke_stream(node, {})

            assert resp.status == "COMPLETED"
            assert "def add(a, b):" in resp.output
            assert "return a + b" in resp.output
            assert resp.files_modified == ["src/math_ops.py"]
            assert adapter.total_frames_received == 2

    asyncio.run(_run())


def test_duplex_socket_adapter_real_uds_server_abort_signal(tmp_path: Path):
    """Verify UDS server sending an out-of-band ControlSignal.ABORT triggers REVISING."""
    sock_path = str(tmp_path / "dafg_uds_abort.sock")

    async def _run():
        async def aborting_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            req_data = await reader.read(4096)
            if len(req_data) >= 12:
                frame, _ = StreamFrame.decode(req_data)
                f1 = StreamFrame(
                    stream_id=frame.stream_id,
                    channel=StreamChannel.DATA,
                    seq=1,
                    signal=ControlSignal.NOOP,
                    epoch=frame.epoch,
                    payload=b"token1 ",
                )
                writer.write(f1.encode())
                await writer.drain()

                abort_payload = json.dumps({"verdict": "ABORT", "feedback": "KV-cache prefill divergence"}).encode("utf-8")
                f_abort = StreamFrame(
                    stream_id=frame.stream_id,
                    channel=StreamChannel.CONTROL,
                    seq=2,
                    signal=ControlSignal.ABORT,
                    epoch=frame.epoch,
                    payload=abort_payload,
                )
                writer.write(f_abort.encode())
                await writer.drain()
            writer.close()
            await writer.wait_closed()

        async with UnixSocketStreamServer(sock_path, aborting_server):
            node = TaskNode(
                id="t_abort_uds",
                title="Test UDS Abort",
                owns=["src/ops.py"],
                epoch=4,
            )
            adapter = DuplexSocketAdapter(socket_path=sock_path)
            resp = await adapter.invoke_stream(node, {})

            assert resp.status == "REVISING"
            assert resp.epoch == 5  # Incremented
            assert resp.metadata["interrupted"] is True
            assert resp.metadata["abort_signal"] == int(ControlSignal.ABORT)
            assert resp.revision_directive.feedback == "KV-cache prefill divergence"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# End-to-End Triad Integration: Client Adapter + Challenger Interceptor
# ---------------------------------------------------------------------------


def test_full_streaming_triad_challenger_intercept_over_uds(tmp_path: Path):
    """End-to-End Test: Hot-Path Challenger intercepts forbidden import over live UDS.

    Validates that:
    1. Model/Engine streams tokens over DATA channel (0x01).
    2. StreamingTokenInspector catches 'import os' on token arrival.
    3. DuplexSocketAdapter sends 0xABORT back over UDS to stop engine compute.
    4. Adapter halts immediately and returns status='REVISING' with epoch bumped.
    """
    sock_path = str(tmp_path / "dafg_triad_e2e.sock")

    async def _run():
        server_aborted_by_client = False

        async def engine_server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            nonlocal server_aborted_by_client
            req_data = await reader.read(4096)
            if len(req_data) >= 12:
                frame, _ = StreamFrame.decode(req_data)

                tokens = [
                    b"# Generating solution\n",
                    b"import os\n",  # <- Boundary/Security violation!
                    b"os.system('rm -rf /')\n",  # Should never be consumed or generated!
                    b"def done(): pass\n",
                ]
                for seq, token in enumerate(tokens, start=1):
                    data_frame = StreamFrame(
                        stream_id=frame.stream_id,
                        channel=StreamChannel.DATA,
                        seq=seq,
                        signal=ControlSignal.NOOP,
                        epoch=frame.epoch,
                        payload=token,
                    )
                    writer.write(data_frame.encode())
                    await writer.drain()

                    # Check if client sent an abort frame back
                    try:
                        client_reply = await asyncio.wait_for(reader.read(4096), timeout=0.5)
                        if len(client_reply) >= 12:
                            reply_frame, _ = StreamFrame.decode(client_reply)
                            if reply_frame.signal == ControlSignal.ABORT:
                                server_aborted_by_client = True
                                break
                    except Exception:
                        pass

            writer.close()
            await writer.wait_closed()

        inspector = StreamingTokenInspector(
            allowed_owns=["src/safe_module.py"],
            forbidden_imports=["os", "subprocess"],
        )

        async with UnixSocketStreamServer(sock_path, engine_server):
            node = TaskNode(
                id="t_triad",
                title="Dangerous Code Task",
                owns=["src/safe_module.py"],
                epoch=10,
            )
            adapter = DuplexSocketAdapter(socket_path=sock_path, token_inspector=inspector)
            resp = await adapter.invoke_stream(node, {})

            assert resp.status == "REVISING"
            assert resp.epoch == 11
            assert resp.metadata["interrupted"] is True
            assert resp.metadata["interceptor"] == "StreamingTokenInspector"
            assert resp.revision_directive is not None
            assert resp.revision_directive.failure_class == FailureClass.PERMISSION_DENIED
            assert "Forbidden import 'os'" in resp.revision_directive.feedback
            assert "rm -rf" not in resp.output  # Intercepted before destructive token

            # Allow server task loop to complete reading client's abort frame
            await asyncio.sleep(0.05)
            assert server_aborted_by_client is True

    asyncio.run(_run())


def test_cross_paradigm_coercion_with_duplex_socket():
    """Verify BaseRuntimeAdapter.coerce_response handles duplex-socket paradigm jumps."""
    original_resp = AgentResponse(
        output="Streaming result text",
        status="COMPLETED",
        epoch=2,
        files_modified=["src/file.py"],
        metadata={"adapter": "duplex-socket", "frames_received": 10},
    )

    # 1. DuplexSocket -> ToolDispatch
    coerced_disp = BaseRuntimeAdapter.coerce_response(
        original_resp, source_adapter="duplex-socket", target_adapter="tool-dispatch"
    )
    assert coerced_disp.metadata["coerced_output_schema"] == "structured"
    assert coerced_disp.metadata["_coerced_from"] == "duplex-socket"

    # 2. DuplexSocket -> ReAct
    coerced_react = BaseRuntimeAdapter.coerce_response(
        original_resp, source_adapter="duplex-socket", target_adapter="react-state-machine"
    )
    assert coerced_react.metadata["coerced_output_schema"] == "react_trace"
    assert len(coerced_react.metadata["trace"]) == 1

    # 3. IterativeCLI -> DuplexSocket
    cli_resp = AgentResponse(output="CLI output", status="COMPLETED", epoch=1)
    coerced_stream = BaseRuntimeAdapter.coerce_response(
        cli_resp, source_adapter="iterative-cli", target_adapter="duplex-socket"
    )
    assert coerced_stream.metadata["coerced_output_schema"] == "stream_frames"
