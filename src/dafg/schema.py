"""Typed Schemas and Response Validation for DAFG Agents.

Provides structured schema definitions, type validation, automatic JSON extraction,
and repair for LLM/agent responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from enum import Enum
import inspect
import json
from pathlib import Path
import re
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
    get_args,
    get_origin,
)


class ValidationError(Exception):
    """Raised when data fails schema validation."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        errors: Optional[List[str]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.field = field
        self.errors = errors or ([message] if message else [])

    def __str__(self) -> str:
        if self.field:
            return f"Validation error for field '{self.field}': {self.message}"
        if len(self.errors) > 1:
            return f"{self.message}\n  - " + "\n  - ".join(self.errors)
        return self.message


_MISSING = object()


class Field:
    """Defines a field and its validation rules within a Schema."""

    def __init__(
        self,
        field_type: Any = Any,
        *,
        required: Optional[bool] = None,
        default: Any = _MISSING,
        default_factory: Optional[Callable[[], Any]] = None,
        description: str = "",
        choices: Optional[Sequence[Any]] = None,
        min_value: Optional[Union[int, float]] = None,
        max_value: Optional[Union[int, float]] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
        validator: Optional[Callable[[Any], bool]] = None,
    ):
        self.field_type = field_type
        self.default = default
        self.default_factory = default_factory

        # Resolve required vs optional
        if required is not None:
            self.required = required
        elif default is not _MISSING or default_factory is not None:
            self.required = False
        else:
            self.required = True

        self.description = description
        self.choices = list(choices) if choices is not None else None
        self.min_value = min_value
        self.max_value = max_value
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = pattern
        self.validator = validator

        self._compiled_pattern = re.compile(pattern) if pattern else None

    def get_default(self) -> Any:
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is not _MISSING:
            return self.default
        return None

    def validate(self, value: Any, name: str = "") -> Any:
        """Validate a single value against this field's constraints."""
        if value is None:
            if self.required:
                raise ValidationError(f"Field '{name}' is required and cannot be None", field=name)
            return None

        # 1. Type validation
        self._validate_type(value, self.field_type, name)

        # 2. Choices
        if self.choices is not None:
            if value not in self.choices:
                raise ValidationError(
                    f"Field '{name}' value {value!r} not in allowed choices: {self.choices}",
                    field=name,
                )

        # 3. Numeric bounds
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.min_value is not None and value < self.min_value:
                raise ValidationError(
                    f"Field '{name}' value {value} is less than minimum {self.min_value}",
                    field=name,
                )
            if self.max_value is not None and value > self.max_value:
                raise ValidationError(
                    f"Field '{name}' value {value} is greater than maximum {self.max_value}",
                    field=name,
                )

        # 4. Length bounds (str, list, dict, set, tuple)
        if isinstance(value, (str, list, dict, set, tuple)):
            val_len = len(value)
            if self.min_length is not None and val_len < self.min_length:
                raise ValidationError(
                    f"Field '{name}' length {val_len} is less than min_length {self.min_length}",
                    field=name,
                )
            if self.max_length is not None and val_len > self.max_length:
                raise ValidationError(
                    f"Field '{name}' length {val_len} is greater than max_length {self.max_length}",
                    field=name,
                )

        # 5. Regex pattern
        if isinstance(value, str) and self._compiled_pattern:
            if not self._compiled_pattern.search(value):
                raise ValidationError(
                    f"Field '{name}' value {value!r} does not match pattern '{self.pattern}'",
                    field=name,
                )

        # 6. Custom validator
        if self.validator is not None:
            try:
                res = self.validator(value)
                if not res:
                    raise ValidationError(
                        f"Field '{name}' failed custom validation predicate",
                        field=name,
                    )
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError(
                    f"Field '{name}' custom validation error: {e}",
                    field=name,
                )

        return value

    def _validate_type(self, value: Any, expected_type: Any, name: str) -> None:
        if expected_type is Any or expected_type is None:
            return

        origin = get_origin(expected_type)
        args = get_args(expected_type)

        # Union / Optional
        if origin is Union:
            matched = False
            for arg in args:
                if arg is type(None) and value is None:
                    matched = True
                    break
                try:
                    self._validate_type(value, arg, name)
                    matched = True
                    break
                except ValidationError:
                    continue
            if not matched:
                type_names = [getattr(a, "__name__", str(a)) for a in args]
                raise ValidationError(
                    f"Field '{name}' expected one of [{', '.join(type_names)}], got {type(value).__name__}",
                    field=name,
                )
            return

        # List / Sequence
        if origin in (list, Sequence, List):
            if not isinstance(value, list):
                raise ValidationError(
                    f"Field '{name}' expected list, got {type(value).__name__}",
                    field=name,
                )
            if args:
                item_type = args[0]
                for i, item in enumerate(value):
                    self._validate_type(item, item_type, f"{name}[{i}]")
            return

        # Dict / Mapping
        if origin in (dict, Dict):
            if not isinstance(value, dict):
                raise ValidationError(
                    f"Field '{name}' expected dict, got {type(value).__name__}",
                    field=name,
                )
            if len(args) == 2:
                key_type, val_type = args
                for k, v in value.items():
                    self._validate_type(k, key_type, f"{name}.key({k})")
                    self._validate_type(v, val_type, f"{name}[{k}]")
            return

        # Nested Schema
        if isinstance(expected_type, type) and issubclass(expected_type, Schema):
            if isinstance(value, dict):
                schema_inst = expected_type()
                schema_inst.validate(value)
            elif isinstance(value, expected_type):
                pass
            else:
                raise ValidationError(
                    f"Field '{name}' expected schema {expected_type.__name__} or dict, got {type(value).__name__}",
                    field=name,
                )
            return

        # Primitive types
        if isinstance(expected_type, type):
            if expected_type is bool and not isinstance(value, bool):
                raise ValidationError(
                    f"Field '{name}' expected bool, got {type(value).__name__}",
                    field=name,
                )
            if expected_type in (int, float) and isinstance(value, bool):
                raise ValidationError(
                    f"Field '{name}' expected {expected_type.__name__}, got bool",
                    field=name,
                )
            if not isinstance(value, expected_type):
                raise ValidationError(
                    f"Field '{name}' expected {expected_type.__name__}, got {type(value).__name__}",
                    field=name,
                )


class Schema:
    """Base schema class supporting declarative fields, type annotations, and validation."""

    def __init__(self, fields: Optional[Dict[str, Union[Field, Any]]] = None, **kwargs: Any):
        self._fields: Dict[str, Field] = {}
        self._init_fields(fields)
        self._data: Dict[str, Any] = {}

        if kwargs:
            self._data = self.validate(kwargs)

    def _init_fields(self, explicit_fields: Optional[Dict[str, Union[Field, Any]]] = None) -> None:
        cls = self.__class__
        hints = getattr(cls, "__annotations__", {})

        for name, hint in hints.items():
            if name.startswith("_"):
                continue
            val = getattr(cls, name, _MISSING)
            if isinstance(val, Field):
                fld = val
                if fld.field_type is Any:
                    fld.field_type = hint
                self._fields[name] = fld
            elif val is not _MISSING:
                self._fields[name] = Field(field_type=hint, default=val)
            else:
                self._fields[name] = Field(field_type=hint, required=True)

        for name in dir(cls):
            if name.startswith("_") or name in self._fields:
                continue
            val = getattr(cls, name)
            if isinstance(val, Field):
                self._fields[name] = val

        if explicit_fields:
            for name, fld in explicit_fields.items():
                if isinstance(fld, Field):
                    self._fields[name] = fld
                elif isinstance(fld, type):
                    self._fields[name] = Field(field_type=fld, required=True)
                else:
                    self._fields[name] = Field(field_type=type(fld), default=fld)

    @property
    def fields(self) -> Dict[str, Field]:
        return self._fields

    def validate(self, data: Union[Dict[str, Any], Any]) -> Dict[str, Any]:
        """Validate input data against schema fields and return validated dictionary."""
        if not isinstance(data, dict):
            if hasattr(data, "to_dict") and callable(data.to_dict):
                data = data.to_dict()
            elif is_dataclass(data):
                data = inspect.getmembers(data)
                data = {k: v for k, v in data if not k.startswith("_")}
            else:
                raise ValidationError(f"Expected dict-like data for schema validation, got {type(data).__name__}")

        validated: Dict[str, Any] = {}
        errors: List[str] = []

        # Validate defined fields
        for name, fld in self._fields.items():
            if name in data:
                val = data[name]
                try:
                    validated[name] = fld.validate(val, name=name)
                except ValidationError as e:
                    errors.extend(e.errors)
            elif fld.required:
                errors.append(f"Missing required field '{name}'")
            else:
                validated[name] = fld.get_default()

        # Include additional extra fields
        for k, v in data.items():
            if k not in self._fields:
                validated[k] = v

        if errors:
            raise ValidationError(
                f"Schema validation failed ({len(errors)} errors): " + "; ".join(errors),
                errors=errors,
            )

        return validated

    def is_valid(self, data: Any) -> bool:
        """Return True if data passes validation, False otherwise."""
        try:
            self.validate(data)
            return True
        except (ValidationError, Exception):
            return False

    def parse_raw(self, raw_text: str) -> Dict[str, Any]:
        """Extract and repair JSON from raw text, then validate against schema."""
        parsed = parse_json_response(raw_text)
        return self.validate(parsed)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data)

    def __getitem__(self, item: str) -> Any:
        return self._data[item]

    def __contains__(self, item: str) -> bool:
        return item in self._data


# =====================================================================
# JSON Extraction and Repair
# =====================================================================

MARKDOWN_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*([\s\S]*?)\s*```",
    re.IGNORECASE,
)


def extract_json(text: str) -> str:
    """Extract JSON string from markdown code fences or surrounding noisy text."""
    if not text or not text.strip():
        return ""

    stripped = text.strip()

    # 1. Check markdown code fence
    fence_matches = MARKDOWN_JSON_FENCE_RE.findall(stripped)
    if fence_matches:
        for block in fence_matches:
            b_stripped = block.strip()
            if (b_stripped.startswith("{") and b_stripped.endswith("}")) or (
                b_stripped.startswith("[") and b_stripped.endswith("]")
            ):
                return b_stripped
        return fence_matches[0].strip()

    # 2. Extract outermost JSON object { ... } or array [ ... ] with bracket counting
    obj_match = _extract_balanced_brackets(stripped, "{", "}")
    if obj_match:
        return obj_match

    arr_match = _extract_balanced_brackets(stripped, "[", "]")
    if arr_match:
        return arr_match

    return stripped


def _extract_balanced_brackets(text: str, open_ch: str, close_ch: str) -> Optional[str]:
    start = text.find(open_ch)
    if start == -1:
        return None

    count = 0
    in_string = False
    escape = False

    for idx in range(start, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == open_ch:
                count += 1
            elif ch == close_ch:
                count -= 1
                if count == 0:
                    return text[start : idx + 1]
    return None


def repair_json(text: str) -> str:
    """Repair common syntax mistakes in LLM-generated JSON."""
    if not text:
        return text

    repaired = text.strip()

    # 1. Remove trailing commas before } or ]
    repaired = re.sub(r",\s*([\]}])", r"\1", repaired)

    # 2. Normalize Python constants outside strings: True -> true, False -> false, None -> null
    def _normalize_constants(match: re.Match) -> str:
        word = match.group(0)
        if word == "True":
            return "true"
        if word == "False":
            return "false"
        if word == "None":
            return "null"
        return word

    repaired = re.sub(r"\b(True|False|None)\b", _normalize_constants, repaired)

    # 3. Handle single-quoted keys and values if not standard JSON
    try:
        json.loads(repaired)
        return repaired
    except Exception:
        pass

    sq_repaired = re.sub(r"(?<!\\)'", '"', repaired)
    try:
        json.loads(sq_repaired)
        return sq_repaired
    except Exception:
        pass

    return repaired


def parse_json_response(text: str) -> Any:
    """Extract, repair, and parse JSON from noisy or markdown-wrapped LLM text."""
    if not isinstance(text, str):
        if isinstance(text, (dict, list)):
            return text
        raise ValidationError(f"Expected string for JSON parsing, got {type(text).__name__}")

    stripped = text.strip()
    if not stripped:
        raise ValidationError("Empty response text cannot be parsed as JSON")

    # Step 1: Direct JSON parsing
    try:
        return json.loads(stripped)
    except Exception:
        pass

    # Step 2: Extract from markdown or surrounding noise
    extracted = extract_json(stripped)
    try:
        return json.loads(extracted)
    except Exception:
        pass

    # Step 3: Repair syntax flaws
    repaired = repair_json(extracted)
    try:
        return json.loads(repaired)
    except Exception:
        pass

    # Step 4: Try repair on raw stripped text as fallback
    raw_repaired = repair_json(stripped)
    try:
        return json.loads(raw_repaired)
    except Exception as err:
        raise ValidationError(
            f"Could not parse or repair JSON from agent output: {err}\nOutput was: {text[:200]!r}"
        ) from err


# =====================================================================
# Response Validator & Agent Response Schema
# =====================================================================

class InputManifestSchema(Schema):
    """Schema definition for pre-dispatch InputManifest."""
    required_inputs = Field(list, default_factory=list, description="Required input artifacts and versions")
    mandatory_context = Field(list, default_factory=list, description="Mandatory context documents")
    optional_context = Field(list, default_factory=list, description="Optional context documents")
    checks = Field(dict, default_factory=dict, description="Pre-dispatch validation check results")


class InterfaceContractSchema(Schema):
    """Schema definition for versioned InterfaceContract."""
    contract_id = Field(str, required=True, description="Contract identifier")
    version = Field(int, default=1, min_value=1, description="Contract semantic version")
    owner = Field(str, default="", description="Node or role owning this contract")
    input_schema = Field(dict, default_factory=dict, description="Input schema specification")
    output_schema = Field(dict, default_factory=dict, description="Output schema specification")
    invariants = Field(list, default_factory=list, description="Contract invariant assertions")
    error_behavior = Field(dict, default_factory=dict, description="Error status mapping")
    compatibility_mode = Field(str, default="backward_compatible", choices=["backward_compatible", "breaking"])
    consumers = Field(list, default_factory=list, description="List of consuming task IDs")
    metadata = Field(dict, default_factory=dict, description="Arbitrary contract metadata")


class RevisionDirectiveSchema(Schema):
    """Schema definition for diagnostic RevisionDirective."""
    verdict = Field(str, default="REVISE", choices=["REVISE", "PROCEED", "ABORT"])
    failure_class = Field(
        str,
        default="LOCAL_DEFECT",
        choices=[
            "LOCAL_DEFECT",
            "MISSING_PREREQUISITE",
            "STALE_DEPENDENCY",
            "INTERFACE_MISMATCH",
            "INSUFFICIENT_EVIDENCE",
            "PERMISSION_DENIED",
            "CAPABILITY_MISMATCH",
        ],
    )
    affected_dependency = Field(Optional[str], default=None)
    consumed_version = Field(Optional[int], default=None)
    required_version = Field(Optional[int], default=None)
    repair_scope = Field(str, default="LOCAL_ONLY", choices=["LOCAL_ONLY", "DEPENDENCY_AND_DESCENDANTS", "CONTRACT_REPAIR"])
    evidence_refs = Field(list, default_factory=list)
    feedback = Field(str, default="")


class CriterionEvidenceSchema(Schema):
    """Schema definition for structured, typed verification CriterionEvidence."""
    criterion_id = Field(str, required=True, description="Criterion or gate identifier")
    status = Field(str, default="MET", choices=["MET", "FAILED", "UNVERIFIED"])
    evidence_type = Field(
        str,
        default="TEST_RESULT",
        choices=["TEST_RESULT", "SCHEMA_VALIDATION", "INVARIANT_CHECK", "STRUCTURAL_CHECK", "MODEL_JUDGMENT"],
    )
    evidence_ref = Field(str, default="")
    artifact_version = Field(int, default=1)
    timestamp = Field(str, default="")
    details = Field(dict, default_factory=dict)


class AgentResponseSchema(Schema):
    """Schema definition for standard DAFG AgentResponse."""
    output = Field(str, default="", description="Primary response text or summary")
    status = Field(
        str,
        default="COMPLETED",
        choices=["COMPLETED", "FAILED", "ERROR", "REJECTED", "READY", "BLOCKED", "PENDING", "RUNNING"],
        description="Agent execution status",
    )
    needs = Field(list, default_factory=list, description="Dynamic prerequisites or dependencies")
    spawn_children = Field(list, default_factory=list, description="Child task nodes in depth tree")
    files_modified = Field(List[str], default_factory=list, description="List of files touched")
    metadata = Field(dict, default_factory=dict, description="Arbitrary metadata dictionary")
    revision_directive = Field(Optional[dict], default=None, description="Diagnostic revision directive")
    published_contracts = Field(list, default_factory=list, description="Interface contracts published by agent")
    criterion_evidence = Field(list, default_factory=list, description="Structured criterion evidence records")


class BypassPolicySchema(Schema):
    """Schema definition for BypassPolicy."""
    max_files = Field(int, default=1, min_value=1)
    allow_contracts = Field(bool, default=False)
    allow_permissions = Field(bool, default=False)
    max_ambiguity = Field(float, default=0.15)
    shadow_sample_rate = Field(float, default=0.10)


class BypassTelemetrySchema(Schema):
    """Schema definition for BypassTelemetry."""
    total_runs = Field(int, default=0)
    bypassed_runs = Field(int, default=0)
    misrouted_runs = Field(int, default=0)
    shadow_runs = Field(int, default=0)
    shadow_defects_caught = Field(int, default=0)
    bypass_rate = Field(float, default=0.0)
    bypass_misroute_rate = Field(float, default=0.0)
    shadow_delta = Field(float, default=0.0)


class EvaluationTrialSchema(Schema):
    """Schema definition for EvaluationTrial."""
    trial_id = Field(str, required=True)
    task_id = Field(str, required=True)
    condition = Field(str, default="cli")
    is_feasible = Field(bool, default=True)
    completion_claim = Field(str, default="SUCCESS", choices=["SUCCESS", "PARTIAL", "BLOCKED", "FAILED"])
    standard_outcome = Field(
        str,
        default="VERIFIED_SUCCESS",
        choices=["VERIFIED_SUCCESS", "CORRECT_BLOCK", "VERIFIED_FAILURE", "EVALUATION_ERROR", "EXECUTION_ERROR"],
    )
    tokens_consumed = Field(int, default=0)
    duration_seconds = Field(float, default=0.0)
    error_reason = Field(Optional[str], default=None)
    bypass_used = Field(bool, default=False)
    shadow_divergence = Field(bool, default=False)
    timestamp = Field(str, default="")


class ResponseValidator:
    """Validates raw agent outputs or dictionaries against schemas."""

    def __init__(self, schema: Optional[Union[Schema, Type[Schema], Dict[str, Any]]] = None):
        if schema is None:
            self.schema = AgentResponseSchema()
        elif isinstance(schema, Schema):
            self.schema = schema
        elif isinstance(schema, type) and issubclass(schema, Schema):
            self.schema = schema()
        elif isinstance(schema, dict):
            self.schema = Schema(fields=schema)
        else:
            raise TypeError(f"Invalid schema specification: {schema}")

    def validate(self, response: Union[str, Dict[str, Any], Any]) -> Dict[str, Any]:
        """Validate response against the configured schema."""
        if isinstance(response, str):
            parsed = parse_json_response(response)
        elif isinstance(response, dict):
            parsed = response
        elif hasattr(response, "to_dict") and callable(response.to_dict):
            parsed = response.to_dict()
        else:
            parsed = response

        return self.schema.validate(parsed)

    @classmethod
    def validate_agent_response(cls, response: Union[str, Dict[str, Any], Any]) -> Any:
        """Validate response and return a validated AgentResponse object."""
        from dafg.runtime import AgentResponse, CriterionEvidence, InterfaceContract, RevisionDirective

        if isinstance(response, AgentResponse):
            val_dict = AgentResponseSchema().validate(response.to_dict())
            return AgentResponse(
                output=val_dict.get("output", ""),
                status=val_dict.get("status", "COMPLETED"),
                needs=response.needs,
                spawn_children=response.spawn_children,
                files_modified=val_dict.get("files_modified", []),
                metadata=val_dict.get("metadata", {}),
                revision_directive=response.revision_directive,
                published_contracts=response.published_contracts,
                criterion_evidence=response.criterion_evidence,
            )

        if isinstance(response, str):
            parsed = parse_json_response(response)
        elif isinstance(response, dict):
            parsed = response
        else:
            raise ValidationError(f"Cannot validate agent response of type {type(response).__name__}")

        val_dict = AgentResponseSchema().validate(parsed)
        rev_dir = val_dict.get("revision_directive")
        if rev_dir and isinstance(rev_dir, dict):
            rev_dir = RevisionDirective.from_dict(rev_dir)

        pub_contracts = [
            InterfaceContract.from_dict(c) if isinstance(c, dict) else c
            for c in val_dict.get("published_contracts", [])
        ]
        crit_evidence = [
            CriterionEvidence.from_dict(e) if isinstance(e, dict) else e
            for e in val_dict.get("criterion_evidence", [])
        ]

        return AgentResponse(
            output=val_dict.get("output", ""),
            status=val_dict.get("status", "COMPLETED"),
            needs=val_dict.get("needs", []),
            spawn_children=val_dict.get("spawn_children", []),
            files_modified=val_dict.get("files_modified", []),
            metadata=val_dict.get("metadata", {}),
            revision_directive=rev_dir,
            published_contracts=pub_contracts,
            criterion_evidence=crit_evidence,
        )
