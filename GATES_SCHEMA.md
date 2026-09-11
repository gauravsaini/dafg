# Acceptance Gates: Typed Schemas and Response Validation

- [x] G1: Schema validation passes valid agent responses and rejects invalid ones
  CHECK: uv run python -c 'from dafg.schema import Schema, Field, ValidationError; s = Schema(fields={"name": Field(str, required=True), "score": Field(int, min_value=0, max_value=100)}); v = s.validate({"name": "agent", "score": 95}); assert v["score"] == 95; ok = False; exec("try:\n s.validate({\"name\": \"agent\", \"score\": 150})\nexcept ValidationError:\n ok = True"); assert ok; print("G1_VALIDATION_OK")'
  EXPECT: G1_VALIDATION_OK
  OWNS: src/dafg/schema.py, tests/test_schema.py
  EVIDENCE: exit_code=0 timestamp=2026-09-10T15:50:17.511654+00:00 match='G1_VALIDATION_OK'

- [x] G2: Schema validation automatically repairs and extracts JSON from noisy outputs and markdown fences
  CHECK: uv run python -c 'from dafg.schema import parse_json_response; noisy = """Output:\n```json\n{\n  "output": "success",\n  "status": "COMPLETED",\n}\n```\nDone."""; data = parse_json_response(noisy); assert data["output"] == "success" and data["status"] == "COMPLETED"; print("G2_REPAIR_OK")'
  EXPECT: G2_REPAIR_OK
  OWNS: src/dafg/schema.py, tests/test_schema.py
  EVIDENCE: exit_code=0 timestamp=2026-09-10T15:50:17.572250+00:00 match='G2_REPAIR_OK'

- [x] G3: New test suite for schema validation passes in pytest
  CHECK: uv run pytest tests/test_schema.py -q
  EXPECT: 20 passed
  OWNS: src/dafg/schema.py, tests/test_schema.py
  EVIDENCE: exit_code=0 timestamp=2026-09-10T15:50:17.768326+00:00 match='20 passed'
