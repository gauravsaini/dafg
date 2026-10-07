"""Token issuance (hmac-signed)."""
from __future__ import annotations
import hashlib
import hmac

def issue(subject: str, ttl_s: int, now: float, secret: str) -> str:
    exp = int(now) + ttl_s
    sig = hmac.new(secret.encode(), f"{subject}:{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{subject}:{exp}:{sig}"
