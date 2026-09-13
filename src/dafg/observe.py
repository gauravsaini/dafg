"""Distributed Observability Fabric (DOF) — Eyes, not brain.

Passive observation layer for the DAFG runtime. Records spans, events,
and metrics through pluggable Probe backends without influencing runtime
decisions.  Zero runtime dependencies (stdlib only).

Usage:
    from dafg.observe import ObservabilityFabric, JsonlProbe, InMemoryProbe

    fabric = ObservabilityFabric([JsonlProbe("traces.jsonl")])
    graph = DAFG(probes=[JsonlProbe("traces.jsonl")])
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class SpanStatus(str, Enum):
    """Deterministic span outcome — 3 fixed states for clean analytics."""
    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Span:
    """One unit of observable work (node dispatch, gate check, repair attempt).

    trace_id maps to DAFG run_id.  span_id is derived from DispatchIdentity
    fields when available, otherwise auto-generated.
    """
    trace_id: str
    span_id: str
    name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    parent_span_id: Optional[str] = None
    status: SpanStatus = SpanStatus.OK
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def finish(self, status: SpanStatus = SpanStatus.OK) -> None:
        self.end_time = time.time()
        self.status = status

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["duration_ms"] = self.duration_ms
        return d


# ---------------------------------------------------------------------------
# Probe protocol — structural typing, no inheritance required
# ---------------------------------------------------------------------------

@runtime_checkable
class Probe(Protocol):
    """Interface a DOF backend must satisfy.  All methods are fire-and-forget."""

    def on_span_start(self, span: Span) -> None: ...
    def on_span_end(self, span: Span) -> None: ...
    def on_event(self, name: str, attributes: Dict[str, Any]) -> None: ...
    def on_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None: ...


# ---------------------------------------------------------------------------
# Fabric — fan-out coordinator
# ---------------------------------------------------------------------------

class ObservabilityFabric:
    """Holds probes and fans out calls.  Exception-safe: a broken probe
    never crashes the runtime.

    Set async_mode=True for heavy probes (remote logging).  Default is
    synchronous fan-out (ponytail: no thread pool until you need it).
    """

    def __init__(
        self,
        probes: Optional[Sequence[Probe]] = None,
        async_mode: bool = False,
    ) -> None:
        self._probes: List[Probe] = list(probes) if probes else []
        self._seq = 0
        self._lock = threading.Lock()
        self._async = async_mode
        # ponytail: lazy pool, only created when first async fan-out fires
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def add_probe(self, probe: Probe) -> None:
        self._probes.append(probe)

    @property
    def probes(self) -> List[Probe]:
        return list(self._probes)

    def _next_span_id(self) -> str:
        with self._lock:
            self._seq += 1
            return f"span_{self._seq}"

    def start_span(
        self,
        name: str,
        trace_id: str,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Span:
        """Create and announce a new span."""
        span = Span(
            trace_id=trace_id,
            span_id=span_id or self._next_span_id(),
            name=name,
            parent_span_id=parent_span_id,
            attributes=attributes or {},
        )
        self._fan_out("on_span_start", span)
        return span

    def end_span(self, span: Span, status: SpanStatus = SpanStatus.OK) -> None:
        span.finish(status)
        self._fan_out("on_span_end", span)

    def emit_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self._fan_out("on_event", name, attributes or {})

    def emit_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        self._fan_out("on_metric", name, value, tags)

    def _get_pool(self) -> concurrent.futures.ThreadPoolExecutor:
        if self._pool is None:
            # ponytail: 2 workers is enough — probes are I/O, not CPU
            self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        return self._pool

    # ponytail: one fan-out helper handles all methods via positional args
    def _fan_out(self, method: str, *args: Any) -> None:
        for probe in self._probes:
            if self._async:
                self._get_pool().submit(self._safe_call, probe, method, args)
            else:
                self._safe_call(probe, method, args)

    @staticmethod
    def _safe_call(probe: Any, method: str, args: tuple) -> None:
        try:
            getattr(probe, method)(*args)
        except Exception as exc:
            print(f"[DOF] probe {type(probe).__name__}.{method} failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Built-in probe backends
# ---------------------------------------------------------------------------

class NullProbe:
    """No-op probe.  Zero overhead."""

    def on_span_start(self, span: Span) -> None:
        pass

    def on_span_end(self, span: Span) -> None:
        pass

    def on_event(self, name: str, attributes: Dict[str, Any]) -> None:
        pass

    def on_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        pass


class InMemoryProbe:
    """Collects all signals in lists.  Useful for tests and analytics."""

    def __init__(self) -> None:
        self.spans: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self.metrics: List[Dict[str, Any]] = []

    def on_span_start(self, span: Span) -> None:
        pass  # captured on end

    def on_span_end(self, span: Span) -> None:
        self.spans.append(span.to_dict())

    def on_event(self, name: str, attributes: Dict[str, Any]) -> None:
        self.events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": name,
            "attributes": attributes,
        })

    def on_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        self.metrics.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": name,
            "value": value,
            "tags": tags or {},
        })

    def clear(self) -> None:
        self.spans.clear()
        self.events.clear()
        self.metrics.clear()


class JsonlProbe:
    """Appends spans, events, and metrics as JSONL to a file.

    Follows the same atomic-write pattern as TrendStore.
    Optional rotation: set max_bytes to rotate when file exceeds that size.
    """

    def __init__(
        self,
        filepath: str | Path = "eval_results/traces.jsonl",
        max_bytes: Optional[int] = None,
    ) -> None:
        self._path = Path(filepath)
        self._max_bytes = max_bytes

    def _rotate_if_needed(self) -> None:
        """Rotate file when max_bytes exceeded.  Keeps one .bak."""
        if self._max_bytes is None:
            return
        try:
            if self._path.exists() and self._path.stat().st_size >= self._max_bytes:
                bak = self._path.with_suffix(".jsonl.bak")
                os.replace(self._path, bak)
        except OSError:
            pass  # best-effort rotation

    def _write(self, record: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_if_needed()
        line = json.dumps(record, default=str)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def on_span_start(self, span: Span) -> None:
        pass  # captured on end

    def on_span_end(self, span: Span) -> None:
        self._write({"type": "span", **span.to_dict()})

    def on_event(self, name: str, attributes: Dict[str, Any]) -> None:
        self._write({
            "type": "event",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": name,
            "attributes": attributes,
        })

    def on_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        self._write({
            "type": "metric",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "name": name,
            "value": value,
            "tags": tags or {},
        })


class StdoutProbe:
    """Pretty-prints spans and events to stderr for local development."""

    _RESET = "\033[0m"
    _DIM = "\033[2m"
    _CYAN = "\033[36m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _RED = "\033[31m"

    def __init__(self, color: Optional[bool] = None) -> None:
        self._color = color if color is not None else hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

    def _c(self, code: str, text: str) -> str:
        return f"{code}{text}{self._RESET}" if self._color else text

    def on_span_start(self, span: Span) -> None:
        ts = self._c(self._DIM, datetime.now(timezone.utc).strftime("%H:%M:%S"))
        name = self._c(self._CYAN, span.name)
        print(f"  {ts} ▶ {name} [{span.span_id}]", file=sys.stderr)

    def on_span_end(self, span: Span) -> None:
        ts = self._c(self._DIM, datetime.now(timezone.utc).strftime("%H:%M:%S"))
        color = self._GREEN if span.status == SpanStatus.OK else self._RED
        status = self._c(color, span.status.value)
        dur = self._c(self._DIM, f"{span.duration_ms:.1f}ms")
        print(f"  {ts} ◼ {span.name} {status} {dur}", file=sys.stderr)

    def on_event(self, name: str, attributes: Dict[str, Any]) -> None:
        ts = self._c(self._DIM, datetime.now(timezone.utc).strftime("%H:%M:%S"))
        ev = self._c(self._YELLOW, name)
        print(f"  {ts} ⚡ {ev}", file=sys.stderr)

    def on_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        ts = self._c(self._DIM, datetime.now(timezone.utc).strftime("%H:%M:%S"))
        metric = self._c(self._DIM, f"{name}={value}")
        print(f"  {ts} 📊 {metric}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Convenience: parse --observe CLI value into probes
# ---------------------------------------------------------------------------

def parse_observe_flag(values: List[str]) -> List[Probe]:
    """Parse CLI --observe values into probe instances.

    Supported formats:
        'jsonl:path/to/file.jsonl'  -> JsonlProbe(path)
        'jsonl'                     -> JsonlProbe()  (default path)
        'stdout'                    -> StdoutProbe()
        'memory'                    -> InMemoryProbe()
        'all'                       -> StdoutProbe + JsonlProbe + InMemoryProbe
        'none'                      -> []
    """
    probes: List[Probe] = []
    for val in values:
        val = val.strip()
        if val == "none":
            continue
        elif val == "all":
            probes.extend([StdoutProbe(), JsonlProbe(), InMemoryProbe()])
        elif val == "stdout":
            probes.append(StdoutProbe())
        elif val == "memory":
            probes.append(InMemoryProbe())
        elif val.startswith("jsonl"):
            if ":" in val:
                _, path = val.split(":", 1)
                probes.append(JsonlProbe(path.strip()))
            else:
                probes.append(JsonlProbe())
        else:
            print(f"[DOF] unknown observe backend: {val!r}, skipping", file=sys.stderr)
    return probes
