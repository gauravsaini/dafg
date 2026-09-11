"""Tests for Typed Schemas and Response Validation in DAFG."""

from __future__ import annotations

import json
import pytest
from typing import Dict, List, Optional, Union

from dafg import (
    AgentResponse,
    AgentResponseSchema,
    Field,
    ResponseValidator,
    Schema,
    ValidationError,
    extract_json,
    parse_json_response,
    repair_json,
)


class TestFieldValidation:
    def test_primitive_type_validation(self):
        f_str = Field(str)
        assert f_str.validate("hello") == "hello"
        with pytest.raises(ValidationError):
            f_str.validate(123)

        f_int = Field(int)
        assert f_int.validate(42) == 42
        # bool should not pass as int
        with pytest.raises(ValidationError):
            f_int.validate(True)

        f_bool = Field(bool)
        assert f_bool.validate(True) is True
        assert f_bool.validate(False) is False
        with pytest.raises(ValidationError):
            f_bool.validate(1)

    def test_choices(self):
        f = Field(str, choices=["LOW", "MEDIUM", "HIGH"])
        assert f.validate("LOW") == "LOW"
        with pytest.raises(ValidationError) as exc:
            f.validate("CRITICAL")
        assert "not in allowed choices" in str(exc.value)

    def test_numeric_bounds(self):
        f = Field(int, min_value=1, max_value=10)
        assert f.validate(1) == 1
        assert f.validate(10) == 10
        with pytest.raises(ValidationError):
            f.validate(0)
        with pytest.raises(ValidationError):
            f.validate(11)

    def test_string_length_and_pattern(self):
        f = Field(str, min_length=3, max_length=6, pattern=r"^[a-z]+$")
        assert f.validate("abc") == "abc"
        assert f.validate("abcdef") == "abcdef"

        with pytest.raises(ValidationError):
            f.validate("ab")  # too short
        with pytest.raises(ValidationError):
            f.validate("abcdefg")  # too long
        with pytest.raises(ValidationError):
            f.validate("abc12")  # pattern mismatch

    def test_custom_validator(self):
        f = Field(int, validator=lambda x: x % 2 == 0)
        assert f.validate(4) == 4
        with pytest.raises(ValidationError):
            f.validate(5)

    def test_list_and_dict_types(self):
        f_list = Field(List[str])
        assert f_list.validate(["a", "b"]) == ["a", "b"]
        with pytest.raises(ValidationError):
            f_list.validate(["a", 123])

        f_dict = Field(Dict[str, int])
        assert f_dict.validate({"a": 1, "b": 2}) == {"a": 1, "b": 2}
        with pytest.raises(ValidationError):
            f_dict.validate({"a": "not_an_int"})


class TestSchemaValidation:
    def test_declarative_schema(self):
        class UserSchema(Schema):
            name: str = Field(str, min_length=2)
            age: int = Field(int, min_value=0, max_value=150)
            email: Optional[str] = Field(str, required=False, default=None)
            role: str = Field(str, default="user", choices=["admin", "user", "guest"])

        schema = UserSchema()
        valid_data = {"name": "Alice", "age": 30}
        res = schema.validate(valid_data)
        assert res["name"] == "Alice"
        assert res["age"] == 30
        assert res["email"] is None
        assert res["role"] == "user"

        # Invalid data
        with pytest.raises(ValidationError) as exc:
            schema.validate({"name": "A", "age": 200, "role": "superuser"})
        assert "Schema validation failed" in str(exc.value)

    def test_programmatic_schema(self):
        s = Schema(fields={
            "task": Field(str, required=True),
            "priority": Field(int, default=1, min_value=1, max_value=5),
        })
        res = s.validate({"task": "Write docs"})
        assert res["task"] == "Write docs"
        assert res["priority"] == 1

        assert s.is_valid({"task": "Write docs"}) is True
        assert s.is_valid({"task": "Write docs", "priority": 10}) is False

    def test_nested_schema(self):
        class Location(Schema):
            city: str = Field(str, required=True)
            country: str = Field(str, required=True)

        class Person(Schema):
            name: str = Field(str, required=True)
            location: Location = Field(Location, required=True)

        schema = Person()
        valid = {"name": "Bob", "location": {"city": "Sydney", "country": "Australia"}}
        assert schema.validate(valid)["location"]["city"] == "Sydney"

        with pytest.raises(ValidationError):
            schema.validate({"name": "Bob", "location": {"city": "Sydney"}})  # missing country


class TestJsonExtractionAndRepair:
    def test_extract_json_from_markdown_fence(self):
        text = """Here is the result:
```json
{
  "output": "all good",
  "status": "COMPLETED"
}
```
Let me know if you need more."""
        extracted = extract_json(text)
        data = json.loads(extracted)
        assert data["output"] == "all good"
        assert data["status"] == "COMPLETED"

    def test_extract_json_fence_without_language_tag(self):
        text = """```
{"status": "READY", "count": 5}
```"""
        extracted = extract_json(text)
        data = json.loads(extracted)
        assert data["count"] == 5

    def test_extract_json_noisy_text_no_fence(self):
        text = 'Preamble: {"output": "hello", "needs": ["T1"]} Postscript.'
        extracted = extract_json(text)
        data = json.loads(extracted)
        assert data["output"] == "hello"
        assert data["needs"] == ["T1"]

    def test_repair_trailing_commas(self):
        bad_json = '{"a": 1, "b": [2, 3,], }'
        repaired = repair_json(bad_json)
        data = json.loads(repaired)
        assert data == {"a": 1, "b": [2, 3]}

    def test_repair_python_constants(self):
        bad_json = '{"active": True, "archived": False, "note": None}'
        repaired = repair_json(bad_json)
        data = json.loads(repaired)
        assert data == {"active": True, "archived": False, "note": None}

    def test_repair_single_quotes(self):
        bad_json = "{'title': 'test', 'status': 'COMPLETED'}"
        repaired = repair_json(bad_json)
        data = json.loads(repaired)
        assert data["title"] == "test"

    def test_parse_json_response_comprehensive(self):
        noisy_output = """Sure! Here is the response:
```json
{
  "output": "Unit tests complete",
  "status": "COMPLETED",
  "needs": [],
  "files_modified": ["src/dafg/schema.py",],
  "metadata": {"ok": True,},
}
```
Hope this helps!"""
        res = parse_json_response(noisy_output)
        assert res["status"] == "COMPLETED"
        assert res["files_modified"] == ["src/dafg/schema.py"]
        assert res["metadata"]["ok"] is True


class TestResponseValidator:
    def test_validate_raw_agent_response(self):
        validator = ResponseValidator()
        raw_llm = '```json\n{"output": "task done", "status": "COMPLETED", "files_modified": ["file.txt"]}\n```'
        validated = validator.validate(raw_llm)
        assert validated["output"] == "task done"
        assert validated["status"] == "COMPLETED"
        assert validated["files_modified"] == ["file.txt"]

    def test_validate_agent_response_object(self):
        raw_llm = '{"output": "finished", "status": "COMPLETED", "needs": ["T1"]}'
        resp_obj = ResponseValidator.validate_agent_response(raw_llm)
        assert isinstance(resp_obj, AgentResponse)
        assert resp_obj.output == "finished"
        assert resp_obj.status == "COMPLETED"
        assert resp_obj.needs == ["T1"]

    def test_reject_invalid_agent_response(self):
        validator = ResponseValidator()
        with pytest.raises(ValidationError):
            validator.validate('{"status": "UNKNOWN_STATUS"}')

    def test_custom_schema_validation(self):
        class CodeReviewSchema(Schema):
            approved: bool = Field(bool, required=True)
            comments: List[str] = Field(List[str], default_factory=list)
            score: int = Field(int, min_value=0, max_value=10)

        validator = ResponseValidator(schema=CodeReviewSchema)
        output = '```json\n{"approved": true, "comments": ["Great clean code"], "score": 10}\n```'
        validated = validator.validate(output)
        assert validated["approved"] is True
        assert validated["score"] == 10
