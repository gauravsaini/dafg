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
from typing import Any, Callable, Dict, List, Optional

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


class IterativeCLIAdapter(BaseRuntimeAdapter):
    """Simulates an iterative command-line agent (e.g. Agy, Bash-driven agent)."""

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
        # Model prompt token estimation
        prompt_tokens = len(node.title) * 4 + 200
        self.total_tokens_consumed += prompt_tokens

        files_modified = list(node.owns)
        output_text = f"CLI session completed for {node.id}: {node.title}"

        if self.runner_fn:
            result = self.runner_fn(output_text, node)
            return AgentResponse(
                output=result.get("output", output_text),
                status=result.get("status", "COMPLETED"),
                files_modified=result.get("files_modified", files_modified),
                metadata=result.get("metadata", {"adapter": self.name}),
            )

        return AgentResponse(
            output=output_text,
            status="COMPLETED",
            files_modified=files_modified,
            metadata={"adapter": self.name, "commands_run": len(self.command_history)},
        )


class ToolDispatchAdapter(BaseRuntimeAdapter):
    """Simulates function-calling / tool dispatch architecture (e.g. Claude Code, Codex)."""

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
        # Tool dispatch overhead token estimation
        tokens = len(node.title) * 4 + len(self.available_tools) * 50 + 350
        self.total_tokens_consumed += tokens

        # Simulate tool calls for node's declared files
        for f in node.owns:
            tool_call = {"tool": "edit_file", "path": f}
            self.dispatched_tool_calls.append(tool_call)

        return AgentResponse(
            output=f"ToolDispatch completed {len(node.owns)} tool calls for {node.id}",
            status="COMPLETED",
            files_modified=list(node.owns),
            metadata={"adapter": self.name, "tool_calls_count": len(self.dispatched_tool_calls)},
        )


class ReActStateAdapter(BaseRuntimeAdapter):
    """Simulates a ReAct state-machine loop (e.g. LangGraph / ReAct agent)."""

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
        # ReAct chatter and state overhead: Thought -> Action -> Observation
        turn_tokens = 250
        turns_used = 0

        for turn in range(min(3, self.max_turns)):
            turns_used += 1
            self.total_tokens_consumed += turn_tokens
            self.state_trace.append({
                "turn": str(turn + 1),
                "thought": f"Assessing {node.title} requirements",
                "action": f"modify_target_{turn}",
                "observation": "Step passed",
            })

        return AgentResponse(
            output=f"ReAct completed after {turns_used} turns for {node.id}",
            status="COMPLETED",
            files_modified=list(node.owns),
            metadata={"adapter": self.name, "turns_used": turns_used, "trace": self.state_trace},
        )
