"""Base harness interface and telemetry models for DAFG evaluation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

@dataclass
class ExecutionResult:
    status: str  # 'COMPLETED', 'BLOCKED', 'TIMEOUT', 'CRASH', 'BUDGET_EXCEEDED'
    completion_claim: str
    tokens_used: int
    wall_clock_sec: float
    trace: List[Dict[str, Any]] = field(default_factory=list)
    internal_gates_met: bool = False
    error: Optional[str] = None

class BaseHarness:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version

    async def run(
        self,
        task,
        workspace: Path,
        mode: str,
        token_limit: int,
        timeout_sec: float,
        ablation: Optional[str] = None
    ) -> ExecutionResult:
        raise NotImplementedError
