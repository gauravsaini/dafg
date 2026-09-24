"""Unit test suite for DAFG streaming transport wire protocol.

Verifies:
- 12-byte fixed binary header packing and network byte order (!HBIHIB)
- Pure round-trip serialization and deserialization
- Multi-frame stream decoding and fragmentation handling
- Boundary validation (empty payloads, 65535 byte maximum, out-of-range fields)
- Corrupt frame and incomplete buffer error handling
- Immutability and pure function contracts
"""

import pytest

from dafg.transport import (
    ControlSignal,
    CorruptFrameError,
    HEADER_SIZE,
    IncompleteFrameError,
    MAX_PAYLOAD_SIZE,
    PayloadOverflowError,
    StreamChannel,
    StreamFrame,
    decode_all_frames,
    encode_frames,
)


def test_frame_header_size():
    """Header must strictly match the 12-byte specification."""
    assert HEADER_SIZE == 12
    frame = StreamFrame(
        stream_id=1,
        channel=StreamChannel.DATA,
        seq=0,
        signal=ControlSignal.NOOP,
        epoch=1,
        payload=b"",
    )
    encoded = frame.encode()
    assert len(encoded) == 12


def test_round_trip_basic():
    """Verify standard data frame encoding and decoding."""
    payload = "def test_solution(): pass".encode("utf-8")
    frame = StreamFrame(
        stream_id=42,
        channel=StreamChannel.DATA,
        seq=1001,
        signal=ControlSignal.NOOP,
        epoch=3,
        payload=payload,
    )
    encoded = frame.encode()
    assert len(encoded) == 12 + len(payload)

    decoded, tail = StreamFrame.decode(encoded)
    assert tail == b""
    assert decoded.stream_id == 42
    assert decoded.channel == StreamChannel.DATA
    assert decoded.seq == 1001
    assert decoded.signal == ControlSignal.NOOP
    assert decoded.epoch == 3
    assert decoded.payload == payload
    assert decoded == frame


@pytest.mark.parametrize(
    "channel,signal",
    [
        (StreamChannel.DATA, ControlSignal.NOOP),
        (StreamChannel.CONTROL, ControlSignal.ABORT),
        (StreamChannel.CONTROL, ControlSignal.STEER),
        (StreamChannel.CONTROL, ControlSignal.PAUSE),
        (StreamChannel.CONTROL, ControlSignal.RESUME),
        (StreamChannel.TELEMETRY, ControlSignal.NOOP),
    ],
)
def test_round_trip_channels_and_signals(channel, signal):
    """Verify all channel and control signal variants round-trip cleanly."""
    frame = StreamFrame(
        stream_id=10,
        channel=channel,
        seq=55,
        signal=signal,
        epoch=2,
        payload=b"test-payload",
    )
    decoded, tail = StreamFrame.decode(frame.encode())
    assert tail == b""
    assert decoded.channel == channel
    assert decoded.signal == signal


def test_boundary_values():
    """Verify boundary conditions for 16-bit and 32-bit integer fields."""
    max_frame = StreamFrame(
        stream_id=0xFFFF,
        channel=StreamChannel.DATA,
        seq=0xFFFFFFFF,
        signal=ControlSignal.ABORT,
        epoch=0xFFFF,
        payload=b"x" * 10,
    )
    decoded, _ = StreamFrame.decode(max_frame.encode())
    assert decoded.stream_id == 65535
    assert decoded.seq == 4294967295
    assert decoded.epoch == 65535

    zero_frame = StreamFrame(
        stream_id=0,
        channel=StreamChannel.CONTROL,
        seq=0,
        signal=ControlSignal.NOOP,
        epoch=0,
        payload=b"",
    )
    decoded_zero, _ = StreamFrame.decode(zero_frame.encode())
    assert decoded_zero.stream_id == 0
    assert decoded_zero.seq == 0
    assert decoded_zero.epoch == 0
    assert decoded_zero.payload == b""


def test_max_payload_boundary():
    """Verify maximum uint16 payload (65535 bytes) is accepted and larger is rejected."""
    max_payload = b"A" * MAX_PAYLOAD_SIZE
    frame = StreamFrame(
        stream_id=1,
        channel=StreamChannel.DATA,
        seq=1,
        signal=ControlSignal.NOOP,
        epoch=1,
        payload=max_payload,
    )
    encoded = frame.encode()
    decoded, tail = StreamFrame.decode(encoded)
    assert tail == b""
    assert len(decoded.payload) == MAX_PAYLOAD_SIZE

    overflow_payload = b"A" * (MAX_PAYLOAD_SIZE + 1)
    with pytest.raises(PayloadOverflowError):
        StreamFrame(
            stream_id=1,
            channel=StreamChannel.DATA,
            seq=1,
            signal=ControlSignal.NOOP,
            epoch=1,
            payload=overflow_payload,
        )


def test_out_of_range_fields_raise():
    """Verify integer overflow checks in StreamFrame __post_init__."""
    with pytest.raises(CorruptFrameError):
        StreamFrame(
            stream_id=0x10000,
            channel=StreamChannel.DATA,
            seq=0,
            signal=ControlSignal.NOOP,
            epoch=0,
        )

    with pytest.raises(CorruptFrameError):
        StreamFrame(
            stream_id=1,
            channel=StreamChannel.DATA,
            seq=0x100000000,
            signal=ControlSignal.NOOP,
            epoch=0,
        )

    with pytest.raises(CorruptFrameError):
        StreamFrame(
            stream_id=1,
            channel=StreamChannel.DATA,
            seq=0,
            signal=ControlSignal.NOOP,
            epoch=0x10000,
        )


def test_incomplete_buffer_handling():
    """Verify IncompleteFrameError when buffer is smaller than header or payload."""
    raw = StreamFrame(
        stream_id=1,
        channel=StreamChannel.DATA,
        seq=1,
        signal=ControlSignal.NOOP,
        epoch=1,
        payload=b"1234567890",
    ).encode()

    # Smaller than 12-byte header
    for cut in range(1, HEADER_SIZE):
        with pytest.raises(IncompleteFrameError):
            StreamFrame.decode(raw[:cut])

    # Smaller than header + full payload
    for cut in range(HEADER_SIZE, len(raw) - 1):
        with pytest.raises(IncompleteFrameError):
            StreamFrame.decode(raw[:cut])


def test_corrupt_channel_and_signal():
    """Verify CorruptFrameError when encountering undefined channel or signal bytes."""
    valid_raw = bytearray(
        StreamFrame(
            stream_id=1,
            channel=StreamChannel.DATA,
            seq=1,
            signal=ControlSignal.NOOP,
            epoch=1,
            payload=b"abc",
        ).encode()
    )

    # Corrupt channel byte (index 2 in !HBIHIB: 2 bytes stream_id, 1 byte channel)
    corrupted_ch = bytearray(valid_raw)
    corrupted_ch[2] = 0x99
    with pytest.raises(CorruptFrameError):
        StreamFrame.decode(bytes(corrupted_ch))

    # Corrupt signal byte (index 7 in !HBIHIB: 2 + 1 + 4 = 7)
    corrupted_sig = bytearray(valid_raw)
    corrupted_sig[7] = 0xFE
    with pytest.raises(CorruptFrameError):
        StreamFrame.decode(bytes(corrupted_sig))


def test_multi_frame_stream_and_fragmentation():
    """Verify decode_all_frames and encode_frames across multiple sequential frames."""
    f1 = StreamFrame(1, StreamChannel.DATA, 1, ControlSignal.NOOP, 1, b"chunk_1")
    f2 = StreamFrame(1, StreamChannel.DATA, 2, ControlSignal.NOOP, 1, b"chunk_2")
    f3 = StreamFrame(1, StreamChannel.CONTROL, 3, ControlSignal.ABORT, 1, b"reason:boundary_breach")

    stream_bytes = encode_frames([f1, f2, f3])
    frames, tail = decode_all_frames(stream_bytes)
    assert len(frames) == 3
    assert tail == b""
    assert frames[0] == f1
    assert frames[1] == f2
    assert frames[2] == f3

    # Add trailing fragmented bytes (partial header of 4th frame)
    fragmented = stream_bytes + b"\x00\x01\x01\x00"
    frames2, tail2 = decode_all_frames(fragmented)
    assert len(frames2) == 3
    assert tail2 == b"\x00\x01\x01\x00"


def test_frame_immutability():
    """Verify StreamFrame is frozen dataclass (pure function rule)."""
    frame = StreamFrame(1, StreamChannel.DATA, 1, ControlSignal.NOOP, 1, b"data")
    with pytest.raises(Exception):  # FrozenInstanceError
        frame.seq = 2  # type: ignore
