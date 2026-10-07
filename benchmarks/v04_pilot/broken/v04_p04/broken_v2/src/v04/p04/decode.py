"""Frame decoding -- BROKEN: no truncation check."""
from __future__ import annotations
import struct

class IncompleteFrame(Exception):
    pass

class FrameTooLarge(Exception):
    pass

def decode_one(buf: bytes):
    (n,) = struct.unpack(">I", buf[:4])
    return buf[4:4+n], buf[4+n:]
