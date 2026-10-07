"""Rate-limited calls."""
from __future__ import annotations

class RateLimited(Exception):
    pass

def call_limited(bucket, fn):
    if bucket.take():
        return fn()
    raise RateLimited("rate limit exceeded")
