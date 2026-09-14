#!/usr/bin/env python3
"""
Lightweight Deterministic JSON Schema Validator for SuperRTP.

Enforces schema validation on assets, provenance records, and slot mappings
using only Python standard library without external dependencies.
Supports draft 2020-12 core features:
  - type (string, integer, number, boolean, object, array, null)
  - required
  - properties & additionalProperties
  - enum & const
  - pattern (regex)
  - minimum & maximum
  - items, minItems, maxItems
"""

import os
import sys
import json
import re

class SchemaValidationError(ValueError):
    pass

def validate_schema(data, schema, path="root"):
    """Recursively validates data against a JSON schema."""
    # 1. Type validation
    expected_type = schema.get("type")
    if expected_type:
        type_checks = {
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: (isinstance(v, (int, float))) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "null": lambda v: v is None,
        }
        if expected_type in type_checks and not type_checks[expected_type](data):
            raise SchemaValidationError(f"[{path}] Expected type '{expected_type}', got {type(data).__name__}")

    # 2. Const validation
    if "const" in schema:
        if data != schema["const"]:
            raise SchemaValidationError(f"[{path}] Expected const value {schema['const']!r}, got {data!r}")

    # 3. Enum validation
    if "enum" in schema:
        if data not in schema["enum"]:
            raise SchemaValidationError(f"[{path}] Value {data!r} is not in enum: {schema['enum']}")

    # 4. Numeric bounds
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            raise SchemaValidationError(f"[{path}] Value {data} is less than minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            raise SchemaValidationError(f"[{path}] Value {data} is greater than maximum {schema['maximum']}")

    # 5. String pattern
    if isinstance(data, str):
        if "pattern" in schema:
            if not re.search(schema["pattern"], data):
                raise SchemaValidationError(f"[{path}] String '{data}' does not match pattern '{schema['pattern']}'")

    # 6. Object validation
    if isinstance(data, dict):
        required_props = schema.get("required", [])
        for req in required_props:
            if req not in data:
                raise SchemaValidationError(f"[{path}] Missing required property: '{req}'")

        properties = schema.get("properties", {})
        additional_allowed = schema.get("additionalProperties", True)

        for key, val in data.items():
            if key in properties:
                validate_schema(val, properties[key], path=f"{path}.{key}")
            elif not additional_allowed:
                raise SchemaValidationError(f"[{path}] Additional property '{key}' is not permitted")

    # 7. Array validation
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            raise SchemaValidationError(f"[{path}] Array length {len(data)} is less than minItems {schema['minItems']}")
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            raise SchemaValidationError(f"[{path}] Array length {len(data)} is greater than maxItems {schema['maxItems']}")

        if "items" in schema:
            item_schema = schema["items"]
            for idx, item in enumerate(data):
                validate_schema(item, item_schema, path=f"{path}[{idx}]")

    # 8. Combinator: allOf
    if "allOf" in schema:
        for idx, subschema in enumerate(schema["allOf"]):
            validate_schema(data, subschema, path=f"{path}.allOf[{idx}]")

    # 9. Combinator: anyOf
    if "anyOf" in schema:
        matched = False
        for subschema in schema["anyOf"]:
            try:
                validate_schema(data, subschema, path=path)
                matched = True
                break
            except SchemaValidationError:
                pass
        if not matched:
            raise SchemaValidationError(f"[{path}] Data does not match any schema in 'anyOf'")

    # 10. Combinator: oneOf
    if "oneOf" in schema:
        match_count = 0
        for subschema in schema["oneOf"]:
            try:
                validate_schema(data, subschema, path=path)
                match_count += 1
            except SchemaValidationError:
                pass
        if match_count != 1:
            raise SchemaValidationError(f"[{path}] Data matched {match_count} schemas in 'oneOf', expected exactly 1")

    # 11. Conditional: if / then / else
    if "if" in schema:
        condition_met = True
        try:
            validate_schema(data, schema["if"], path=path)
        except SchemaValidationError:
            condition_met = False

        if condition_met and "then" in schema:
            validate_schema(data, schema["then"], path=path)
        elif not condition_met and "else" in schema:
            validate_schema(data, schema["else"], path=path)

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
    if len(sys.argv) < 3:
        print("Usage: python3 tools/schema_validator.py <data.json> <schema.json>")
        sys.exit(1)
    try:
        validate_file_against_schema(sys.argv[1], sys.argv[2])
        print("Schema validation PASSED.")
    except Exception as e:
        print(f"Schema validation FAILED: {e}")
        sys.exit(1)
