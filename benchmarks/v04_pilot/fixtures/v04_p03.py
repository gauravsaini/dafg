"""Pins v04_p03: monotonic audit sequence numbers and tamper detection."""
from src.v04.p03.audit import AuditLog
from src.v04.p03.verify import check_monotonic

log = AuditLog()
log.append("login")
log.append("pay")
log.append("logout")
ents = log.entries()
assert [e["seq"] for e in ents] == [1, 2, 3]
assert check_monotonic(ents) is True
tampered = [dict(e) for e in ents]
tampered[1]["seq"] = 99
assert check_monotonic(tampered) is False
assert check_monotonic([]) is True
print("EVAL_PASSED")
