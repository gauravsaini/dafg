"""Pins v04_p04: length-prefixed framing round-trip and truncation detection."""
from src.v04.p04.frame import encode
from src.v04.p04.decode import decode_one, IncompleteFrame

p1, p2 = b"hello", b"world!"
blob = encode(p1) + encode(p2)
out1, rest = decode_one(blob)
out2, rest2 = decode_one(rest)
assert out1 == p1 and out2 == p2 and rest2 == b""
try:
    decode_one(encode(p1)[:3])
    raise AssertionError("expected IncompleteFrame")
except IncompleteFrame:
    pass
try:
    decode_one(encode(p1)[:-1])
    raise AssertionError("expected IncompleteFrame")
except IncompleteFrame:
    pass
print("EVAL_PASSED")
