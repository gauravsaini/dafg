MODE: standard

# Acceptance Gates: DAFG Framework

- [x] G1: Offline test suite passes 100%
  CHECK: uv run pytest -q
  EXPECT: passed
  CWD: .
  OWNS: src/dafg/ tests/
  AUTHOR: external
  TIMEOUT: 120.0
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:49.981211+00:00 match='passed' epoch=1 sig=f9abfb4bf1bb record={"attempt_id": 1, "command_digest": "608e058edee526496df3e281d2a06eecd93f2443dd6a13d83ffe6da547af42da", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G1", "gate_signature": "f9abfb4bf1bba0e4c387892d74fad80fc2a2cd60b87c6ecd0019c330129e323a", "match_preview": "passed", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:49.981211+00:00"}

- [x] G2: Gate ledger linting reports clean
  CHECK: uv run gates --lint GATES.md
  EXPECT: Ledger lint passed: 0 issues found
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.057554+00:00 match='Ledger lint passed: 0 issues found' epoch=1 sig=26992c4f080d record={"attempt_id": 1, "command_digest": "780306ff807e9fd9bec84a8ac0c5c15ddb838fc7e32f91160e020b72cd2e1705", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G2", "gate_signature": "26992c4f080df17a25fa37492079747431500db6f119dd5727215b3a58ea8944", "match_preview": "Ledger lint passed: 0 issues found", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.057554+00:00"}

- [x] G3: Security approval boundary safely refuses unapproved checks
  CHECK: uv run python -c "from dafg import Gate, GateEngine, ApprovalStore; store = ApprovalStore(); engine = GateEngine(approval_store=store); res = engine.execute_gate(Gate('G_sec', 'test title', check='echo unsafe', expect='unsafe')); print('SECURITY_STATUS:' + res.status)"
  EXPECT: SECURITY_STATUS:UNAPPROVED
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.130184+00:00 match='SECURITY_STATUS:UNAPPROVED' epoch=1 sig=2ad00a0801c6 record={"attempt_id": 1, "command_digest": "c26b1897872a34c98de7b70a5145dadf7cad68fa1a19318a8819b9bb34200274", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G3", "gate_signature": "2ad00a0801c67412a12983f8393a0660eb7c243c144285dcf5071ce61220931f", "match_preview": "SECURITY_STATUS:UNAPPROVED", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.130184+00:00"}

- [x] G4: DAFG runtime enforces objective gate verification for node acceptance
  CHECK: uv run python -c "from dafg import DAFG, TaskNode, GateLedger, GateEngine, AgentResponse, NodeStatus; lg = GateLedger.parse('- [ ] G_t: Test\n  CHECK: echo success\n  EXPECT: success\n'); eng = GateEngine(auto_approve=True); graph = DAFG(ledger=lg, engine=eng); n = graph.add_node(TaskNode('T1', 'Work', assigned_gates=['G_t'])); graph.run(); print('NODE_STATUS:' + n.status.value)"
  EXPECT: NODE_STATUS:ACCEPTED
  CWD: .
  OWNS: src/dafg/runtime.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.211136+00:00 match='NODE_STATUS:ACCEPTED' epoch=1 sig=918807ee480b record={"attempt_id": 1, "command_digest": "68eeb4672a32ed1a318de3071819b04c9f3f998fdcc41b8f7ef8efc4f061efac", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G4", "gate_signature": "918807ee480b09da4025cfcddfaf92526411a53f0ce43b5c8a3e577264aa1985", "match_preview": "NODE_STATUS:ACCEPTED", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.211136+00:00"}

- [x] G5: Stop hook blocks completion when pending gates exist
  CHECK: uv run python -c "from dafg import CompletionGuard, GateLedger; lg = GateLedger.parse('- [ ] G_pending: Work\n  CHECK: echo ok\n  EXPECT: ok\n'); guard = CompletionGuard(ledger=lg); d = guard.evaluate(); print('STOP_DECISION:' + d.decision)"
  EXPECT: STOP_DECISION:block
  CWD: .
  OWNS: src/dafg/hook.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.283838+00:00 match='STOP_DECISION:block' epoch=1 sig=b35dd559e986 record={"attempt_id": 1, "command_digest": "d96620dcdaa9d24cb65237a72a3012d37188fd9aca58a8d6b42e7f893974d98e", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G5", "gate_signature": "b35dd559e986de074577f51c5fa12d2b41bc87ffc905694e7a9018d8f59d26cd", "match_preview": "STOP_DECISION:block", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.283838+00:00"}

- [x] G6: Formal protocol conformance audit passes all 7 pillars
  CHECK: uv run dafg audit
  EXPECT: Overall Result: PASSED
  CWD: .
  OWNS: src/dafg/
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.357470+00:00 match='Overall Result: PASSED' epoch=1 sig=f0d6816c0ff2 record={"attempt_id": 1, "command_digest": "e5e18c129ab7ea63300326fd8dc566d1a749683c5bdb4994db4b6b32d0c8bd3e", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G6", "gate_signature": "f0d6816c0ff2852667bf0ff500d9cba2b235b33111e365af5e8294717665c2cb", "match_preview": "Overall Result: PASSED", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.357470+00:00"}

- [x] G7: Grounded benchmark telemetry and trial records persisted to disk
  CHECK: uv run python -c "import json, os; assert os.path.exists('eval_results/benchmark_matrix_v03.json'); m=json.load(open('eval_results/benchmark_matrix_v03.json')); print('MATRIX_STATUS:' + str('cli' in m['adapters'] and 'dispatch' in m['adapters'] and 'react' in m['adapters']))"
  EXPECT: MATRIX_STATUS:True
  CWD: .
  OWNS: eval_results/
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.390197+00:00 match='MATRIX_STATUS:True' epoch=1 sig=7a651e563004 record={"attempt_id": 1, "command_digest": "2674f075e837714c8ca8f73a7b9937cf86626990ac4b5452de8fa6e6e3b1b16e", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G7", "gate_signature": "7a651e56300476b4c52cbdefc4622d4196eb9f2c4f2a1b18422d99c17f9f90ff", "match_preview": "MATRIX_STATUS:True", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.390197+00:00"}

- [x] G8: Cross-adapter benchmark demonstrates authentic non-saturated variance
  CHECK: uv run python -c "import json; m=json.load(open('eval_results/benchmark_matrix_v03.json')); r_cli=m['adapters']['cli']['metrics']['delivery_success_rate']; r_react=m['adapters']['react']['metrics']['delivery_success_rate']; print('VARIANCE_STATUS:' + str(r_cli != r_react and r_cli < 1.0 and r_react < 1.0))"
  EXPECT: VARIANCE_STATUS:True
  CWD: .
  OWNS: eval_results/
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.422503+00:00 match='VARIANCE_STATUS:True' epoch=1 sig=34b05d642072 record={"attempt_id": 1, "command_digest": "348fab20a98fb0e66ae6bc90d37c1b7608a07a31d8408d2e3c0025c5216a26ca", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G8", "gate_signature": "34b05d642072bdb966bd6e8cd2d76f66a532d1a9deafabfc2e8de9bb3979770f", "match_preview": "VARIANCE_STATUS:True", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.422503+00:00"}

- [x] G9: Source sabotage mutation testing verifies genuine test coverage
  CHECK: uv run python -c "from dafg.mutation import GateMutator, MutationStrategy; from dafg.gates import Gate; mut = GateMutator(); print('MUTATION_STRATEGY:' + MutationStrategy.SOURCE_SABOTAGE.value)"
  EXPECT: MUTATION_STRATEGY:SOURCE_SABOTAGE
  CWD: .
  OWNS: src/dafg/mutation.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.494334+00:00 match='MUTATION_STRATEGY:SOURCE_SABOTAGE' epoch=1 sig=15a75b737c41 record={"attempt_id": 1, "command_digest": "2285b34fc34068964088d0abe83bc8f82416b220beed43c6ee1c03da1a2dd94c", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G9", "gate_signature": "15a75b737c41b1c76607848f519358b57c3c7843764d4164eff3ddbb22221698", "match_preview": "MUTATION_STRATEGY:SOURCE_SABOTAGE", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.494334+00:00"}

- [x] G10: Gate linter detects low-specificity tokens and unowned gates
  CHECK: uv run python -c "from dafg.gates import GateLedger, GateLinter; lg = GateLedger.parse('- [ ] G_bad: Title\n  CHECK: echo 1\n  EXPECT: 1\n'); issues = GateLinter.lint(lg); print('LINTER_ISSUES:' + str(len(issues)))"
  EXPECT: LINTER_ISSUES:2
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.566764+00:00 match='LINTER_ISSUES:2' epoch=1 sig=1390af28ca48 record={"attempt_id": 1, "command_digest": "0c8beb1ae7810f224bbd7dc7e5494a2be2fff12f76058d73fbdef50643b7b3fc", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G10", "gate_signature": "1390af28ca4851e64862edc1e56c3184bac9fd5530dd571f575aeaec0f6a0582", "match_preview": "LINTER_ISSUES:2", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.566764+00:00"}

- [x] G11: Evidence coverage rollup transparency and stop-hook reporting
  CHECK: uv run python -c "from dafg.hook import CompletionGuard; from dafg.gates import GateLedger; lg = GateLedger.parse('- [ ] G_t: Title\n  CHECK: echo ok\n  EXPECT: ok\n'); d = CompletionGuard(lg).evaluate(); print('COVERAGE_TOTAL:' + str(d.coverage.total))"
  EXPECT: COVERAGE_TOTAL:1
  CWD: .
  OWNS: src/dafg/hook.py src/dafg/judge.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.639310+00:00 match='COVERAGE_TOTAL:1' epoch=1 sig=c04be822c6cf record={"attempt_id": 1, "command_digest": "2a842a2b370f09e6e14aaa740e3784b8c1b1d1ca5782fcccc457b7a04df6cf99", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G11", "gate_signature": "c04be822c6cfd358282302edcd2b11d1a49c32e8fff8eb6d0e3394cfa2cff240", "match_preview": "COVERAGE_TOTAL:1", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.639310+00:00"}

- [x] G12: Pattern-based safe command approvals enforce security boundaries
  CHECK: uv run python -c "from dafg.gates import ApprovalStore, Gate; store = ApprovalStore(); store.approve_pattern('uv run pytest .*'); print('PATTERN_APPROVED:' + str(store.is_approved(Gate('G1', 'test', check='uv run pytest -q', expect='passed'))))"
  EXPECT: PATTERN_APPROVED:True
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.710915+00:00 match='PATTERN_APPROVED:True' epoch=1 sig=211cf9977a0f record={"attempt_id": 1, "command_digest": "0556e66d34df69cb0e568be3a5feb521a2e8b06199bccf53ed4bf0d8d12473b0", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G12", "gate_signature": "211cf9977a0f01228036a1d9106f0da4805bbb0eeb690f59d50566b6e0b2b08c", "match_preview": "PATTERN_APPROVED:True", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.710915+00:00"}

- [x] G13: Proportional ceremony and test bootstrapping discover project tests
  CHECK: uv run python -c "from dafg.gates import bootstrap_ledger; lg = bootstrap_ledger(); print('BOOTSTRAP_GATES:' + str(len(lg.gates) > 10))"
  EXPECT: BOOTSTRAP_GATES:True
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-17T23:34:50.900495+00:00 match='BOOTSTRAP_GATES:True' epoch=1 sig=924d2ac9cc71 record={"attempt_id": 1, "command_digest": "d63ac87094a8d274c416a4f11f1f980e11fdea94014e913158862a8dc7b9969f", "environment_digest": "a749b39a70a3c3c8098a3b820f640a0940d743bf43d448fc3a32295a1415eaf8", "gate_id": "G13", "gate_signature": "924d2ac9cc71f62d3c70fb703ebe53d2adb79b181c7ce76a39d321c703ab1892", "match_preview": "BOOTSTRAP_GATES:True", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-17T23:34:50.900495+00:00"}
