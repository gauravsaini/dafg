# Project: Real-World Agent Evaluation Benchmark (KV Store with DAFG Organism)

## Architecture
This project establishes an end-to-end evaluation benchmark where a real local CLI code-generating agent implements a fast in-memory KV store with TTL, atomic increments, and HTTP REST interface under the supervision of the DAFG Organism runtime. The completion claims and internal scores of DAFG are validated against an independent adversarial ground-truth test suite completely external to DAFG's gate ledger.

### Data Flow & Component Layout
1. **Isolated External Ground-Truth Oracle** (`experiments/real_world_agent_eval/tests_external/test_kv_ground_truth.py`):
   - Standalone pytest suite completely isolated from `OrganismGenesis` and `GATES.md`.
   - Exercises real HTTP requests (POST, GET, DELETE, INCR) over live TCP sockets against the running server.
   - Asserts on status codes (200, 201, 400, 404), JSON response bodies, monotonic TTL expiry timing, and concurrency contention (50-100 threads).
   - Generates machine-readable `eval_results/ground_truth.json` containing pass rate and test counts.
2. **Real Code-Generating Agent Wrapper** (`experiments/real_world_agent_eval/agent_worker/agent_cli.py`):
   - TaskNode executions dispatch implementation work to this local CLI agent.
   - Dual-mode operation: live CLI agent execution (e.g. `omp -p`) or calibrated multi-generation defect progression (Gen 1 syntax error -> Gen 2 logic flaw -> Gen 3 concurrency race -> Gen 4 thread-safe delivery).
   - Generates actual files: `src/kv_store.py` and `src/server.py`.
3. **Objective Functional Gate Verification** (`experiments/real_world_agent_eval/harness/test_service.py` & `GATES.md`):
   - Replaces self-referential stubs (`test_system.py`) with live functional assertions using Python standard library `urllib.request`.
   - Complies with `SafeCommandPolicy.ALLOWED_COMMAND_PREFIXES` (`uv run python test_service.py <TEST>`).
   - Fails gates when code is missing, has syntax errors, broken logic, or concurrency bugs.
4. **Programmatic Evaluation & Discrepancy Auditing** (`src/dafg/compare.py` & `run_benchmark.py`):
   - Extends `dafg compare` to read `eval_results/ground_truth.json` and compute discrepancy:
     `Discrepancy = Internal Score - (GT Pass Rate * 100)`.
   - Proves whether DAFG's internal `VERIFIED_DELIVERY` represents authentic external functional validity.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Ground-Truth CRUD & Status Codes | Isolated pytest asserting GET, POST, DELETE with status codes 200, 201, 404 | M1 | Survey (R1) |
| 2 | Ground-Truth TTL Expiry Timing | Assert key present, sleep past TTL, assert 404 and expired | M1 | Survey (R1) |
| 3 | Ground-Truth Atomic INCR & Concurrency | 50 concurrent threads incrementing key; assert 0 lost updates | M1 | Survey (R1) |
| 4 | Ground-Truth HTTP Error Handling | Assert 400 on malformed JSON, negative TTL, non-integer increment | M1 | Survey (R1) |
| 5 | Ground-Truth Dynamic Port & Teardown | Ephemeral port 0 binding, health polling, clean process teardown | M1 | Survey (R1) |
| 6 | Ground-Truth Telemetry Output | Write `eval_results/ground_truth.json` with pass rate and test metrics | M1 | Survey (R1) |
| 7 | Local CLI Agent Dispatcher | CLI wrapper supporting live CLI execution and calibrated defect progression | M2 | Survey (R2) |
| 8 | Multi-Generation Code Defect Staging | Staging Gen 1 (syntax), Gen 2 (logic), Gen 3 (race), Gen 4 (clean) | M2 | Survey (R2) |
| 9 | In-Memory KV Store Core Engine | Python stdlib KV store with thread-safe locking and monotonic TTL | M2 | Survey (R2) |
| 10 | Stdlib Threading HTTP REST Server | Multi-threaded HTTP daemon handling `/health`, `/keys`, `/incr` with body read | M2 | Survey (R2) |
| 11 | Functional Gate Test Harness | `test_service.py` issuing real socket/HTTP checks, allowed by SafeCommandPolicy | M2 | Survey (R3) |
| 12 | Objective GATES.md Construction | GATES.md without self-referential pass-through stubs | M2 | Survey (R3) |
| 13 | Multi-Generation Benchmark Execution | Orchestrating multi-generation run saving telemetry in `generations/` | M3 | Survey (R4) |
| 14 | Ground-Truth Extension to dafg compare | Extend `src/dafg/compare.py` to parse GT results and display Discrepancy | M3 | Survey (R4) |
| 15 | Discrepancy & Correlation Analysis | Verify Gen 4 has near-zero discrepancy while baseline exhibits +94.3 gap | M3 | Survey (R4) |
| 16 | Comprehensive E2E Verification | End-to-end pytest verification and stop-hook compliance | M4 | Survey (R4) |

## Milestones
| # | Name | Scope | Dependencies | Status | Key Deliverables |
|---|------|-------|-------------|--------|------------------|
| M1 | External Ground-Truth Oracle | Author `tests_external/test_kv_ground_truth.py` and fixture harness | None | DONE | `tests_external/` (20 tests, conftest.py, telemetry hook) |
| M2 | Real Agent & Functional Gates | Author `agent_worker/agent_cli.py`, `harness/test_service.py`, `GATES.md`, and KV store reference engine | M1 | IN_PROGRESS | `agent_worker/`, `harness/`, `GATES.md`, reference KV engine |
| M3 | Benchmark Execution & dafg compare | Execute multi-generation benchmark, update `src/dafg/compare.py`, produce audit telemetry | M2 | PLANNED | `generations/`, `src/dafg/compare.py` GT extensions, `eval_results/` |
| M4 | Adversarial Verification & Gate Audit | Run Challenger and Forensic Auditor, verify all gates and tests pass offline | M3 | PLANNED | Forensic audit clean verdict, full pytest pass |

## Interface Contracts
### `tests_external/test_kv_ground_truth.py` ↔ Running KV Server
- Base URL: `http://127.0.0.1:<port>`
- `GET /health` -> `200 OK`, JSON `{"status": "ok" | "healthy"}`
- `POST /keys/<key>` -> Body `{"value": <any>, "ttl": <optional float>}`, `200 OK` (or `201 Created`)
- `GET /keys/<key>` -> `200 OK` with `{"key": "<key>", "value": <val>}`, or `404 Not Found`
- `DELETE /keys/<key>` -> `200 OK` with `{"status": "ok", "deleted": true}`, or `404 Not Found`
- `POST /keys/<key>/incr` (or `/incr/<key>`) -> Body `{"amount": <int>}`, `200 OK` with `{"key": "<key>", "value": <int>}`, or `400 Bad Request`

### `dafg compare` ↔ `eval_results/ground_truth.json`
- Schema:
  ```json
  {
    "total": 20,
    "passed": 20,
    "failed": 0,
    "pass_rate": 1.0,
    "duration_seconds": 1.03
  }
  ```
- Output columns added to Markdown table: `GT Pass Rate` and `Discrepancy`.

## Code Layout
```
experiments/real_world_agent_eval/
├── README.md
├── PROMPT.txt
├── run_benchmark.py
├── tests_external/
│   ├── __init__.py
│   ├── conftest.py
│   └── test_kv_ground_truth.py
├── agent_worker/
│   ├── __init__.py
│   └── agent_cli.py
├── harness/
│   └── test_service.py
├── generations/
│   ├── gen_1_syntax_error/
│   ├── gen_2_logic_flaw/
│   ├── gen_3_concurrency_race/
│   └── gen_4_verified_delivery/
└── eval_results/
    ├── ground_truth.json
    ├── benchmark_comparison.json
    └── comparison_matrix.md
```
