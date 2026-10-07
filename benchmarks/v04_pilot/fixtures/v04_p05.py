"""Pins v04_p05: exponential backoff values and retryable-status decisions."""
from src.v04.p05.policy import backoff_delay
from src.v04.p05.should_retry import should_retry

assert backoff_delay(0) == 1.0
assert backoff_delay(1) == 2.0
assert backoff_delay(2) == 4.0
assert backoff_delay(10) == 30.0
assert backoff_delay(3, base=0.5, cap=1.0) == 1.0
assert should_retry(503, 0, 3) is True
assert should_retry(429, 2, 3) is True
assert should_retry(404, 0, 3) is False
assert should_retry(400, 0, 3) is False
assert should_retry(503, 3, 3) is False
print("EVAL_PASSED")
