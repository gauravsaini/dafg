# E2E Test Infra: real_world_agent_eval

## Test Philosophy
- Opaque-box, requirement-driven. Completely isolated from internal gate mechanics.
- No dependency on implementation design or internal gate ledgers.
- High-concurrency adversarial assertions over real localhost HTTP sockets.

## Feature Inventory
| # | Feature | Source | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|--------|:------:|:------:|:------:|:------:|
| 1 | Key Storage & Retrieval (CRUD) | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ | ✓ |
| 2 | TTL Expiry Timing | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ | ✓ |
| 3 | Atomic INCR & Concurrency | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ | ✓ |
| 4 | HTTP Error Codes & Framing | ORIGINAL_REQUEST R1 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Test runner: `pytest experiments/real_world_agent_eval/tests_external/test_kv_ground_truth.py -v`
- Pass/Fail semantics: All tests must pass with exit code 0 against a running server.
- JSON output: Writes `eval_results/ground_truth.json` with test pass counts and rates.
- Directory layout: `experiments/real_world_agent_eval/tests_external/`

## Coverage Thresholds
- Tier 1 (Feature Coverage): Basic CRUD, healthcheck, simple TTL, simple INCR
- Tier 2 (Boundary & Corner): Negative TTL, non-integer increment, missing key 404, malformed JSON body 400, percent-encoded keys
- Tier 3 (Cross-Feature Combinations): Overwriting TTL on rewrite, deleting key then incrementing, TTL reset
- Tier 4 (Real-World & Concurrency): 50-thread concurrent atomic increment, mixed read/write/delete stress
