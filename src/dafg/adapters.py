"""Decoupled Execution Architecture Adapters for DAFG v0.3.

Provides concrete execution adapters representing fundamentally different
agent loop architectures (Iterative CLI, Tool Dispatch / Function Calling,
and ReAct State Machine) to test true cross-runtime transferability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
import json
import os
import socket
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Sequence, Set, Tuple

from dafg.protocol import DispatchIdentity
from dafg.runtime import AgentResponse, FailureClass, RevisionDirective, TaskNode
from dafg.transport import (
    ControlSignal,
    StreamChannel,
    StreamFrame,
    decode_all_frames,
    encode_frames,
)


class BaseRuntimeAdapter(ABC):
    """Abstract protocol for external agent execution architectures."""

    def __init__(self, name: str):
        self.name = name
        self.total_invocations: int = 0
        self.total_tokens_consumed: int = 0

    @abstractmethod
    def invoke(self, node: TaskNode, context: Dict[str, Any]) -> AgentResponse:
        """Execute a task node within this agent architecture."""
        pass

    def check_refusal(self, node: TaskNode, context: Optional[Dict[str, Any]] = None) -> Optional[AgentResponse]:
        """Assess task feasibility and permissions; honestly refuse if unfulfillable.
        
        Refusal is determined strictly through protocol constraints (missing authorization)
        or explicit structural impossibility declarations, never by keyword matching on title.
        """
        disp_raw = context.get("dispatch_identity") if context else getattr(node, "active_dispatch", None)
        disp = DispatchIdentity.from_dict(disp_raw) if isinstance(disp_raw, dict) else disp_raw
        epoch = getattr(disp, "epoch", getattr(node, "epoch", 1)) if disp else getattr(node, "epoch", 1)
        if node.requires_permissions and not node.metadata.get("authorized"):
            return AgentResponse(
                output=f"Honest refusal: Task '{node.title}' requires elevated permissions or authorization.",
                status="BLOCKED",
                metadata={"refusal_class": "MISSING_AUTHORIZATION", "adapter": self.name},
                epoch=epoch,
                dispatch_identity=disp,
            )
        req_caps = node.metadata.get("required_capabilities", [])
        if isinstance(req_caps, str):
            req_caps = [req_caps]
        unsupported = [c for c in req_caps if c in ("uncomputable", "hypercomputation", "oracle", "quantum_oracle")]
        if unsupported or node.metadata.get("is_impossible"):
            reason = f"Required capability not available: {', '.join(unsupported)}" if unsupported else f"Task '{node.title}' is mathematically or architecturally impossible to fulfill."
            return AgentResponse(
                output=f"Honest refusal: {reason}",
                status="BLOCKED",
                metadata={"refusal_class": "UNAVAILABLE_CAPABILITY", "adapter": self.name},
                epoch=epoch,
                dispatch_identity=disp,
            )
        return None

    @staticmethod
    def coerce_response(
        response: AgentResponse,
        source_adapter: str,
        target_adapter: str,
    ) -> AgentResponse:
        """Normalize an AgentResponse produced by one adapter paradigm for consumption
        by another, performing cross-paradigm schema coercion.

        CLI output is raw text that needs structured extraction.
        ToolDispatch output carries structured tool_calls metadata.
        ReAct output carries a state trace.

        Returns a new AgentResponse with metadata augmented for the target paradigm.
        """
        coerced_meta = dict(response.metadata)
        coerced_meta["_coerced_from"] = source_adapter
        coerced_meta["_coerced_to"] = target_adapter

        if source_adapter == "iterative-cli" and target_adapter == "tool-dispatch":
            # CLI→ToolDispatch: parse raw text output into structured tool_call form
            coerced_meta["tool_calls_count"] = coerced_meta.get("tool_calls_count", 0)
            coerced_meta["coerced_output_schema"] = "structured"
            if "commands_run" in coerced_meta:
                coerced_meta["tool_calls_count"] = coerced_meta["commands_run"]

        elif source_adapter == "tool-dispatch" and target_adapter == "react-state-machine":
            # ToolDispatch→ReAct: wrap structured calls into thought-action-observation trace
            tc = coerced_meta.get("tool_calls_count", 0)
            coerced_meta["trace"] = [
                {"turn": "1", "thought": "Ingesting tool dispatch output",
                 "action": "consume_upstream", "observation": f"Received {tc} tool calls"}
            ]
            coerced_meta["coerced_output_schema"] = "react_trace"

        elif source_adapter == "iterative-cli" and target_adapter == "react-state-machine":
            # CLI→ReAct: full paradigm jump
            coerced_meta["trace"] = [
                {"turn": "1", "thought": "Parsing CLI text output",
                 "action": "parse_stdout", "observation": response.output[:200]}
            ]
            coerced_meta["coerced_output_schema"] = "react_trace"

        elif source_adapter == "react-state-machine" and target_adapter == "tool-dispatch":
            # ReAct→ToolDispatch: extract action calls from trace
            trace = coerced_meta.get("trace", [])
            coerced_meta["tool_calls_count"] = len(trace)
            coerced_meta["coerced_output_schema"] = "structured"

        elif source_adapter == "react-state-machine" and target_adapter == "iterative-cli":
            # ReAct→CLI: flatten trace to text
            coerced_meta["coerced_output_schema"] = "raw_text"

        elif source_adapter == "tool-dispatch" and target_adapter == "iterative-cli":
            # ToolDispatch→CLI: flatten structured calls to text
            coerced_meta["coerced_output_schema"] = "raw_text"

        elif source_adapter == "duplex-socket" and target_adapter == "tool-dispatch":
            coerced_meta["tool_calls_count"] = 0
            coerced_meta["coerced_output_schema"] = "structured"

        elif source_adapter == "duplex-socket" and target_adapter == "react-state-machine":
            coerced_meta["trace"] = [
                {"turn": "1", "thought": "Ingesting duplex streaming output",
                 "action": "consume_stream", "observation": response.output[:200]}
            ]
            coerced_meta["coerced_output_schema"] = "react_trace"

        elif source_adapter == "duplex-socket" and target_adapter == "iterative-cli":
            coerced_meta["coerced_output_schema"] = "raw_text"

        elif source_adapter in ("iterative-cli", "tool-dispatch", "react-state-machine") and target_adapter == "duplex-socket":
            coerced_meta["coerced_output_schema"] = "stream_frames"
            coerced_meta["frames_count"] = 1

        return AgentResponse(
            output=response.output,
            status=response.status,
            epoch=response.epoch,
            dispatch_identity=response.dispatch_identity,
            needs=list(response.needs),
            spawn_children=list(response.spawn_children),
            files_modified=list(response.files_modified),
            metadata=coerced_meta,
            revision_directive=response.revision_directive,
            published_contracts=list(response.published_contracts),
            criterion_evidence=list(response.criterion_evidence),
        )


class IterativeCLIAdapter(BaseRuntimeAdapter):
    """Simulates an iterative command-line agent (e.g. Agy, Bash-driven agent).
    
    Sequential command execution with text stdout parsing; vulnerable to
    shell errors, command exit codes, and raw text ambiguities.
    """

    def __init__(
        self,
        name: str = "iterative-cli",
        runner_fn: Optional[Callable[[str, TaskNode], Dict[str, Any]]] = None,
    ):
        super().__init__(name)
        self.runner_fn = runner_fn
        self.command_history: List[str] = []

    def invoke(self, node: TaskNode, context: Dict[str, Any]) -> AgentResponse:
        self.total_invocations += 1
        prompt_tokens = len(node.title) * 4 + 180
        self.total_tokens_consumed += prompt_tokens

        refusal = self.check_refusal(node, context)
        if refusal:
            return refusal

        disp_raw = context.get("dispatch_identity") if context else getattr(node, "active_dispatch", None)
        disp = DispatchIdentity.from_dict(disp_raw) if isinstance(disp_raw, dict) else disp_raw
        epoch = getattr(disp, "epoch", getattr(node, "epoch", 1)) if disp else getattr(node, "epoch", 1)

        files_modified = list(node.owns)
        cmd = f"run_task_{node.id}"
        self.command_history.append(cmd)
        self.total_tokens_consumed += 60

        if self.runner_fn:
            res = self.runner_fn(f"CLI session completed for {node.id}: {node.title}", node)
            if isinstance(res, AgentResponse):
                if res.epoch is None:
                    res.epoch = epoch
                if res.dispatch_identity is None:
                    res.dispatch_identity = disp
                return res
            result = res if isinstance(res, dict) else {}
            return AgentResponse(
                output=result.get("output", f"CLI completed {node.id}"),
                status=result.get("status", "COMPLETED"),
                files_modified=result.get("files_modified", files_modified),
                metadata=result.get("metadata", {"adapter": self.name}),
                epoch=epoch,
                dispatch_identity=disp,
            )

        # Structural vulnerability 1: hostile flaky tools / shell command failure
        if node.metadata.get("flaky_tools") or node.metadata.get("flaky_environment"):
            return AgentResponse(
                output=f"CLI execution failed: command '{cmd}' exited with code 1 (unhandled shell error)",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "commands_run": len(self.command_history), "exit_code": 1},
                epoch=epoch,
                dispatch_identity=disp,
            )

        # Structural vulnerability 2: raw text ambiguities in stdout
        if node.metadata.get("raw_text_ambiguity") or node.metadata.get("ambiguous_output") or (node.ambiguity_score > 0.5):
            return AgentResponse(
                output=f"CLI parsing error: stdout response from '{cmd}' is ambiguous and could not be parsed deterministically",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "error": "RAW_TEXT_AMBIGUITY", "ambiguity_score": node.ambiguity_score},
                epoch=epoch,
                dispatch_identity=disp,
            )

        output_text = f"CLI session completed for {node.id}: {node.title}"
        return AgentResponse(
            output=output_text,
            status="COMPLETED",
            files_modified=files_modified,
            metadata={"adapter": self.name, "commands_run": len(self.command_history)},
            epoch=epoch,
            dispatch_identity=disp,
        )


class ToolDispatchAdapter(BaseRuntimeAdapter):
    """Simulates function-calling / tool dispatch architecture (e.g. Claude Code, Codex).
    
    Structured schema-driven function calling; sensitive to argument validation,
    tool availability, and schema mismatches.
    """

    def __init__(
        self,
        name: str = "tool-dispatch",
        available_tools: Optional[Dict[str, Callable[..., Any]]] = None,
    ):
        super().__init__(name)
        self.available_tools = available_tools or {
            "view_file": lambda path: f"Content of {path}",
            "edit_file": lambda path, content: True,
            "run_test": lambda cmd: "1 passed",
        }
        self.dispatched_tool_calls: List[Dict[str, Any]] = []

    def invoke(self, node: TaskNode, context: Dict[str, Any]) -> AgentResponse:
        self.total_invocations += 1

        refusal = self.check_refusal(node, context)
        if refusal:
            self.total_tokens_consumed += 120
            return refusal

        disp_raw = context.get("dispatch_identity") if context else getattr(node, "active_dispatch", None)
        disp = DispatchIdentity.from_dict(disp_raw) if isinstance(disp_raw, dict) else disp_raw
        epoch = getattr(disp, "epoch", getattr(node, "epoch", 1)) if disp else getattr(node, "epoch", 1)

        # Role-scoped tool definitions to prevent whole-catalog schema re-transmission
        scoped_tools = self.available_tools
        if node.role in ("reviewer", "tester"):
            scoped_tools = {k: v for k, v in self.available_tools.items() if k in ("view_file", "run_test")}
        elif node.role == "planner":
            scoped_tools = {k: v for k, v in self.available_tools.items() if k in ("view_file",)}

        # Tool dispatch overhead token estimation
        tokens = len(node.title) * 4 + len(scoped_tools) * 45 + 180
        self.total_tokens_consumed += tokens

        # Structural vulnerability 1: missing required tool for declared file modifications
        if node.owns and "edit_file" not in scoped_tools:
            return AgentResponse(
                output=f"ToolDispatch failed: 'edit_file' not available in scoped tools for role '{node.role}'",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "error": "MISSING_TOOL"},
                epoch=epoch,
                dispatch_identity=disp,
            )

        # Structural vulnerability 1b: explicit tool unavailability
        if node.metadata.get("missing_tool") or node.metadata.get("tool_unavailable"):
            req_tool = node.metadata.get("required_tool", "custom_tool")
            return AgentResponse(
                output=f"ToolDispatch failed: required tool '{req_tool}' not available in tool registry",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "error": "MISSING_TOOL", "required_tool": req_tool},
                epoch=epoch,
                dispatch_identity=disp,
            )

        # Structural vulnerability 2: Schema mutation sensitivity
        if node.metadata.get("schema_mutation"):
            return AgentResponse(
                output=f"ToolDispatch SchemaValidationError: payload schema mutated; parameter types rejected on {node.id}",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "error": "SCHEMA_VALIDATION_ERROR"},
                epoch=epoch,
                dispatch_identity=disp,
            )

        # Structural vulnerability 3: Argument type validation failure
        if node.metadata.get("invalid_arguments") or node.metadata.get("argument_validation_error"):
            return AgentResponse(
                output=f"ToolDispatch ArgumentValidationError: arguments failed schema type validation on {node.id}",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "error": "ARGUMENT_VALIDATION_ERROR"},
                epoch=epoch,
                dispatch_identity=disp,
            )

        # Simulate tool calls for node's declared files
        for f in node.owns:
            tool_call = {"tool": "edit_file", "path": f}
            self.dispatched_tool_calls.append(tool_call)

        return AgentResponse(
            output=f"ToolDispatch completed {len(node.owns)} tool calls for {node.id}",
            status="COMPLETED",
            files_modified=list(node.owns),
            metadata={"adapter": self.name, "tool_calls_count": len(self.dispatched_tool_calls)},
            epoch=epoch,
            dispatch_identity=disp,
        )


class ReActStateAdapter(BaseRuntimeAdapter):
    """Simulates a ReAct state-machine loop (e.g. LangGraph / ReAct agent).
    
    Thought-Action-Observation loop; subject to reasoning budget limits,
    step loops, and observation truncation.

    KillSwitch parameters:
      kill_n: max consecutive no-progress turns before aborting (default: 0 = disabled)
      spec_gap_theta: speculation gap threshold (0.0-1.0). When the ratio of
          speculative (non-progressing) turns to total turns exceeds this,
          the loop aborts. Default 0.0 = disabled.
      kill_epsilon: minimum token delta per turn (default: 0.0 = disabled).
          When the per-turn token increment falls below this threshold, the
          turn is flagged as below-epsilon and consecutive below-epsilon turns
          trigger an abort. This catches dead-end loops that burn tokens
          without meaningful progress, converting horizon exhaustion into
          fast-fail REJECTED states.
    """

    def __init__(
        self,
        name: str = "react-state-machine",
        max_turns: int = 5,
        kill_n: int = 0,
        spec_gap_theta: float = 0.0,
        kill_epsilon: float = 0.0,
    ):
        super().__init__(name)
        self.max_turns = max_turns
        self.kill_n = kill_n
        self.spec_gap_theta = spec_gap_theta
        self.kill_epsilon = kill_epsilon
        self.state_trace: List[Dict[str, str]] = []
        self.killswitch_activations: int = 0

    def invoke(self, node: TaskNode, context: Dict[str, Any]) -> AgentResponse:
        self.total_invocations += 1

        refusal = self.check_refusal(node, context)
        if refusal:
            self.total_tokens_consumed += 140
            return refusal

        disp_raw = context.get("dispatch_identity") if context else getattr(node, "active_dispatch", None)
        disp = DispatchIdentity.from_dict(disp_raw) if isinstance(disp_raw, dict) else disp_raw
        epoch = getattr(disp, "epoch", getattr(node, "epoch", 1)) if disp else getattr(node, "epoch", 1)

        # Compute effective horizon depth from node.depth, metadata, or dependency graph in context
        effective_depth = node.depth
        if effective_depth == 0 and context.get("graph") and node.needs:
            graph = context["graph"]
            def _get_chain_len(nid: str, visited: Set[str]) -> int:
                if nid in visited or nid not in graph.nodes:
                    return 0
                visited.add(nid)
                n = graph.nodes[nid]
                if not n.needs:
                    return 1
                return 1 + max((_get_chain_len(dep, visited.copy()) for dep in n.needs if dep in graph.nodes), default=0)
            effective_depth = _get_chain_len(node.id, set()) - 1

        # Structural characteristic 1: Reasoning budget limit on deep horizons (depth >= 4)
        is_deep_horizon = (
            (node.metadata.get("difficulty_dimension") == "horizon" or bool(node.metadata.get("exhaust_reasoning_budget")))
            and (node.depth >= 4 or effective_depth >= 4 or len(node.needs) >= 4)
        )

        turn_tokens = 180
        turns_used = 0
        is_flaky = bool(node.metadata.get("flaky_tools") or node.metadata.get("flaky_environment"))
        num_turns = min(self.max_turns, 3 if is_flaky else 2)

        # Structural characteristic 2: Step loops where thought-action cycles repeatedly
        if node.metadata.get("step_loop") or node.metadata.get("infinite_step_loop"):
            self.total_tokens_consumed += turn_tokens * self.max_turns
            return AgentResponse(
                output=f"ReAct step loop detected: repetitive actions cycled without progress after {self.max_turns} turns on {node.id}",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "error": "STEP_LOOP_DETECTED", "turns_used": self.max_turns},
                epoch=epoch,
                dispatch_identity=disp,
            )

        # Structural characteristic 3: Observation truncation losing critical context
        if node.metadata.get("observation_truncation"):
            return AgentResponse(
                output=f"ReAct observation truncation: observation buffer exceeded limit and was truncated on {node.id}",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "error": "OBSERVATION_TRUNCATED"},
                epoch=epoch,
                dispatch_identity=disp,
            )

        # KillSwitch state tracking
        consecutive_no_progress = 0
        speculative_turns = 0

        prev_tokens = self.total_tokens_consumed
        consecutive_below_epsilon = 0

        for turn in range(num_turns):
            turns_used += 1
            token_increment = turn_tokens + (turn * 50)
            self.total_tokens_consumed += token_increment
            obs = "Transient error, retrying" if (is_flaky and turn == 0) else "Step passed"

            # Determine if this turn made progress
            made_progress = (obs == "Step passed")
            if not made_progress:
                consecutive_no_progress += 1
                speculative_turns += 1
            else:
                consecutive_no_progress = 0

            entry = {
                "turn": str(turn + 1),
                "thought": f"Assessing {node.title} requirements (turn {turn + 1})",
                "action": f"modify_target_{turn}",
                "observation": obs,
            }
            # Scratchpad compaction: preserve rolling active window
            if len(self.state_trace) >= 2:
                self.state_trace.pop(0)
            self.state_trace.append(entry)

            # KillSwitch: kill_n consecutive no-progress check
            if self.kill_n > 0 and consecutive_no_progress >= self.kill_n:
                self.killswitch_activations += 1
                return AgentResponse(
                    output=f"KillSwitch(kill_n={self.kill_n}): {consecutive_no_progress} consecutive no-progress turns on {node.id}",
                    status="FAILED",
                    files_modified=[],
                    metadata={
                        "adapter": self.name,
                        "error": "KILLSWITCH_KILL_N",
                        "kill_n": self.kill_n,
                        "consecutive_no_progress": consecutive_no_progress,
                        "turns_used": turns_used,
                    },
                    epoch=epoch,
                    dispatch_identity=disp,
                )

            # KillSwitch: spec_gap_theta speculation ratio check
            if self.spec_gap_theta > 0.0 and turns_used > 0:
                spec_ratio = speculative_turns / turns_used
                if spec_ratio > self.spec_gap_theta:
                    self.killswitch_activations += 1
                    return AgentResponse(
                        output=f"KillSwitch(spec_gap_θ={self.spec_gap_theta}): speculation ratio {spec_ratio:.2f} exceeded threshold on {node.id}",
                        status="FAILED",
                        files_modified=[],
                        metadata={
                            "adapter": self.name,
                            "error": "KILLSWITCH_SPEC_GAP",
                            "spec_gap_theta": self.spec_gap_theta,
                            "spec_ratio": spec_ratio,
                            "speculative_turns": speculative_turns,
                            "turns_used": turns_used,
                        },
                        epoch=epoch,
                        dispatch_identity=disp,
                    )

            # KillSwitch: kill_epsilon minimum token delta check
            if self.kill_epsilon > 0.0:
                if token_increment < self.kill_epsilon:
                    consecutive_below_epsilon += 1
                else:
                    consecutive_below_epsilon = 0
                # Trigger on first below-epsilon turn (dead-end detection)
                if consecutive_below_epsilon >= 1:
                    self.killswitch_activations += 1
                    return AgentResponse(
                        output=f"KillSwitch(kill_ε={self.kill_epsilon}): token delta {token_increment} below epsilon on {node.id}",
                        status="FAILED",
                        files_modified=[],
                        metadata={
                            "adapter": self.name,
                            "error": "KILLSWITCH_KILL_EPSILON",
                            "kill_epsilon": self.kill_epsilon,
                            "token_delta": token_increment,
                            "consecutive_below_epsilon": consecutive_below_epsilon,
                            "turns_used": turns_used,
                        },
                        epoch=epoch,
                        dispatch_identity=disp,
                    )

        if is_deep_horizon:
            # ReAct exceeded its turn budget on deep horizon planning
            self.total_tokens_consumed += turn_tokens * (self.max_turns - turns_used)
            return AgentResponse(
                output=f"ReAct reasoning budget exhausted after {self.max_turns} turns on deep horizon {node.id}",
                status="FAILED",
                files_modified=[],
                metadata={"adapter": self.name, "turns_used": self.max_turns, "error": "REASONING_BUDGET_EXHAUSTED"},
                epoch=epoch,
                dispatch_identity=disp,
            )

        return AgentResponse(
            output=f"ReAct completed after {turns_used} turns for {node.id}",
            status="COMPLETED",
            files_modified=list(node.owns),
            metadata={"adapter": self.name, "turns_used": turns_used, "trace": self.state_trace},
            epoch=epoch,
            dispatch_identity=disp,
        )


@dataclass
class CancellationToken:
    """Explicit cancellation token for cooperative asynchronous stream interruption."""

    is_cancelled: bool = False
    reason: str = ""

    def cancel(self, reason: str = "Stream interrupted by cancellation token") -> None:
        self.is_cancelled = True
        self.reason = reason


class UnixSocketStreamServer:
    """Async context manager helper for running Unix Domain Socket streaming servers."""

    def __init__(
        self,
        socket_path: str,
        client_handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Any],
    ):
        self.socket_path = socket_path
        self.client_handler = client_handler
        self._server: Optional[asyncio.Server] = None

    async def __aenter__(self) -> UnixSocketStreamServer:
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass
        self._server = await asyncio.start_unix_server(
            self.client_handler, path=self.socket_path
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass


class DuplexSocketAdapter(BaseRuntimeAdapter):
    """Full-duplex streaming execution adapter over Unix Domain Sockets (UDS) / async streams.

    Implements Box 1 of the Streaming Triad architecture:
    - Wraps bi-directional UDS sockets for streaming token deltas and out-of-band control signals.
    - Consumes StreamChannel.DATA (0x01) for incremental token output.
    - Monitors StreamChannel.CONTROL (0x02) for real-time barge-in signals (ABORT, STEER, PAUSE, RESUME).
    - Can attach a StreamingTokenInspector for hot-path challenger aborts.
    - Supports cooperative cancellation tokens (CancellationToken) and async timeouts.
    - When ABORT signal is encountered or triggered, halts inference/stream consumption immediately
      and returns AgentResponse(status='REVISING', epoch=epoch + 1, ...).
    """

    def __init__(
        self,
        name: str = "duplex-socket",
        socket_path: Optional[str] = None,
        token_inspector: Optional[Any] = None,
        cancel_token: Optional[CancellationToken] = None,
        timeout: float = 30.0,
        buffer_size: int = 65536,
        stream_handler: Optional[Callable[[TaskNode, Dict[str, Any]], Any]] = None,
    ):
        super().__init__(name)
        self.socket_path = socket_path
        self.token_inspector = token_inspector
        self.cancel_token = cancel_token
        self.timeout = timeout
        self.buffer_size = buffer_size
        self.stream_handler = stream_handler
        self.total_frames_sent: int = 0
        self.total_frames_received: int = 0
        self.total_aborts_handled: int = 0

    async def invoke_stream(
        self,
        node: TaskNode,
        context: Dict[str, Any],
        cancel_token: Optional[CancellationToken] = None,
    ) -> AgentResponse:
        """Asynchronously execute a streaming task node over UDS or duplex stream."""
        self.total_invocations += 1

        refusal = self.check_refusal(node, context)
        if refusal:
            self.total_tokens_consumed += 120
            return refusal

        disp_raw = context.get("dispatch_identity") if context else getattr(node, "active_dispatch", None)
        disp = DispatchIdentity.from_dict(disp_raw) if isinstance(disp_raw, dict) else disp_raw
        epoch = getattr(disp, "epoch", getattr(node, "epoch", 1)) if disp else getattr(node, "epoch", 1)

        active_cancel = cancel_token or self.cancel_token
        if active_cancel and active_cancel.is_cancelled:
            self.total_aborts_handled += 1
            reason = active_cancel.reason or "Pre-cancelled by cancellation token"
            return AgentResponse(
                output="",
                status="REVISING",
                epoch=epoch + 1,
                dispatch_identity=disp,
                files_modified=[],
                metadata={
                    "adapter": self.name,
                    "interrupted": True,
                    "abort_signal": int(ControlSignal.ABORT),
                    "abort_reason": reason,
                },
                revision_directive=RevisionDirective(
                    verdict="ABORT",
                    failure_class=FailureClass.LOCAL_DEFECT,
                    feedback=reason,
                ),
            )

        # 1. Real Unix Domain Socket connection path
        if self.socket_path and os.path.exists(self.socket_path):
            return await self._invoke_over_uds(node, context, disp, epoch, active_cancel)

        # 2. Custom stream handler callable
        if self.stream_handler:
            return await self._invoke_over_handler(node, context, disp, epoch, active_cancel)

        # 3. Default deterministic streaming simulation
        return await self._invoke_simulation(node, context, disp, epoch, active_cancel)

    async def _invoke_over_uds(
        self,
        node: TaskNode,
        context: Dict[str, Any],
        disp: Optional[DispatchIdentity],
        epoch: int,
        cancel_token: Optional[CancellationToken],
    ) -> AgentResponse:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path),
                timeout=self.timeout,
            )
        except Exception as err:
            return AgentResponse(
                output=f"Failed to connect to UDS socket at {self.socket_path}: {err}",
                status="FAILED",
                epoch=epoch,
                dispatch_identity=disp,
                files_modified=[],
                metadata={"adapter": self.name, "error": str(err)},
            )

        req_payload = json.dumps(
            {"node_id": node.id, "title": node.title, "owns": list(node.owns)}
        ).encode("utf-8")
        stream_id = abs(hash(node.id)) % 0xFFFF or 1
        req_frame = StreamFrame(
            stream_id=stream_id,
            channel=StreamChannel.DATA,
            seq=0,
            signal=ControlSignal.NOOP,
            epoch=epoch,
            payload=req_payload,
        )
        writer.write(req_frame.encode())
        await writer.drain()
        self.total_frames_sent += 1

        accumulated_output = ""
        rx_buf = b""
        frames_received = 0
        tokens_consumed = 0

        try:
            while True:
                if cancel_token and cancel_token.is_cancelled:
                    abort_frame = StreamFrame(
                        stream_id=stream_id,
                        channel=StreamChannel.CONTROL,
                        seq=frames_received + 1,
                        signal=ControlSignal.ABORT,
                        epoch=epoch,
                        payload=cancel_token.reason.encode("utf-8"),
                    )
                    try:
                        writer.write(abort_frame.encode())
                        await writer.drain()
                    except Exception:
                        pass
                    writer.close()
                    await writer.wait_closed()
                    self.total_aborts_handled += 1
                    return AgentResponse(
                        output=accumulated_output,
                        status="REVISING",
                        epoch=epoch + 1,
                        dispatch_identity=disp,
                        files_modified=[],
                        metadata={
                            "adapter": self.name,
                            "interrupted": True,
                            "abort_signal": int(ControlSignal.ABORT),
                            "abort_reason": cancel_token.reason,
                        },
                        revision_directive=RevisionDirective(
                            verdict="ABORT",
                            failure_class=FailureClass.LOCAL_DEFECT,
                            feedback=cancel_token.reason,
                        ),
                    )

                chunk = await asyncio.wait_for(
                    reader.read(self.buffer_size), timeout=self.timeout
                )
                if not chunk:
                    break

                rx_buf += chunk
                frames, rx_buf = decode_all_frames(rx_buf)
                for f in frames:
                    frames_received += 1
                    self.total_frames_received += 1

                    if f.channel == StreamChannel.DATA:
                        token_text = f.payload.decode("utf-8", errors="replace")
                        accumulated_output += token_text
                        tokens_consumed += max(1, len(token_text.split()))

                        if self.token_inspector:
                            abort_frame = self.token_inspector.inspect_frame(f)
                            if abort_frame is not None:
                                try:
                                    writer.write(abort_frame.encode())
                                    await writer.drain()
                                except Exception:
                                    pass
                                writer.close()
                                await writer.wait_closed()
                                self.total_aborts_handled += 1
                                rev_dir = None
                                try:
                                    rev_dir = RevisionDirective.from_dict(
                                        json.loads(abort_frame.payload.decode("utf-8"))
                                    )
                                except Exception:
                                    pass
                                return AgentResponse(
                                    output=accumulated_output,
                                    status="REVISING",
                                    epoch=epoch + 1,
                                    dispatch_identity=disp,
                                    files_modified=[],
                                    metadata={
                                        "adapter": self.name,
                                        "interrupted": True,
                                        "abort_signal": int(ControlSignal.ABORT),
                                        "abort_reason": "Hot-path challenger interceptor triggered abort",
                                        "interceptor": "StreamingTokenInspector",
                                    },
                                    revision_directive=rev_dir,
                                )

                    elif f.channel == StreamChannel.CONTROL:
                        if f.signal == ControlSignal.ABORT:
                            writer.close()
                            await writer.wait_closed()
                            self.total_aborts_handled += 1
                            abort_str = f.payload.decode("utf-8", errors="replace")
                            rev_dir = None
                            try:
                                rev_dir = RevisionDirective.from_dict(json.loads(abort_str))
                            except Exception:
                                pass
                            return AgentResponse(
                                output=accumulated_output,
                                status="REVISING",
                                epoch=epoch + 1,
                                dispatch_identity=disp,
                                files_modified=[],
                                metadata={
                                    "adapter": self.name,
                                    "interrupted": True,
                                    "abort_signal": int(f.signal),
                                    "abort_reason": abort_str,
                                },
                                revision_directive=rev_dir
                                or RevisionDirective(verdict="ABORT", feedback=abort_str),
                            )

            writer.close()
            await writer.wait_closed()
            self.total_tokens_consumed += tokens_consumed

            return AgentResponse(
                output=accumulated_output,
                status="COMPLETED",
                files_modified=list(node.owns),
                epoch=epoch,
                dispatch_identity=disp,
                metadata={
                    "adapter": self.name,
                    "frames_received": frames_received,
                    "tokens_consumed": tokens_consumed,
                },
            )

        except asyncio.TimeoutError:
            writer.close()
            return AgentResponse(
                output=accumulated_output,
                status="FAILED",
                epoch=epoch,
                dispatch_identity=disp,
                files_modified=[],
                metadata={"adapter": self.name, "error": "UDS_STREAM_TIMEOUT"},
            )
        except Exception as err:
            writer.close()
            return AgentResponse(
                output=accumulated_output,
                status="FAILED",
                epoch=epoch,
                dispatch_identity=disp,
                files_modified=[],
                metadata={"adapter": self.name, "error": str(err)},
            )

    async def _invoke_over_handler(
        self,
        node: TaskNode,
        context: Dict[str, Any],
        disp: Optional[DispatchIdentity],
        epoch: int,
        cancel_token: Optional[CancellationToken],
    ) -> AgentResponse:
        accumulated_output = ""
        frames_received = 0
        tokens_consumed = 0

        res = self.stream_handler(node, context)
        if hasattr(res, "__aiter__"):
            async_iter = res
        elif hasattr(res, "__iter__"):
            async def _wrap_iter(it):
                for item in it:
                    yield item
            async_iter = _wrap_iter(res)
        else:
            if isinstance(res, AgentResponse):
                return res
            return AgentResponse(
                output=str(res),
                status="COMPLETED",
                files_modified=list(node.owns),
                epoch=epoch,
                dispatch_identity=disp,
                metadata={"adapter": self.name},
            )

        async for f in async_iter:
            if cancel_token and cancel_token.is_cancelled:
                self.total_aborts_handled += 1
                return AgentResponse(
                    output=accumulated_output,
                    status="REVISING",
                    epoch=epoch + 1,
                    dispatch_identity=disp,
                    files_modified=[],
                    metadata={
                        "adapter": self.name,
                        "interrupted": True,
                        "abort_signal": int(ControlSignal.ABORT),
                        "abort_reason": cancel_token.reason,
                    },
                    revision_directive=RevisionDirective(
                        verdict="ABORT",
                        failure_class=FailureClass.LOCAL_DEFECT,
                        feedback=cancel_token.reason,
                    ),
                )

            frames_received += 1
            self.total_frames_received += 1

            if f.channel == StreamChannel.DATA:
                token_text = f.payload.decode("utf-8", errors="replace")
                accumulated_output += token_text
                tokens_consumed += max(1, len(token_text.split()))

                if self.token_inspector:
                    abort_frame = self.token_inspector.inspect_frame(f)
                    if abort_frame is not None:
                        self.total_aborts_handled += 1
                        rev_dir = None
                        try:
                            rev_dir = RevisionDirective.from_dict(
                                json.loads(abort_frame.payload.decode("utf-8"))
                            )
                        except Exception:
                            pass
                        return AgentResponse(
                            output=accumulated_output,
                            status="REVISING",
                            epoch=epoch + 1,
                            dispatch_identity=disp,
                            files_modified=[],
                            metadata={
                                "adapter": self.name,
                                "interrupted": True,
                                "abort_signal": int(ControlSignal.ABORT),
                                "abort_reason": "Hot-path challenger interceptor triggered abort",
                                "interceptor": "StreamingTokenInspector",
                            },
                            revision_directive=rev_dir,
                        )

            elif f.channel == StreamChannel.CONTROL:
                if f.signal == ControlSignal.ABORT:
                    self.total_aborts_handled += 1
                    abort_str = f.payload.decode("utf-8", errors="replace")
                    rev_dir = None
                    try:
                        rev_dir = RevisionDirective.from_dict(json.loads(abort_str))
                    except Exception:
                        pass
                    return AgentResponse(
                        output=accumulated_output,
                        status="REVISING",
                        epoch=epoch + 1,
                        dispatch_identity=disp,
                        files_modified=[],
                        metadata={
                            "adapter": self.name,
                            "interrupted": True,
                            "abort_signal": int(f.signal),
                            "abort_reason": abort_str,
                        },
                        revision_directive=rev_dir
                        or RevisionDirective(verdict="ABORT", feedback=abort_str),
                    )

        self.total_tokens_consumed += tokens_consumed
        return AgentResponse(
            output=accumulated_output,
            status="COMPLETED",
            files_modified=list(node.owns),
            epoch=epoch,
            dispatch_identity=disp,
            metadata={
                "adapter": self.name,
                "frames_received": frames_received,
                "tokens_consumed": tokens_consumed,
            },
        )

    async def _invoke_simulation(
        self,
        node: TaskNode,
        context: Dict[str, Any],
        disp: Optional[DispatchIdentity],
        epoch: int,
        cancel_token: Optional[CancellationToken],
    ) -> AgentResponse:
        stream_id = abs(hash(node.id)) % 0xFFFF or 1

        if node.metadata.get("simulate_abort"):
            self.total_aborts_handled += 1
            reason = node.metadata.get("abort_reason", "Simulated out-of-band abort")
            return AgentResponse(
                output="[ABORTED MID-STREAM]",
                status="REVISING",
                epoch=epoch + 1,
                dispatch_identity=disp,
                files_modified=[],
                metadata={
                    "adapter": self.name,
                    "interrupted": True,
                    "abort_signal": int(ControlSignal.ABORT),
                    "abort_reason": reason,
                },
                revision_directive=RevisionDirective(verdict="ABORT", feedback=reason),
            )

        stream_content = node.metadata.get("stream_content")
        if stream_content:
            chunks = stream_content.splitlines(keepends=True) or [stream_content]
        else:
            chunks = [
                f"# Streaming task {node.id}: {node.title}\n",
                f"# OWNS: {', '.join(node.owns) if node.owns else 'none'}\n",
                "def execute():\n",
                f"    return 'Streamed result for {node.id}'\n",
            ]

        accumulated = ""
        for seq, chunk in enumerate(chunks, start=1):
            if cancel_token and cancel_token.is_cancelled:
                self.total_aborts_handled += 1
                return AgentResponse(
                    output=accumulated,
                    status="REVISING",
                    epoch=epoch + 1,
                    dispatch_identity=disp,
                    files_modified=[],
                    metadata={
                        "adapter": self.name,
                        "interrupted": True,
                        "abort_signal": int(ControlSignal.ABORT),
                        "abort_reason": cancel_token.reason,
                    },
                    revision_directive=RevisionDirective(
                        verdict="ABORT",
                        failure_class=FailureClass.LOCAL_DEFECT,
                        feedback=cancel_token.reason,
                    ),
                )

            frame = StreamFrame(
                stream_id=stream_id,
                channel=StreamChannel.DATA,
                seq=seq,
                signal=ControlSignal.NOOP,
                epoch=epoch,
                payload=chunk.encode("utf-8"),
            )
            self.total_frames_received += 1
            accumulated += chunk

            if self.token_inspector:
                abort_frame = self.token_inspector.inspect_frame(frame)
                if abort_frame is not None:
                    self.total_aborts_handled += 1
                    rev_dir = None
                    try:
                        rev_dir = RevisionDirective.from_dict(
                            json.loads(abort_frame.payload.decode("utf-8"))
                        )
                    except Exception:
                        pass
                    return AgentResponse(
                        output=accumulated,
                        status="REVISING",
                        epoch=epoch + 1,
                        dispatch_identity=disp,
                        files_modified=[],
                        metadata={
                            "adapter": self.name,
                            "interrupted": True,
                            "abort_signal": int(ControlSignal.ABORT),
                            "abort_reason": "Hot-path challenger interceptor triggered abort",
                            "interceptor": "StreamingTokenInspector",
                        },
                        revision_directive=rev_dir,
                    )

        tokens = max(1, len(accumulated.split()))
        self.total_tokens_consumed += tokens

        return AgentResponse(
            output=accumulated,
            status="COMPLETED",
            files_modified=list(node.owns),
            epoch=epoch,
            dispatch_identity=disp,
            metadata={
                "adapter": self.name,
                "frames_received": len(chunks),
                "tokens_consumed": tokens,
            },
        )

    def invoke(self, node: TaskNode, context: Dict[str, Any]) -> AgentResponse:
        """Synchronously execute by driving the async stream on an event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    lambda: asyncio.run(self.invoke_stream(node, context))
                ).result(timeout=self.timeout)
        else:
            return asyncio.run(self.invoke_stream(node, context))
