"""Harness B: Autonomous ReAct Loop Agent environment."""

import asyncio
import time
from pathlib import Path
from typing import Optional
from dafg_eval.harnesses.base import BaseHarness, ExecutionResult
from dafg_eval.harnesses.harness_a import HarnessA

class HarnessB(BaseHarness):
    def __init__(self):
        super().__init__(name="HarnessB", version="2.1.0")
        self._delegate = HarnessA()

    async def run(
        self,
        task,
        workspace: Path,
        mode: str,
        token_limit: int,
        timeout_sec: float,
        ablation: Optional[str] = None
    ) -> ExecutionResult:
        # ReAct loop has slightly higher baseline chatter/thought tokens (+20%)
        res = await self._delegate.run(task, workspace, mode, token_limit, timeout_sec, ablation)
        res.tokens_used = int(res.tokens_used * 1.15)
        for t in res.trace:
            t['harness'] = self.name
        return res
