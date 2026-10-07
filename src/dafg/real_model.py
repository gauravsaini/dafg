"""Real-model runner for DAFG evaluation: Gemini Flash via the stored connector.

Coverage: provides the honest model backend for the Phase-1 A/B pilot
(benchmarks/PHASE1_BENCHMARK.md). Exposes a ``runner_fn(prompt, node)``
compatible with ``IterativeCLIAdapter`` and returns TRUE token usage from
the API response (``usageMetadata``) so CPAD is computed from real numbers,
not the legacy ``len(title)*4+180`` stub formula.

Auth: uses the ``custom.gemini`` connector through authd surrogates
(``dynamic_credentials`` helpers, same pattern as the gemini skill's
``bin/gemini_tts.py``). The raw key is never printed, logged, or persisted;
requests go only to generativelanguage.googleapis.com.

No network activity happens at import time.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

HOST = "generativelanguage.googleapis.com"
CONNECTOR = "custom.gemini"
# Cheapest capable flash-class text model for eval traffic.
DEFAULT_MODEL = "gemini-2.5-flash"
# Per the Phase-1 design: frozen prompts, low temperature.
DEFAULT_TEMPERATURE = 0.2


def _credential_helpers():
    """Lazy import so importing this module never touches the skill path."""
    sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
    from dynamic_credentials import (  # noqa: E402
        DynamicCredentialError,
        add_surrogate_to_request,
        read_json_response,
    )
    return DynamicCredentialError, add_surrogate_to_request, read_json_response


@dataclass
class GeminiRunner:
    """Thin generateContent client returning adapter-compatible results."""

    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    timeout_s: int = 180
    max_output_tokens: int = 4096
    seed: Optional[int] = None
    total_prompt_tokens: int = field(default=0, init=False)
    total_completion_tokens: int = field(default=0, init=False)
    calls: int = field(default=0, init=False)

    def generate(self, prompt: str) -> Dict[str, Any]:
        """Call the model once. Never raises on API/transport failure.

        Returns {"ok": True, "text": str, "usage": {...}} or
        {"ok": False, "error": str}.
        """
        DynamicCredentialError, add_surrogate_to_request, read_json_response = _credential_helpers()
        url = f"https://{HOST}/v1beta/models/{self.model}:generateContent"
        generation_config: Dict[str, Any] = {
            "temperature": self.temperature,
            "maxOutputTokens": self.max_output_tokens,
        }
        if self.seed is not None:
            generation_config["seed"] = self.seed
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            add_surrogate_to_request(req, CONNECTOR, allowed_hosts=[HOST])
        except DynamicCredentialError as exc:
            return {"ok": False, "error": f"auth: {exc}"}
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = read_json_response(resp)
        except Exception as exc:  # noqa: BLE001 - transport/API errors are data here
            return {"ok": False, "error": f"request: {type(exc).__name__}: {str(exc)[:300]}"}

        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            return {"ok": False, "error": f"unexpected response: {json.dumps(payload)[:300]}"}
        meta = payload.get("usageMetadata", {}) or {}
        usage = {
            "prompt_tokens": int(meta.get("promptTokenCount", 0)),
            "completion_tokens": int(meta.get("candidatesTokenCount", 0)),
            "total_tokens": int(meta.get("totalTokenCount", 0)),
        }
        self.calls += 1
        self.total_prompt_tokens += usage["prompt_tokens"]
        self.total_completion_tokens += usage["completion_tokens"]
        return {"ok": True, "text": text, "usage": usage}

    def runner_fn(self, prompt: str, node: Any) -> Dict[str, Any]:
        """Adapter-compatible entry: ``runner_fn(prompt, node) -> dict``.

        Returns an AgentResponse-shaped dict including true ``usage`` so the
        adapter can account real tokens instead of the stub formula.
        """
        result = self.generate(prompt)
        if not result["ok"]:
            return {
                "output": f"model call failed: {result['error']}",
                "status": "FAILED",
                "files_modified": [],
                "metadata": {"adapter": "iterative-cli", "model": self.model, "error": result["error"]},
            }
        usage = result["usage"]
        return {
            "output": result["text"],
            "status": "COMPLETED",
            "files_modified": [],
            "metadata": {"adapter": "iterative-cli", "model": self.model},
            "usage": usage,
        }
