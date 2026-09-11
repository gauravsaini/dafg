"""Structured Tracing & Span Telemetry System for DAFG Bottleneck Analysis."""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional
import time
import json

class DAFGStage(str, Enum):
    GOAL_INTERPRETATION = "goal_interpretation"
    GRAPH_CONSTRUCTION = "graph_construction"
    PERSONA_GENERATION = "persona_generation"
    CAPABILITY_ROUTING = "capability_routing"
    CONTEXT_ASSEMBLY = "context_assembly"
    WORKER_EXECUTION = "worker_execution"
    VERIFICATION = "verification"
    REVISION_INVALIDATION = "revision_invalidation"
    INTEGRATION = "integration"
    DELIVERY = "delivery"

class ReasonCode(str, Enum):
    NONE = "NONE"
    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    WRONG_DECOMPOSITION = "WRONG_DECOMPOSITION"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    PERSONA_CAPABILITY_MISMATCH = "PERSONA_CAPABILITY_MISMATCH"
    TOOL_FAILURE = "TOOL_FAILURE"
    UNSUPPORTED_ASSERTION = "UNSUPPORTED_ASSERTION"
    VERIFIER_FALSE_ACCEPT = "VERIFIER_FALSE_ACCEPT"
    VERIFIER_FALSE_REJECT = "VERIFIER_FALSE_REJECT"
    STALE_INPUT = "STALE_INPUT"
    INTERFACE_MISMATCH = "INTERFACE_MISMATCH"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"

@dataclass
class TraceSpan:
    run_id: str
    node_id: str
    epoch: int
    stage: str
    started_at: float
    ended_at: float
    queue_ms: float
    model: str
    persona_version: str
    input_artifact_versions: List[str]
    output_artifact_version: Optional[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    decision: str  # 'ACCEPT', 'REVISE', 'INVALIDATE', 'BLOCK', 'PASS'
    reason_code: str
    is_critical_path: bool = False
    defect_introduced: bool = False
    defect_detected: bool = False
    defect_repaired: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.ended_at - self.started_at)
