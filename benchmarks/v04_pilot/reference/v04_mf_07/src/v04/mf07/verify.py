"""Token verification."""
from __future__ import annotations
import hashlib
import hmac

class TokenExpired(Exception):
    pass

class BadSignature(Exception):
    pass

def verify(token: str, now: float, secret: str) -> str:
    try:
        subject, exp_s, sig = token.split(":")
        exp = int(exp_s)
    except ValueError:
        raise BadSignature("malformed token")
    good = hmac.new(secret.encode(), f"{subject}:{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig):
        raise BadSignature("signature mismatch")
    if now > exp:
        raise TokenExpired("token expired")
    return subject
