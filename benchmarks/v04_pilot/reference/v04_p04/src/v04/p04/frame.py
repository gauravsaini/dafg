"""Length-prefixed framing."""
from __future__ import annotations
import struct

MAX_FRAME = 1 << 20

def encode(payload: bytes) -> bytes:
    if len(payload) > MAX_FRAME:
        raise ValueError("frame too large")
    return struct.pack(">I", len(payload)) + payload
