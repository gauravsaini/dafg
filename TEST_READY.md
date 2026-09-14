# E2E Test Suite Ready: real_world_agent_eval

## Test Runner
- Command: `uv run pytest experiments/real_world_agent_eval/tests_external/test_kv_ground_truth.py -v`
- Expected: all 20 tests pass with exit code 0 against a compliant running server

## Coverage Summary
| Tier | Count | Description |
|------|------:|-------------|
| 1. Feature Coverage | 8 | String CRUD, JSON types, Null distinction, Reset |
| 2. Boundary & Corner | 6 | Negative/zero TTL, malformed JSON, missing field, empty body, URL encoding, missing 404 |
| 3. Cross-Feature | 3 | TTL expiration, TTL clearing on rewrite, TTL extension on rewrite |
| 4. Real-World Application & Concurrency | 3 | 50-thread concurrent atomic INCR (500 ops), arbitrary deltas, 50-thread mixed contention |
| **Total** | **20** | Full adversarial coverage |

## Feature Checklist
| Feature | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---------|:------:|:------:|:------:|:------:|
| Key Storage & Retrieval (CRUD) | ✓ | ✓ | ✓ | ✓ |
| Monotonic TTL Expiration | ✓ | ✓ | ✓ | ✓ |
| Atomic Increment Concurrency | ✓ | ✓ | ✓ | ✓ |
| HTTP Status Codes & Error Codes | ✓ | ✓ | ✓ | ✓ |
| Dynamic Port & Server Lifecycle | ✓ | ✓ | ✓ | ✓ |
| Ground-Truth Telemetry Persistence | ✓ | ✓ | ✓ | ✓ |
