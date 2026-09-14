# Gates

- [x] G1: Legitimate check
  CHECK: node test_system.js CORE
  EXPECT: OK CORE
  OWNS: test_system.js
  EVIDENCE: exit_code=0 timestamp=2026-09-14T11:10:00.456586+00:00 match='OK CORE' epoch=1 sig=85272591b00e record={"command_digest": "f498596922da18b0ad1f28ecfd145970a3ca6972728200dbb727517ccc49b254", "environment_digest": "77bf2514060aa5ddb78074bb1b4106909ba32ec746ec7d82bed0c2fa310109db", "gate_id": "G1", "gate_signature": "85272591b00ef14abdcbac7b3390f681777474dfe4800864c23bcaab0f11fa67", "match_preview": "OK CORE", "node_id": "task_G1", "run_epoch": 1, "run_id": "run_1789384200410_77272", "timestamp": "2026-09-14T11:10:00.456586+00:00"}
- [ ] G2: Malicious path traversal
  CHECK: node test_system.js ../../../etc/passwd
  EXPECT: root
  OWNS: test_system.js
- [ ] G3: Malicious code injection
  CHECK: node -e "require('child_process').execSync('id')"
  EXPECT: uid
  OWNS: test_system.js
