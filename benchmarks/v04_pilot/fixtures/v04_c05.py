"""Pins v04_c05: token bucket with fake clock; limited calls."""
from src.v04.c05.bucket import TokenBucket
from src.v04.c05.api import call_limited, RateLimited

class FakeClock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t

clk = FakeClock()
b = TokenBucket(rate_per_s=1.0, capacity=3, clock=clk)
assert [b.take() for _ in range(3)] == [True, True, True]
assert b.take() is False
clk.t = 1.5
assert b.take() is True
assert b.take() is False
try:
    call_limited(b, lambda: "ok")
    raise AssertionError("expected RateLimited")
except RateLimited:
    pass
clk.t = 3.0
assert call_limited(b, lambda: "ok") == "ok"
print("EVAL_PASSED")
