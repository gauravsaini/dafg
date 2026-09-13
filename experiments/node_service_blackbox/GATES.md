# Acceptance Gates: Node.js REST Service Blackbox

- [x] G1: Health check endpoint returns status ok
  CHECK: node test_service.js HEALTH
  EXPECT: HEALTH_PASS
  OWNS: src/server.js, src/routes/health.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.844911+00:00 match='HEALTH_PASS'

- [x] G2: Users resource supports CRUD operations
  CHECK: node test_service.js USERS
  EXPECT: USERS_PASS
  OWNS: src/routes/users.js, src/data/store.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.931596+00:00 match='USERS_PASS'

- [x] G3: Products catalog supports listing, fetching, and creating products
  CHECK: node test_service.js PRODUCTS
  EXPECT: PRODUCTS_PASS
  OWNS: src/routes/products.js, src/data/store.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.104760+00:00 match='PRODUCTS_PASS'

- [x] G4: Orders processing creates orders with validation
  CHECK: node test_service.js ORDERS
  EXPECT: ORDERS_PASS
  OWNS: src/routes/orders.js, src/data/store.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.191563+00:00 match='ORDERS_PASS'

- [x] G5: Error handling returns proper HTTP error codes
  CHECK: node test_service.js ERRORS
  EXPECT: ERRORS_PASS
  OWNS: src/middleware/error.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.019522+00:00 match='ERRORS_PASS'

- [x] G6: End-to-end happy path creates user, product, and order in sequence
  CHECK: node test_service.js E2E
  EXPECT: E2E_PASS
  OWNS: src/server.js, src/routes/health.js, src/routes/users.js, src/routes/products.js, src/routes/orders.js, src/data/store.js, src/middleware/error.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:42.280316+00:00 match='E2E_PASS'
