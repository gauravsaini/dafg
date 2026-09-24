"""Zero-dependency multiplexed streaming transport layer for DAFG.

Implements the pure wire protocol specification for full-duplex communication
over Unix Domain Sockets (UDS) / QUIC:
- Channel 0x01 (DATA): Incremental token deltas, partial tool calls, schemas.
- Channel 0x02 (CONTROL): High-priority out-of-band signals (ABORT, STEER, PAUSE, RESUME).
- Channel 0x03 (TELEMETRY): Immutable metrics, latency measurements, and audit traces.

Header Format (12 bytes fixed, network byte order '!HBIHIB'):
- stream_id : 2 bytes (uint16)
- channel   : 1 byte  (uint8, StreamChannel)
- seq       : 4 bytes (uint32, monotonic ordering)
- signal    : 1 byte  (uint8, ControlSignal)
- epoch     : 2 bytes (uint16, DAFG node epoch)
- length    : 2 bytes (uint16, payload length)
- payload   : N bytes (raw UTF-8 / binary)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import List, Sequence, Tuple


class StreamChannel(IntEnum):
    """Multiplexed stream channel identifiers."""
    DATA = 0x01
    CONTROL = 0x02
    TELEMETRY = 0x03


class ControlSignal(IntEnum):
    """Out-of-band control signals for execution steering and interruption."""
    NOOP = 0x00
    ABORT = 0x01
    STEER = 0x02
    PAUSE = 0x03
    RESUME = 0x04


class TransportError(Exception):
    """Base exception for transport and wire protocol errors."""
    pass


class IncompleteFrameError(TransportError, ValueError):
    """Raised when the buffer does not contain enough bytes to decode a complete frame."""
    pass


class CorruptFrameError(TransportError, ValueError):
    """Raised when a frame fails structural, channel, or bounds validation."""
    pass


class PayloadOverflowError(TransportError, ValueError):
    """Raised when payload exceeds the uint16 maximum length (65535 bytes)."""
    pass


HEADER_FORMAT = "!HBIBHH"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 12 bytes: H(2)+B(1)+I(4)+B(1)+H(2)+H(2)
MAX_PAYLOAD_SIZE = 0xFFFF  # 65535 bytes


@dataclass(frozen=True)
class StreamFrame:
    """Immutable binary frame unit in the DAFG streaming transport layer."""

    stream_id: int
    channel: StreamChannel
    seq: int
    signal: ControlSignal
    epoch: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        if not (0 <= self.stream_id <= 0xFFFF):
            raise CorruptFrameError(f"stream_id {self.stream_id} out of uint16 range (0..65535)")
        if not (0 <= self.seq <= 0xFFFFFFFF):
            raise CorruptFrameError(f"seq {self.seq} out of uint32 range (0..4294967295)")
        if not (0 <= self.epoch <= 0xFFFF):
            raise CorruptFrameError(f"epoch {self.epoch} out of uint16 range (0..65535)")
        if len(self.payload) > MAX_PAYLOAD_SIZE:
            raise PayloadOverflowError(
                f"Payload size {len(self.payload)} exceeds maximum allowed {MAX_PAYLOAD_SIZE} bytes"
            )

    def encode(self) -> bytes:
        """Encode this frame into its 12-byte header + binary payload representation."""
        header = struct.pack(
            HEADER_FORMAT,
            self.stream_id,
            int(self.channel),
            self.seq,
            int(self.signal),
            self.epoch,
            len(self.payload),
        )
        return header + self.payload

    @classmethod
    def decode(cls, data: bytes) -> Tuple[StreamFrame, bytes]:
        """Decode a single StreamFrame from raw bytes.

        Returns:
            Tuple of (decoded StreamFrame, remaining unconsumed bytes).

        Raises:
            IncompleteFrameError / ValueError: If data is smaller than 12 bytes or incomplete payload.
            CorruptFrameError / ValueError: If channel or signal values are unrecognized.
        """
        if len(data) < HEADER_SIZE:
            raise IncompleteFrameError(
                f"Buffer too small for frame header: {len(data)} bytes (required: {HEADER_SIZE})"
            )

        stream_id, ch, seq, sig, epoch, length = struct.unpack(
            HEADER_FORMAT, data[:HEADER_SIZE]
        )

        try:
            channel = StreamChannel(ch)
        except ValueError as err:
            raise CorruptFrameError(f"Invalid stream channel byte 0x{ch:02x}") from err

        try:
            signal = ControlSignal(sig)
        except ValueError as err:
            raise CorruptFrameError(f"Invalid control signal byte 0x{sig:02x}") from err

        total_len = HEADER_SIZE + length
        if len(data) < total_len:
            raise IncompleteFrameError(
                f"Incomplete frame payload: buffer has {len(data)} bytes, expected {total_len}"
            )

        payload = data[HEADER_SIZE:total_len]
        frame = cls(
            stream_id=stream_id,
            channel=channel,
            seq=seq,
            signal=signal,
            epoch=epoch,
            payload=payload,
        )
        return frame, data[total_len:]


def decode_all_frames(data: bytes) -> Tuple[List[StreamFrame], bytes]:
    """Pure helper to greedily decode all complete frames from a buffer.

    Returns:
        Tuple of (list of decoded StreamFrame objects, remaining incomplete tail bytes).
    """
    frames: List[StreamFrame] = []
    tail = data
    while len(tail) >= HEADER_SIZE:
        try:
            frame, tail = StreamFrame.decode(tail)
            frames.append(frame)
        except IncompleteFrameError:
            # Trailing partial frame; preserve for next buffer chunk
            break
    return frames, tail


def encode_frames(frames: Sequence[StreamFrame]) -> bytes:
    """Pure helper to encode a sequence of frames into a continuous byte sequence."""
    return b"".join(frame.encode() for frame in frames)
