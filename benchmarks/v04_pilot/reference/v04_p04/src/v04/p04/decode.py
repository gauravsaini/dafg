"""Frame decoding."""
from __future__ import annotations
import struct

class IncompleteFrame(Exception):
    pass

class FrameTooLarge(Exception):
    pass

def decode_one(buf: bytes):
    if len(buf) < 4:
        raise IncompleteFrame("need length prefix")
    (n,) = struct.unpack(">I", buf[:4])
    if n > (1 << 20):
        raise FrameTooLarge("frame too large")
    if len(buf) < 4 + n:
        raise IncompleteFrame("truncated payload")
    return buf[4:4+n], buf[4+n:]
