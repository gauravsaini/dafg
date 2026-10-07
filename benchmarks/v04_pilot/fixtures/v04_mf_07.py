"""Pins v04_mf_07: hmac token issue/verify with explicit clock; expiry, tamper, revocation."""
from src.v04.mf07.tokens import issue
from src.v04.mf07.verify import verify, TokenExpired, BadSignature
from src.v04.mf07.store import RevocationList

tok = issue("alice", ttl_s=60, now=1000.0, secret="s3cret")
subject, exp_s, sig = tok.split(":")
assert verify(tok, now=1050.0, secret="s3cret") == "alice"
try:
    verify(tok, now=2000.0, secret="s3cret")
    raise AssertionError("expected TokenExpired")
except TokenExpired:
    pass
bad = "alice:" + exp_s + ":" + "0" * 64
try:
    verify(bad, now=1050.0, secret="s3cret")
    raise AssertionError("expected BadSignature")
except BadSignature:
    pass
rl = RevocationList()
assert rl.is_revoked(sig) is False
rl.revoke(sig)
assert rl.is_revoked(sig) is True
print("EVAL_PASSED")
