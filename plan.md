# DAFG Iteration Plan: Real-Time Streaming Triad & Out-of-Band Barge-in Protocol

## 1. Executive Summary & Core Objective
DAFG ke current turn-based batch model (`invoke()` -> `AgentResponse` -> post-facto `Action.CHALLENGE`) ko **Full-Duplex Streaming Mesh** mein elevate karna.
Target: Token/compute waste ko 50%–70% cut karna via instant out-of-band challenger aborts, inter-node KV-cache prefilling enable karna, aur pure-function state machine invariants ko 100% preserve rakhna.

---

## 2. Core Problem & First-Principles Analysis

- **Batch Generation Waste:** Agar Prover 1,000 tokens emit karne wala ho aur line 3 par hi boundary contract (`OWNS:`) ya import invariant tod de, toh bache hue 970 tokens ka time aur GPU compute 100% waste hota hai.
- **Turn-Taking Latency:** Wave N+1 tab tak idle baithi rehti hai jab tak Wave N poora finish hokar accepted state mein na jaye.
- **Turn-based Fragility:** RPC/HTTP turn-taking agent-to-agent coordination ko artificial round-trips mein baandh deta hai.

### Key Insight
Generation aur validation ko sequential phases ke bajaye **concurrent lockstep streams** banana:
- Data Stream (0x01) par lightweight token deltas emit hote hain.
- Control Stream (0x02) par out-of-band instant barge-in (`0xABORT` / `0xSTEER`) chalta hai.
- Deterministic FSM (`protocol.py`) stream interrupts ko monotonic epoch increments ke roop mein reduce karta hai.

---

## 3. Wire Protocol Specification (`src/dafg/transport.py`)

Pure dataclass, zero external dependencies, 12-byte fixed binary header over Unix Domain Sockets (UDS) / QUIC.

### Stream Channels:
- `0x01` (DATA): UTF-8 token deltas, partial tool calls, schema headers.
- `0x02` (CONTROL): Out-of-band signals (`0x01 ABORT`, `0x02 STEER`, `0x03 PAUSE`, `0x04 RESUME`).
- `0x03` (TELEMETRY): Invariant timestamps, token counts, hardware metrics.

### Binary Frame Layout:
- `stream_id`: 2 bytes (uint16)
- `channel`: 1 byte (uint8)
- `seq`: 4 bytes (uint32, monotonic ordering)
- `signal`: 1 byte (uint8)
- `epoch`: 2 bytes (uint16, DAFG node epoch)
- `length`: 2 bytes (uint16, payload length)
- `payload`: N bytes (raw UTF-8 / binary)

```python
from enum import IntEnum
from dataclasses import dataclass
import struct
from typing import Tuple

class StreamChannel(IntEnum):
    DATA = 0x01
    CONTROL = 0x02
    TELEMETRY = 0x03

class ControlSignal(IntEnum):
    NOOP = 0x00
    ABORT = 0x01
    STEER = 0x02
    PAUSE = 0x03
    RESUME = 0x04

@dataclass(frozen=True)
class StreamFrame:
    stream_id: int
    channel: StreamChannel
    seq: int
    signal: ControlSignal
    epoch: int
    payload: bytes

    def encode(self) -> bytes:
        header = struct.pack("!HBIBHH", self.stream_id, int(self.channel), self.seq, int(self.signal), self.epoch, len(self.payload))
        return header + self.payload

    @staticmethod
    def decode(data: bytes) -> Tuple["StreamFrame", bytes]:
        HEADER_SIZE = 12
        if len(data) < HEADER_SIZE:
            raise ValueError("Buffer too small for frame header")
        stream_id, ch, seq, sig, epoch, length = struct.unpack("!HBIBHH", data[:HEADER_SIZE])
        total_len = HEADER_SIZE + length
        if len(data) < total_len:
            raise ValueError("Incomplete frame payload")
        frame = StreamFrame(
            stream_id=stream_id,
            channel=StreamChannel(ch),
            seq=seq,
            signal=ControlSignal(sig),
            epoch=epoch,
            payload=data[HEADER_SIZE:total_len]
        )
        return frame, data[total_len:]
```

---

## 4. Architectural Contracts (LLD Pure Boxes)

### Box 1: Streaming Execution Adapter (`src/dafg/adapters.py`)
- Standard input/output contract under `BaseRuntimeAdapter`.
- Manages UDS socket connection.
- Local model engines (vLLM / llama.cpp) ya cloud APIs (via SSE + `AbortController`) ko bi-directional socket mein wrap karta hai.
- Control channel listener abort signal aate hi inference process ko millisecond-level par interrupt karta hai aur `AgentResponse(status='REVISING')` return karta hai.

### Box 2: Hot-Path Challenger Interceptor (`src/dafg/adversarial.py`)
- Stream 0x01 ko tap karke incremental AST parsing aur regex boundary checks run karta hai:
  - **OWNS Invariant:** Declared target files se bahar touch karte hi intercept.
  - **Forbidden Imports / APIs:** Blacklisted dependencies ka syntax aate hi intercept.
  - **Structural Gates:** Approved `GATES.md` invariants ke against early failure detect hote hi cut-off.
- Intercept trigger hote hi Stream 0x02 par `0xABORT` + structured `RevisionDirective` dispatch.

### Box 3: FSM State Machine Integration (`src/dafg/protocol.py`)
- Pure state reducer invariant preserve rehta hai:
  - Add `Action.STREAM_INTERRUPT = "STREAM_INTERRUPT"`.
  - Har interruption state ko `ProtocolState.REVISING` par push karegi.
  - Strict Rule: Har stream abort node ke `epoch` ko `epoch + 1` karega aur active dispatch lease invalidate karega.

### Box 4: Telemetry & Deterministic Replay (`src/dafg/trends.py`)
- Stream 0x03 sidecar process bina model latency add kiye background mein `trends.jsonl` mein frames log karega.
- Auditability intact: pure state playback se exact failure point reproduce ho sakta hai.

### Box 5: Inter-Node Speculative Prefill (`src/dafg/runtime.py` -> `WaveScheduler`)
- Node N jab apna signature/types/schemas emit kar raha ho, dependent Node N+1 stream 0x01 subscribe karke KV-cache prefill build karta hai.
- Gate clearance aate hi Node N+1 ka TTFT (Time-To-First-Token) near-zero ho jata hai.

---

## 5. Resolution of 3 Core Distributed Agent Dilemmas

- **Model Heterogeneity:** Contract byte-level token deltas par rehta hai. Swarm ko fark nahi padta peeche Claude 3.7 hai ya local Qwen/Llama instance.
- **Observability vs Performance:** Separation of concerns — Data stream lightweight rehti hai, telemetry out-of-band siphon hoti hai.
- **Security & Convergence Guard:** Final convergence sirf socket stream par rely nahi karegi; Pillar 6 (`CompletionGuard` / Stop Hook Membrane) aur cryptographically signed SHA-256 gate checks (`gates.py`) verify karne ke baad hi task accept hoga.

---

## 6. Implementation Milestones

- **Milestone 1: Transport & Wire Protocol**
  - Create `src/dafg/transport.py` (StreamFrame, encoders/decoders, buffer slicing).
  - Add comprehensive unit tests in `tests/test_transport.py` (round-trip, corrupted frames, split buffers).
- **Milestone 2: FSM Action & Pure Reducer Expansion**
  - Add `Action.STREAM_INTERRUPT` in `protocol.py`.
  - Add unit tests verifying epoch bumping and lease invalidation on interruption.
- **Milestone 3: Streaming Adapter Base**
  - Implement `DuplexSocketAdapter` in `src/dafg/adapters.py`.
  - Integration with async event loop and out-of-band abort handling.
- **Milestone 4: Adversarial Early-Interception Engine**
  - Implement lightweight streaming token inspector in `adversarial.py`.
  - Benchmark early-abort latency (< 15ms target).
- **Milestone 5: Benchmark Verification**
  - Run full benchmark suite (`uv run dafg eval` and real-world agent eval generations).
  - Measure token burn reduction and TTFT improvements.
