# Acceptance Gates: Stage Scaling — Phase 1 Baseline

- [x] G1: Test suite passes all baseline checks
  CHECK: node test_service.js
  EXPECT: HEALTH_PASS
  CWD: .
  OWNS: src/server.js, src/data/store.js, test_service.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.554884+00:00 match='HEALTH_PASS'

- [x] G2: Health endpoint returns status, timestamp, and uptime
  CHECK: node test_service.js HEALTH
  EXPECT: HEALTH_PASS
  CWD: .
  OWNS: src/server.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.819833+00:00 match='HEALTH_PASS'

- [x] G3: Data store supports full CRUD lifecycle
  CHECK: node test_service.js DATASTORE
  EXPECT: DATASTORE_PASS
  CWD: .
  OWNS: src/data/store.js, src/data/repository.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.869026+00:00 match='DATASTORE_PASS'

- [x] G4: Repository abstraction layer works correctly
  CHECK: node test_service.js REPOSITORY
  EXPECT: REPOSITORY_PASS
  CWD: .
  OWNS: src/data/repository.js, src/data/store.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.917614+00:00 match='REPOSITORY_PASS'

- [x] G5: 404 returned for unknown routes
  CHECK: node test_service.js NOTFOUND
  EXPECT: NOTFOUND_PASS
  CWD: .
  OWNS: src/server.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.971328+00:00 match='NOTFOUND_PASS'

- [x] G6: Server handles internal errors with 500 status
  CHECK: node test_service.js ERROR
  EXPECT: ERROR_PASS
  CWD: .
  OWNS: src/server.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:43.023965+00:00 match='ERROR_PASS'

- [x] G7: All modules import cleanly
  CHECK: node test_service.js IMPORT
  EXPECT: IMPORT_PASS
  CWD: .
  OWNS: src/server.js, src/data/store.js, src/data/repository.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:43.071087+00:00 match='IMPORT_PASS'

- [x] G8: Users API — CRUD operations work correctly
  CHECK: node test_service.js USERS
  EXPECT: USERS_PASS
  CWD: .
  OWNS: src/routes/users.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.608740+00:00 match='USERS_PASS'

- [x] G9: Products API — catalog operations work correctly
  CHECK: node test_service.js PRODUCTS
  EXPECT: PRODUCTS_PASS
  CWD: .
  OWNS: src/routes/products.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.662500+00:00 match='PRODUCTS_PASS'

- [x] G10: Orders API — order operations work correctly
  CHECK: node test_service.js ORDERS
  EXPECT: ORDERS_PASS
  CWD: .
  OWNS: src/routes/orders.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.719157+00:00 match='ORDERS_PASS'

- [x] G11: Metrics API — returns request count, uptime, memory, timestamp
  CHECK: node test_service.js METRICS
  EXPECT: METRICS_PASS
  CWD: .
  OWNS: src/routes/metrics.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.770246+00:00 match='METRICS_PASS'

- [x] G12: All Phase 2 endpoints pass full integration
  CHECK: node test_service.js
  EXPECT: HEALTH_PASS
  CWD: .
  OWNS: src/routes/users.js, src/routes/products.js, src/routes/orders.js, src/routes/metrics.js, src/routes/index.js, src/server.js, test_service.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:43.133856+00:00 match='HEALTH_PASS'
