"""Decoupled Execution Architecture Adapters for DAFG v0.3.

Provides concrete execution adapters representing fundamentally different
agent loop architectures (Iterative CLI, Tool Dispatch / Function Calling,
and ReAct State Machine) to test true cross-runtime transferability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import time
from typing import Any, Callable, Dict, List, Optional, Set

from dafg.protocol import DispatchIdentity
from dafg.runtime import AgentResponse, TaskNode


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
    """

    def __init__(
        self,
        name: str = "react-state-machine",
        max_turns: int = 5,
    ):
        super().__init__(name)
        self.max_turns = max_turns
        self.state_trace: List[Dict[str, str]] = []

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

        for turn in range(num_turns):
            turns_used += 1
            self.total_tokens_consumed += turn_tokens + (turn * 50)
            obs = "Transient error, retrying" if (is_flaky and turn == 0) else "Step passed"
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
