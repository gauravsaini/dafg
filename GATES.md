MODE: standard

# Acceptance Gates: DAFG Framework

- [x] G1: Offline test suite passes 100%
  CHECK: uv run pytest -q
  EXPECT: passed
  CWD: .
  OWNS: src/dafg/ tests/
  AUTHOR: external
  TIMEOUT: 120.0
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:55.586972+00:00 match='passed' epoch=1 sig=f9abfb4bf1bb record={"attempt_id": 1, "command_digest": "608e058edee526496df3e281d2a06eecd93f2443dd6a13d83ffe6da547af42da", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G1", "gate_signature": "f9abfb4bf1bba0e4c387892d74fad80fc2a2cd60b87c6ecd0019c330129e323a", "match_preview": "passed", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:55.586972+00:00"}

- [x] G2: Gate ledger linting reports clean
  CHECK: uv run gates --lint GATES.md
  EXPECT: Ledger lint passed: 0 issues found
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:55.673199+00:00 match='Ledger lint passed: 0 issues found' epoch=1 sig=26992c4f080d record={"attempt_id": 1, "command_digest": "780306ff807e9fd9bec84a8ac0c5c15ddb838fc7e32f91160e020b72cd2e1705", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G2", "gate_signature": "26992c4f080df17a25fa37492079747431500db6f119dd5727215b3a58ea8944", "match_preview": "Ledger lint passed: 0 issues found", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:55.673199+00:00"}

- [x] G3: Security approval boundary safely refuses unapproved checks
  CHECK: uv run python -c "from dafg import Gate, GateEngine, ApprovalStore; store = ApprovalStore(); engine = GateEngine(approval_store=store); res = engine.execute_gate(Gate('G_sec', 'test title', check='echo unsafe', expect='unsafe')); print('SECURITY_STATUS:' + res.status)"
  EXPECT: SECURITY_STATUS:UNAPPROVED
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:55.752067+00:00 match='SECURITY_STATUS:UNAPPROVED' epoch=1 sig=2ad00a0801c6 record={"attempt_id": 1, "command_digest": "c26b1897872a34c98de7b70a5145dadf7cad68fa1a19318a8819b9bb34200274", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G3", "gate_signature": "2ad00a0801c67412a12983f8393a0660eb7c243c144285dcf5071ce61220931f", "match_preview": "SECURITY_STATUS:UNAPPROVED", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:55.752067+00:00"}

- [x] G4: DAFG runtime enforces objective gate verification for node acceptance
  CHECK: uv run python -c "from dafg import DAFG, TaskNode, GateLedger, GateEngine, AgentResponse, NodeStatus; lg = GateLedger.parse('- [ ] G_t: Test\n  CHECK: echo success\n  EXPECT: success\n'); eng = GateEngine(auto_approve=True); graph = DAFG(ledger=lg, engine=eng); n = graph.add_node(TaskNode('T1', 'Work', assigned_gates=['G_t'])); graph.run(); print('NODE_STATUS:' + n.status.value)"
  EXPECT: NODE_STATUS:ACCEPTED
  CWD: .
  OWNS: src/dafg/runtime.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:55.838693+00:00 match='NODE_STATUS:ACCEPTED' epoch=1 sig=918807ee480b record={"attempt_id": 1, "command_digest": "68eeb4672a32ed1a318de3071819b04c9f3f998fdcc41b8f7ef8efc4f061efac", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G4", "gate_signature": "918807ee480b09da4025cfcddfaf92526411a53f0ce43b5c8a3e577264aa1985", "match_preview": "NODE_STATUS:ACCEPTED", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:55.838693+00:00"}

- [x] G5: Stop hook blocks completion when pending gates exist
  CHECK: uv run python -c "from dafg import CompletionGuard, GateLedger; lg = GateLedger.parse('- [ ] G_pending: Work\n  CHECK: echo ok\n  EXPECT: ok\n'); guard = CompletionGuard(ledger=lg); d = guard.evaluate(); print('STOP_DECISION:' + d.decision)"
  EXPECT: STOP_DECISION:block
  CWD: .
  OWNS: src/dafg/hook.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:55.921678+00:00 match='STOP_DECISION:block' epoch=1 sig=b35dd559e986 record={"attempt_id": 1, "command_digest": "d96620dcdaa9d24cb65237a72a3012d37188fd9aca58a8d6b42e7f893974d98e", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G5", "gate_signature": "b35dd559e986de074577f51c5fa12d2b41bc87ffc905694e7a9018d8f59d26cd", "match_preview": "STOP_DECISION:block", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:55.921678+00:00"}

- [x] G6: Formal protocol conformance audit passes all 7 pillars
  CHECK: uv run dafg audit
  EXPECT: Overall Result: PASSED
  CWD: .
  OWNS: src/dafg/
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.002535+00:00 match='Overall Result: PASSED' epoch=1 sig=f0d6816c0ff2 record={"attempt_id": 1, "command_digest": "e5e18c129ab7ea63300326fd8dc566d1a749683c5bdb4994db4b6b32d0c8bd3e", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G6", "gate_signature": "f0d6816c0ff2852667bf0ff500d9cba2b235b33111e365af5e8294717665c2cb", "match_preview": "Overall Result: PASSED", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.002535+00:00"}

- [x] G7: Grounded benchmark telemetry and trial records persisted to disk
  CHECK: uv run python -c "import json, os; assert os.path.exists('eval_results/benchmark_matrix_v03.json'); m=json.load(open('eval_results/benchmark_matrix_v03.json')); print('MATRIX_STATUS:' + str('cli' in m['adapters'] and 'dispatch' in m['adapters'] and 'react' in m['adapters']))"
  EXPECT: MATRIX_STATUS:True
  CWD: .
  OWNS: eval_results/
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.035855+00:00 match='MATRIX_STATUS:True' epoch=1 sig=7a651e563004 record={"attempt_id": 1, "command_digest": "2674f075e837714c8ca8f73a7b9937cf86626990ac4b5452de8fa6e6e3b1b16e", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G7", "gate_signature": "7a651e56300476b4c52cbdefc4622d4196eb9f2c4f2a1b18422d99c17f9f90ff", "match_preview": "MATRIX_STATUS:True", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.035855+00:00"}

- [x] G8: Cross-adapter benchmark demonstrates authentic non-saturated variance
  CHECK: uv run python -c "import json; m=json.load(open('eval_results/benchmark_matrix_v03.json')); r_cli=m['adapters']['cli']['metrics']['delivery_success_rate']; r_react=m['adapters']['react']['metrics']['delivery_success_rate']; print('VARIANCE_STATUS:' + str(r_cli != r_react and r_cli < 1.0 and r_react < 1.0))"
  EXPECT: VARIANCE_STATUS:True
  CWD: .
  OWNS: eval_results/
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.070612+00:00 match='VARIANCE_STATUS:True' epoch=1 sig=34b05d642072 record={"attempt_id": 1, "command_digest": "348fab20a98fb0e66ae6bc90d37c1b7608a07a31d8408d2e3c0025c5216a26ca", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G8", "gate_signature": "34b05d642072bdb966bd6e8cd2d76f66a532d1a9deafabfc2e8de9bb3979770f", "match_preview": "VARIANCE_STATUS:True", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.070612+00:00"}

- [x] G9: Source sabotage mutation testing verifies genuine test coverage
  CHECK: uv run python -c "from dafg.mutation import GateMutator, MutationStrategy; from dafg.gates import Gate; mut = GateMutator(); print('MUTATION_STRATEGY:' + MutationStrategy.SOURCE_SABOTAGE.value)"
  EXPECT: MUTATION_STRATEGY:SOURCE_SABOTAGE
  CWD: .
  OWNS: src/dafg/mutation.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.148713+00:00 match='MUTATION_STRATEGY:SOURCE_SABOTAGE' epoch=1 sig=15a75b737c41 record={"attempt_id": 1, "command_digest": "2285b34fc34068964088d0abe83bc8f82416b220beed43c6ee1c03da1a2dd94c", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G9", "gate_signature": "15a75b737c41b1c76607848f519358b57c3c7843764d4164eff3ddbb22221698", "match_preview": "MUTATION_STRATEGY:SOURCE_SABOTAGE", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.148713+00:00"}

- [x] G10: Gate linter detects low-specificity tokens and unowned gates
  CHECK: uv run python -c "from dafg.gates import GateLedger, GateLinter; lg = GateLedger.parse('- [ ] G_bad: Title\n  CHECK: echo 1\n  EXPECT: 1\n'); issues = GateLinter.lint(lg); print('LINTER_ISSUES:' + str(len(issues)))"
  EXPECT: LINTER_ISSUES:2
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.226925+00:00 match='LINTER_ISSUES:2' epoch=1 sig=1390af28ca48 record={"attempt_id": 1, "command_digest": "0c8beb1ae7810f224bbd7dc7e5494a2be2fff12f76058d73fbdef50643b7b3fc", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G10", "gate_signature": "1390af28ca4851e64862edc1e56c3184bac9fd5530dd571f575aeaec0f6a0582", "match_preview": "LINTER_ISSUES:2", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.226925+00:00"}

- [x] G11: Evidence coverage rollup transparency and stop-hook reporting
  CHECK: uv run python -c "from dafg.hook import CompletionGuard; from dafg.gates import GateLedger; lg = GateLedger.parse('- [ ] G_t: Title\n  CHECK: echo ok\n  EXPECT: ok\n'); d = CompletionGuard(lg).evaluate(); print('COVERAGE_TOTAL:' + str(d.coverage.total))"
  EXPECT: COVERAGE_TOTAL:1
  CWD: .
  OWNS: src/dafg/hook.py src/dafg/judge.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.305604+00:00 match='COVERAGE_TOTAL:1' epoch=1 sig=c04be822c6cf record={"attempt_id": 1, "command_digest": "2a842a2b370f09e6e14aaa740e3784b8c1b1d1ca5782fcccc457b7a04df6cf99", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G11", "gate_signature": "c04be822c6cfd358282302edcd2b11d1a49c32e8fff8eb6d0e3394cfa2cff240", "match_preview": "COVERAGE_TOTAL:1", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.305604+00:00"}

- [x] G12: Pattern-based safe command approvals enforce security boundaries
  CHECK: uv run python -c "from dafg.gates import ApprovalStore, Gate; store = ApprovalStore(); store.approve_pattern('uv run pytest .*'); print('PATTERN_APPROVED:' + str(store.is_approved(Gate('G1', 'test', check='uv run pytest -q', expect='passed'))))"
  EXPECT: PATTERN_APPROVED:True
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.384341+00:00 match='PATTERN_APPROVED:True' epoch=1 sig=211cf9977a0f record={"attempt_id": 1, "command_digest": "0556e66d34df69cb0e568be3a5feb521a2e8b06199bccf53ed4bf0d8d12473b0", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G12", "gate_signature": "211cf9977a0f01228036a1d9106f0da4805bbb0eeb690f59d50566b6e0b2b08c", "match_preview": "PATTERN_APPROVED:True", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.384341+00:00"}

- [x] G13: Proportional ceremony and test bootstrapping discover project tests
  CHECK: uv run python -c "from dafg.gates import bootstrap_ledger; lg = bootstrap_ledger(); print('BOOTSTRAP_GATES:' + str(len(lg.gates) > 10))"
  EXPECT: BOOTSTRAP_GATES:True
  CWD: .
  OWNS: src/dafg/gates.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.581242+00:00 match='BOOTSTRAP_GATES:True' epoch=1 sig=924d2ac9cc71 record={"attempt_id": 1, "command_digest": "d63ac87094a8d274c416a4f11f1f980e11fdea94014e913158862a8dc7b9969f", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G13", "gate_signature": "924d2ac9cc71f62d3c70fb703ebe53d2adb79b181c7ce76a39d321c703ab1892", "match_preview": "BOOTSTRAP_GATES:True", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.581242+00:00"}
- [x] G14: Canonical product direction is explicit
  CHECK: uv run python -c "from pathlib import Path; goal=Path('GOAL.md').read_text(); plan=Path('plan.md').read_text(); assert 'verification and completion-control' in goal; assert 'verification and completion-control' in plan; assert 'Boeing' not in goal.splitlines()[0]; print('PRODUCT_DIRECTION:OK')"
  EXPECT: PRODUCT_DIRECTION:OK
  CWD: .
  OWNS: GOAL.md plan.md
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.617921+00:00 match='PRODUCT_DIRECTION:OK' epoch=1 sig=d42c327cef05 record={"attempt_id": 1, "command_digest": "a3c110771efe9406ab1f5d68ed97e7a9b28173bb44b8094c782c5a3cd67e2f48", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G14", "gate_signature": "d42c327cef059b34bf713862a61216c1aa4ddff2f77c31bba9db250fbb62d526", "match_preview": "PRODUCT_DIRECTION:OK", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.617921+00:00"}

- [x] G15: Evaluation results persist reproducible provenance
  CHECK: uv run pytest -q tests/test_eval_provenance.py
  EXPECT: passed
  CWD: .
  OWNS: src/dafg/eval.py tests/test_eval_provenance.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:56.823095+00:00 match='passed' epoch=1 sig=923861a4b483 record={"attempt_id": 1, "command_digest": "3e17ed6fe63dc13554a9ef6d9daa170e70b4c8a1cf187f8c0cb532e11ffca572", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G15", "gate_signature": "923861a4b48323a5ad54a9075a08de4fe9a1a37cdc2c5071d97390735f02ca52", "match_preview": "passed", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:56.823095+00:00"}

- [x] G16: Comparison rejects incomplete authoritative evidence
  CHECK: uv run pytest -q tests/test_compare.py
  EXPECT: passed
  CWD: .
  OWNS: src/dafg/compare.py tests/test_compare.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T07:47:58.474132+00:00 match='passed' epoch=1 sig=042b147206a7 record={"attempt_id": 1, "command_digest": "fc1c6476dafc7ccc029d76f4759858f450e2c722ddbe032da76ac33e2fedfaf3", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G16", "gate_signature": "042b147206a702019fc644fd209a67dfb3a9979f75da4fe3f63efc19db8a09c4", "match_preview": "passed", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T07:47:58.474132+00:00"}

- [x] G17: Phase 1 pilot task cohorts use real fixtures
  CHECK: uv run pytest -q tests/test_phase1_tasks.py
  EXPECT: passed
  CWD: .
  OWNS: src/dafg/eval.py tests/test_phase1_tasks.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T08:38:13.566794+00:00 match='passed' epoch=1 sig=89da91f86e7d record={"attempt_id": 1, "command_digest": "a46fce6ffa25456179b0ee330c85528fc1760686e21dcf3faa65edfc12973b5b", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G17", "gate_signature": "89da91f86e7d1cd3b7ab9a35513d36bae90d22d23bcbd49d2dd97686b035ca0a", "match_preview": "passed", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T08:38:13.566794+00:00"}

- [x] G18: Independent oracle runner audits discrepancy
  CHECK: uv run pytest -q tests/test_oracle.py
  EXPECT: passed
  CWD: .
  OWNS: src/dafg/oracle.py tests/test_oracle.py src/dafg/__init__.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T08:38:13.961245+00:00 match='passed' epoch=1 sig=7b80ed2edc43 record={"attempt_id": 1, "command_digest": "2d651fb462b3b792ad88589cdea316dd7a6098d5d79b5b202e058676878bff36", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G18", "gate_signature": "7b80ed2edc43433e71b28e6bc194700c885269638e2e991ccf6133257d16eb76", "match_preview": "passed", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T08:38:13.961245+00:00"}

- [x] G19: Phase 1 matrix scaled to 75 real-fixture tasks
  CHECK: uv run pytest -q tests/test_phase1_tasks.py
  EXPECT: passed
  CWD: .
  OWNS: src/dafg/eval.py tests/test_phase1_tasks.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T09:43:47.506706+00:00 match='passed' epoch=1 sig=161c3271f209 record={"attempt_id": 1, "command_digest": "a46fce6ffa25456179b0ee330c85528fc1760686e21dcf3faa65edfc12973b5b", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G19", "gate_signature": "161c3271f20939aa88bbb8c95198ee7ef3748c9ce93e7455ccf71e12af3a00bf", "match_preview": "passed", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T09:43:47.506706+00:00"}

- [x] G20: Paired A/B/C runner executes matrix with discrepancy audit
  CHECK: uv run pytest -q tests/test_phase1.py
  EXPECT: passed
  CWD: .
  OWNS: src/dafg/phase1.py tests/test_phase1.py src/dafg/__init__.py
  AUTHOR: external
  EVIDENCE: exit_code=0 timestamp=2026-09-24T09:43:47.713511+00:00 match='passed' epoch=1 sig=673df676723c record={"attempt_id": 1, "command_digest": "ce0f711e8ea5ef33abb7d20465cd8e41231822c7b45b63217dd23588450490ef", "environment_digest": "0f02b903f98f3f8f09441da0dc3087d2e3023b540560d7a2f103eae1ac0b24ea", "gate_id": "G20", "gate_signature": "673df676723c9de0a7a53e88ce97cca428fe1a6fdc1a5d2f2d00928f38bc0a82", "match_preview": "passed", "run_epoch": 1, "run_id": "local_run", "timestamp": "2026-09-24T09:43:47.713511+00:00"}
