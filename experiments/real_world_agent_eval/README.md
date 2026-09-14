# Real-World Agent Evaluation Benchmark: In-Memory KV Store with DAFG Supervision

## 1. Overview & Problem Context

Previous synthetic organism benchmarks suffered from **mock saturation and self-referential evaluation loops**:
- Gate check harnesses (such as `test_system.py`) caught `ImportError: pass` and printed `*_PASS` regardless of whether functional code was implemented.
- Minimal facade modules containing only empty stubs were awarded **94.3 / 100** scores and `VERIFIED_DELIVERY` status, despite having zero functional KV store implementation, zero HTTP endpoints, and a ground-truth pass rate of **0.0%** (a false-positive discrepancy gap of **+94.3**).

This benchmark establishes a **closed-loop, objective evaluation architecture** that breaks self-referential loops:
1. **Real Code-Generating Agent Execution**: A dual-mode CLI worker (`agent_worker/agent_cli.py`) generating genuine Python source files (`src/kv_store.py`, `src/server.py`) with calibrated realistic defect progressions (Gens 1–4).
2. **Objective Functional Gate Verification**: An un-mocked gate test harness (`harness/test_service.py`) that executes live in-memory assertions and live loopback HTTP socket requests using the Python standard library (`urllib.request`).
3. **Independent Adversarial Ground-Truth Oracle**: A 20-test external blackbox pytest suite (`tests_external/test_kv_ground_truth.py`) completely isolated from DAFG gate ledgers, asserting on real HTTP status codes, JSON schemas, monotonic TTL timing, and 50-thread concurrent atomic contention.
4. **Discrepancy Auditing**: Mathematical correlation of DAFG's internal scores against external ground-truth pass rates:
   $$\text{Discrepancy} = \text{Internal Score} - (\text{External Ground-Truth Pass Rate} \times 100)$$

---

## 2. Benchmark Architecture

```
experiments/real_world_agent_eval/
├── README.md                           # This documentation
├── PROMPT.txt                          # Detailed architectural specification for KV store
├── GATES.md                            # Acceptance gate ledger (G1–G5)
├── test_service.py                     # Root forwarder executing harness/test_service.py
├── agent_worker/
│   ├── __init__.py
│   └── agent_cli.py                    # Dual-mode agent CLI (real CLI / staged Gens 1-4)
├── harness/
│   ├── __init__.py
│   └── test_service.py                 # Objective functional gate harness (CORE, STORAGE, PROTOCOL, CONCURRENCY, E2E)
├── src/                                # Reference implementation (Gen 4 Verified Delivery)
│   ├── __init__.py
│   ├── kv_store.py                     # Thread-safe KV store engine with monotonic TTL
│   └── server.py                       # ThreadingHTTPServer daemon with body read & ephemeral port
├── generations/                        # Staged multi-generation defect benchmarks
│   ├── gen_1_syntax_error/             # Gen 1: Syntax error in src/server.py
│   ├── gen_2_logic_flaw/               # Gen 2: Inverted TTL check & missing DELETE
│   ├── gen_3_concurrency_race/         # Gen 3: Unsynchronized incr race condition
│   └── gen_4_verified_delivery/        # Gen 4: Fully thread-safe delivery (100% GT)
├── tests_external/                     # Isolated adversarial ground-truth oracle
│   ├── __init__.py
│   ├── conftest.py                     # Ephemeral port allocator, healthcheck polling, telemetry writer
│   └── test_kv_ground_truth.py         # 20 adversarial tests (CRUD, TTL, 50-thread incr, errors)
└── eval_results/
    └── ground_truth.json               # Output telemetry from external oracle
```

---

## 3. Calibrated Defect Generations (`agent_cli.py`)

The agent wrapper supports `--mode real` (invoking local CLI agents like `omp`, `claude`, or `codex`) and `--mode staged` (generating reproducible calibrated defects):

| Generation | Defect Category | Manifestation | Gate Harness Impact | GT Pass Rate |
|---|---|---|---|:---:|
| **Gen 1** | Syntax Error | Unclosed parenthesis in `src/server.py` | Fails `py_compile`, fails import in `PROTOCOL` & `E2E` | 0.0% (0/20) |
| **Gen 2** | Logic Flaw | Inverted monotonic TTL (`< expiry` returns expired) and omitted `DELETE` | Fails `CORE` on TTL/delete, fails `PROTOCOL` on `DELETE` (501) | ~15.0% (3/20) |
| **Gen 3** | Concurrency Defect | Missing mutex lock in `incr()` with micro-yield context switch | Passes `CORE`, `STORAGE`, `PROTOCOL`, but fails `CONCURRENCY` with lost updates | ~65.0% (13/20) |
| **Gen 4** | Verified Delivery | Full `threading.Lock()`, monotonic TTL, body reading, and ephemeral port support | Passes `CORE`, `STORAGE`, `PROTOCOL`, `CONCURRENCY`, `E2E` | 100.0% (20/20) |

---

## 4. Objective Gate Verification (`harness/test_service.py` & `GATES.md`)

The gate ledger enforces five objective functional gates approved by `SafeCommandPolicy.ALLOWED_COMMAND_PREFIXES`:

```markdown
- [ ] G1: KVStore Core Engine & Monotonic TTL
  CHECK: uv run python test_service.py CORE
  EXPECT: CORE_PASS
  OWNS: src/kv_store.py

- [ ] G2: Storage Engine & JSON Type Preservation
  CHECK: uv run python test_service.py STORAGE
  EXPECT: STORAGE_PASS
  OWNS: src/kv_store.py

- [ ] G3: HTTP REST API Protocol & Error Handling
  CHECK: uv run python test_service.py PROTOCOL
  EXPECT: PROTOCOL_PASS
  OWNS: src/server.py

- [ ] G4: Atomic Concurrency & Mutex Linearizability
  CHECK: uv run python test_service.py CONCURRENCY
  EXPECT: CONCURRENCY_PASS
  OWNS: src/kv_store.py

- [ ] G5: Full KV Store Server E2E Integration
  CHECK: uv run python test_service.py E2E
  EXPECT: E2E_PASS
  OWNS: src/server.py src/kv_store.py
```

### Safety & Integrity Controls
- **Zero Self-Referential Stubs**: `test_service.py` imports genuine modules, runs live assertions, and exits non-zero (`sys.exit(1)`) on any error or missing component. No swallowed `ImportError`.
- **Zero External Dependencies**: Uses Python standard library only (`urllib.request`, `json`, `time`, `socket`, `threading`).
- **SafeCommandPolicy Compliance**: Strictly conforms to DAFG command sandboxing (no shell pipelines, no forbidden binaries like `curl`).

---

## 5. Independent Adversarial Ground-Truth Oracle

The oracle (`tests_external/test_kv_ground_truth.py`) runs completely out-of-band against the running server over live TCP loopback sockets:
- **Tier 1 (Feature Coverage)**: Basic CRUD, type preservation (int, float, bool, list, dict), explicit null distinction, and state reset (`POST /reset`).
- **Tier 2 (Boundary & Corner Cases)**: Non-existent keys (404), negative/zero TTL (400), malformed JSON (400), missing `"value"` field (400), empty request body (400), and URL percent-encoding roundtrips.
- **Tier 3 (Cross-Feature Combinations)**: Monotonic TTL expiration after sleep, TTL clearing on rewrite without TTL, and TTL extension on rewrite.
- **Tier 4 (Real-World Concurrency)**: 50 concurrent worker threads executing 500 atomic increments with zero lost updates (verifying exact contiguous sequence $1..500$), arbitrary signed deltas under concurrency, and 50-thread mixed read/write/delete/increment contention storms.

---

## 6. Discrepancy Auditing & Metric Correlation

By comparing DAFG's internal scores with external ground-truth pass rates:

| Configuration | Internal DAFG Score | External GT Pass Rate | Discrepancy Gap | Verdict |
|---|:---:|:---:|:---:|---|
| **Synthetic Baseline** (`redis_organism_eval`) | 94.3 | 0.0% | **+94.3** | **False Delivery / Mock Saturation** |
| **Gen 1** (Syntax Error) | ~0.0 | 0.0% | **0.0** | Honest Early Rejection |
| **Gen 2** (Logic Flaw) | ~40.0 | 15.0% | **+25.0** | Partial Delivery Defect Caught |
| **Gen 3** (Concurrency Defect) | ~60.0 | 65.0% | **-5.0** | Concurrency Gate Rejection |
| **Gen 4** (Verified Delivery) | ~95.0 | 100.0% | **-5.0** | **Authentic Verified Delivery** |

Gen 4 achieves an external ground-truth pass rate of **100.0% (20/20 passed)**, validating that DAFG's gate verification represents true functional software delivery.

---

## 7. Reproduction & Verification Commands

### 1. Stage Defect Generations
```bash
uv run python experiments/real_world_agent_eval/agent_worker/agent_cli.py --workdir experiments/real_world_agent_eval/generations/gen_1_syntax_error --mode staged --generation 1
uv run python experiments/real_world_agent_eval/agent_worker/agent_cli.py --workdir experiments/real_world_agent_eval/generations/gen_2_logic_flaw --mode staged --generation 2
uv run python experiments/real_world_agent_eval/agent_worker/agent_cli.py --workdir experiments/real_world_agent_eval/generations/gen_3_concurrency_race --mode staged --generation 3
uv run python experiments/real_world_agent_eval/agent_worker/agent_cli.py --workdir experiments/real_world_agent_eval/generations/gen_4_verified_delivery --mode staged --generation 4
```

### 2. Verify Gate Harness Passes on Gen 4
```bash
cd experiments/real_world_agent_eval
uv run python test_service.py CORE
uv run python test_service.py STORAGE
uv run python test_service.py PROTOCOL
uv run python test_service.py CONCURRENCY
uv run python test_service.py E2E
```

### 3. Verify Gate Harness Fails on Defective Generations
```bash
# Gen 1 fails syntax/compilation
KV_SERVER_WORKDIR=generations/gen_1_syntax_error uv run python test_service.py PROTOCOL

# Gen 2 fails TTL logic and missing DELETE
KV_SERVER_WORKDIR=generations/gen_2_logic_flaw uv run python test_service.py CORE
KV_SERVER_WORKDIR=generations/gen_2_logic_flaw uv run python test_service.py PROTOCOL

# Gen 3 fails atomic concurrency under 50 threads
KV_SERVER_WORKDIR=generations/gen_3_concurrency_race uv run python test_service.py CONCURRENCY
```

### 4. Verify Gate Ledger Linting
```bash
uv run gates --lint experiments/real_world_agent_eval/GATES.md
```

### 5. Execute External Adversarial Ground-Truth Oracle
```bash
uv run pytest experiments/real_world_agent_eval/tests_external/test_kv_ground_truth.py -v
```

### 6. Full Repository Test Suite
```bash
uv run pytest -q
```
