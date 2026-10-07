"""Pins v04_c03: TTL expiry with injected clock; eviction counts."""
from src.v04.c03.cache import TTLCache, KeyExpired
from src.v04.c03.evict import evict_expired

class FakeClock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t

clk = FakeClock()
c = TTLCache(clock=clk)
c.set("a", 1, ttl_s=10)
c.set("b", 2, ttl_s=100)
assert c.get("a") == 1
clk.t = 11.0
try:
    c.get("a")
    raise AssertionError("expected KeyExpired")
except KeyExpired:
    pass
assert c.get("b") == 2
# the expired get() above already removed "a"; add a fresh expired key for eviction
c.set("c", 3, ttl_s=1)
clk.t = 13.0
assert evict_expired(c) == 1
assert len(c) == 1
print("EVAL_PASSED")
