# Acceptance Gates: DAFG Framework

- [x] G1: Offline test suite passes 100%
  CHECK: uv run pytest -q
  EXPECT: 159 passed
  EVIDENCE: exit_code=0 timestamp=2026-09-11T15:10:59.309914+00:00 match='159 passed'

- [x] G2: Gate ledger linting reports clean
  CHECK: uv run gates --lint GATES.md
  EXPECT: Ledger lint passed: 0 issues found
  CWD: .
  EVIDENCE: exit_code=0 timestamp=2026-09-11T15:10:59.376704+00:00 match='Ledger lint passed: 0 issues found'

- [x] G3: Security approval boundary safely refuses unapproved checks
  CHECK: uv run python -c "from dafg import Gate, GateEngine, ApprovalStore; store = ApprovalStore(); engine = GateEngine(approval_store=store); res = engine.execute_gate(Gate('G_sec', 'test title', check='echo unsafe', expect='unsafe')); print('SECURITY_STATUS:' + res.status)"
  EXPECT: SECURITY_STATUS:UNAPPROVED
  CWD: .
  EVIDENCE: exit_code=0 timestamp=2026-09-11T15:10:59.439927+00:00 match='SECURITY_STATUS:UNAPPROVED'

- [x] G4: DAFG runtime enforces objective gate verification for node acceptance
  CHECK: uv run python -c "from dafg import DAFG, TaskNode, GateLedger, GateEngine, AgentResponse, NodeStatus; lg = GateLedger.parse('- [ ] G_t: Test\n  CHECK: echo success\n  EXPECT: success\n'); eng = GateEngine(auto_approve=True); graph = DAFG(ledger=lg, engine=eng); n = graph.add_node(TaskNode('T1', 'Work', assigned_gates=['G_t'])); graph.run(); print('NODE_STATUS:' + n.status.value)"
  EXPECT: NODE_STATUS:ACCEPTED
  CWD: .
  EVIDENCE: exit_code=0 timestamp=2026-09-11T15:10:59.509525+00:00 match='NODE_STATUS:ACCEPTED'

- [x] G5: Stop hook blocks completion when pending gates exist
  CHECK: uv run python -c "from dafg import CompletionGuard, GateLedger; lg = GateLedger.parse('- [ ] G_pending: Work\n  CHECK: echo ok\n  EXPECT: ok\n'); guard = CompletionGuard(ledger=lg); d = guard.evaluate(); print('STOP_DECISION:' + d.decision)"
  EXPECT: STOP_DECISION:block
  CWD: .
  EVIDENCE: exit_code=0 timestamp=2026-09-11T15:10:59.575434+00:00 match='STOP_DECISION:block'

- [x] G6: Formal protocol conformance audit passes all 7 pillars
  CHECK: uv run dafg audit
  EXPECT: Overall Result: PASSED
  CWD: .
  EVIDENCE: exit_code=0 timestamp=2026-09-11T15:10:59.635436+00:00 match='Overall Result: PASSED'

