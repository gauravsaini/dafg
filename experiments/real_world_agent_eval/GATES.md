# Acceptance Gates: In-Memory KV Store Real-World Agent Evaluation

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
