# Acceptance Gates: blackbox_goal_organism — Node.js REST API

- [x] G1: Project structure and package.json exist
  CHECK: test -f package.json && test -f src/server.js && test -f src/data/store.js && test -f src/data/repository.js && echo "FILES_OK"
  EXPECT: FILES_OK
  OWNS: experiments/blackbox_goal_organism/package.json,experiments/blackbox_goal_organism/src/server.js,experiments/blackbox_goal_organism/src/data/store.js,experiments/blackbox_goal_organism/src/data/repository.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.052406+00:00 match='FILES_OK'

- [x] G2: All route modules exist
  CHECK: test -f src/routes/health.js && test -f src/routes/users.js && test -f src/routes/products.js && test -f src/routes/orders.js && test -f src/routes/metrics.js && test -f src/routes/index.js && echo "ROUTES_OK"
  EXPECT: ROUTES_OK
  OWNS: experiments/blackbox_goal_organism/src/routes/health.js,experiments/blackbox_goal_organism/src/routes/users.js,experiments/blackbox_goal_organism/src/routes/products.js,experiments/blackbox_goal_organism/src/routes/orders.js,experiments/blackbox_goal_organism/src/routes/metrics.js,experiments/blackbox_goal_organism/src/routes/index.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.064602+00:00 match='ROUTES_OK'

- [x] G3: Integration test exists and is executable
  CHECK: test -x test_service.js && echo "TEST_EXISTS"
  EXPECT: TEST_EXISTS
  OWNS: experiments/blackbox_goal_organism/test_service.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.077006+00:00 match='TEST_EXISTS'

- [x] G4: Health endpoint returns status ok
  CHECK: node test_service.js HEALTH
  EXPECT: PASSED:HEALTH
  OWNS: experiments/blackbox_goal_organism/test_service.js,experiments/blackbox_goal_organism/src/server.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.136440+00:00 match='PASSED:HEALTH'

- [x] G5: Users API — CRUD operations work
  CHECK: node test_service.js USERS
  EXPECT: PASSED:USERS
  OWNS: experiments/blackbox_goal_organism/test_service.js,experiments/blackbox_goal_organism/src/routes/users.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.192076+00:00 match='PASSED:USERS'

- [x] G6: Products API — catalog operations work
  CHECK: node test_service.js PRODUCTS
  EXPECT: PASSED:PRODUCTS
  OWNS: experiments/blackbox_goal_organism/test_service.js,experiments/blackbox_goal_organism/src/routes/products.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.249011+00:00 match='PASSED:PRODUCTS'

- [x] G7: Orders API — order processing works
  CHECK: node test_service.js ORDERS
  EXPECT: PASSED:ORDERS
  OWNS: experiments/blackbox_goal_organism/test_service.js,experiments/blackbox_goal_organism/src/routes/orders.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.307091+00:00 match='PASSED:ORDERS'

- [x] G8: Metrics API — request count, uptime, memory
  CHECK: node test_service.js METRICS
  EXPECT: PASSED:METRICS
  OWNS: experiments/blackbox_goal_organism/test_service.js,experiments/blackbox_goal_organism/src/routes/metrics.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.359249+00:00 match='PASSED:METRICS'

- [x] G9: Error handling returns proper error responses
  CHECK: node test_service.js ERRORS
  EXPECT: PASSED:ERRORS
  OWNS: experiments/blackbox_goal_organism/test_service.js,experiments/blackbox_goal_organism/src/routes/index.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.411955+00:00 match='PASSED:ERRORS'

- [x] G10: Full test suite passes
  CHECK: node test_service.js
  EXPECT: PASSED:HEALTH
  OWNS: experiments/blackbox_goal_organism/test_service.js
  EVIDENCE: exit_code=0 timestamp=2026-09-13T13:12:41.475643+00:00 match='PASSED:HEALTH'
