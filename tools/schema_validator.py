#!/usr/bin/env python3
"""
Minimal deterministic JSON Schema validator (standard library only).

Implements the draft 2020-12 keywords the SuperRTP schemas use:
  type (single name or list), const, enum, minimum, maximum, pattern,
  required, properties, additionalProperties (boolean *or* subschema),
  items, minItems, maxItems, allOf, anyOf, oneOf, if/then/else.

Annotation-only keywords ($schema, $id, title, description) are ignored.
Any other keyword raises `SchemaValidationError`, so a schema can never rely
on a constraint this validator would silently skip.

Usage:
  python3 tools/schema_validator.py <data.json> <schema.json>
"""

import json
import os
import re
import sys

_ANNOTATIONS = {"$schema", "$id", "title", "description"}
_SUPPORTED = _ANNOTATIONS | {
    "type", "const", "enum", "minimum", "maximum", "pattern",
    "required", "properties", "additionalProperties",
    "items", "minItems", "maxItems",
    "allOf", "anyOf", "oneOf", "if", "then", "else",
}

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


class SchemaValidationError(ValueError):
    pass


def _matches(data, schema, path) -> bool:
    try:
        validate_schema(data, schema, path=path)
        return True
    except SchemaValidationError:
        return False


def validate_schema(data, schema, path="root"):
    """Recursively validates `data` against `schema`; raises SchemaValidationError on the first violation."""
    unsupported = set(schema) - _SUPPORTED
    if unsupported:
        raise SchemaValidationError(f"[{path}] Schema uses unsupported keyword(s): {sorted(unsupported)}")

    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        unknown = [t for t in allowed if t not in _TYPE_CHECKS]
        if unknown:
            raise SchemaValidationError(f"[{path}] Schema uses unknown type(s): {unknown}")
        if not any(_TYPE_CHECKS[t](data) for t in allowed):
            raise SchemaValidationError(f"[{path}] Expected type '{expected_type}', got {type(data).__name__}")

    if "const" in schema and data != schema["const"]:
        raise SchemaValidationError(f"[{path}] Expected const value {schema['const']!r}, got {data!r}")

    if "enum" in schema and data not in schema["enum"]:
        raise SchemaValidationError(f"[{path}] Value {data!r} is not in enum: {schema['enum']}")

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            raise SchemaValidationError(f"[{path}] Value {data} is less than minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            raise SchemaValidationError(f"[{path}] Value {data} is greater than maximum {schema['maximum']}")

    if isinstance(data, str) and "pattern" in schema and not re.search(schema["pattern"], data):
        raise SchemaValidationError(f"[{path}] String '{data}' does not match pattern '{schema['pattern']}'")

    if isinstance(data, dict):
        for req in schema.get("required", []):
            if req not in data:
                raise SchemaValidationError(f"[{path}] Missing required property: '{req}'")

        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, val in data.items():
            child_path = f"{path}.{key}"
            if key in properties:
                validate_schema(val, properties[key], path=child_path)
            elif additional is False:
                raise SchemaValidationError(f"[{path}] Additional property '{key}' is not permitted")
            elif isinstance(additional, dict):
                validate_schema(val, additional, path=child_path)

    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            raise SchemaValidationError(f"[{path}] Array length {len(data)} is less than minItems {schema['minItems']}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            raise SchemaValidationError(f"[{path}] Array length {len(data)} is greater than maxItems {schema['maxItems']}")
        if "items" in schema:
            for idx, item in enumerate(data):
                validate_schema(item, schema["items"], path=f"{path}[{idx}]")

    for idx, subschema in enumerate(schema.get("allOf", [])):
        validate_schema(data, subschema, path=f"{path}.allOf[{idx}]")

    if "anyOf" in schema and not any(_matches(data, sub, path) for sub in schema["anyOf"]):
        raise SchemaValidationError(f"[{path}] Data does not match any schema in 'anyOf'")

    if "oneOf" in schema:
        match_count = sum(1 for sub in schema["oneOf"] if _matches(data, sub, path))
        if match_count != 1:
            raise SchemaValidationError(f"[{path}] Data matched {match_count} schemas in 'oneOf', expected exactly 1")

    if "if" in schema:
        branch = "then" if _matches(data, schema["if"], path) else "else"
        if branch in schema:
            validate_schema(data, schema[branch], path=path)

    return True


def validate_file_against_schema(data_filepath, schema_filepath):
    """Loads and validates a JSON data file against a schema file."""
    with open(data_filepath, "r", encoding="utf-8") as df:
        data = json.load(df)
    with open(schema_filepath, "r", encoding="utf-8") as sf:
        schema = json.load(sf)
    validate_schema(data, schema, path=os.path.basename(data_filepath))
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 tools/schema_validator.py <data.json> <schema.json>")
        sys.exit(2)
    try:
        validate_file_against_schema(sys.argv[1], sys.argv[2])
    except (OSError, json.JSONDecodeError, SchemaValidationError) as e:
        print(f"Schema validation FAILED: {e}")
        sys.exit(1)
    print("Schema validation PASSED.")
