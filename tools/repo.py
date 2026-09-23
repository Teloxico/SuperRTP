#!/usr/bin/env python3
"""
Repository-wide helpers shared by every SuperRTP tool: paths, hashing, JSON I/O,
reproducible timestamps and filesystem safety guards.

Keep this module free of engine-specific knowledge; engine rules belong in the
registry (`registry/`), the transforms (`tools/transforms.py`) or the per-target
verifiers.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Timestamp written into build manifests when SOURCE_DATE_EPOCH is unset. A fixed
# value keeps manifests (and therefore the evidence that hashes them) reproducible.
FIXED_BUILD_TIMESTAMP = "1970-01-01T00:00:00Z"


def repo_path(*parts: str) -> str:
    """Absolute path of `parts` joined under the repository root."""
    return os.path.join(REPO_ROOT, *parts)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str):
    """Loads a JSON file, naming the file in any decode error."""
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: str, data, trailing_newline: bool = True) -> None:
    """
    Writes `data` as 2-space-indented JSON.

    `trailing_newline` exists because existing files are hash-bound byte-for-byte:
    build manifests were written without a final newline, evidence files with one.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        if trailing_newline:
            f.write("\n")


def _source_date_epoch():
    """Parses SOURCE_DATE_EPOCH; returns None when unset and raises when malformed."""
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw is None or raw == "":
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError(f"SOURCE_DATE_EPOCH must be an integer Unix timestamp, got {raw!r}") from exc


def build_timestamp() -> str:
    """Build-manifest timestamp: SOURCE_DATE_EPOCH if set, otherwise a fixed epoch."""
    sde = _source_date_epoch()
    return sde.isoformat() if sde else FIXED_BUILD_TIMESTAMP


def evidence_timestamp() -> str:
    """Runtime-evidence timestamp: SOURCE_DATE_EPOCH if set, otherwise the current UTC time."""
    sde = _source_date_epoch()
    return (sde or datetime.now(timezone.utc)).isoformat()


def parse_iso_timestamp(value: str, field_name: str) -> datetime:
    """Parses an ISO-8601 timestamp (accepting a trailing 'Z'); raises ValueError naming the field."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name} ISO-8601 timestamp '{value}': {exc}") from exc


def resolve_within(base: str, relative: str) -> str:
    """
    Joins `relative` onto `base` and refuses results that escape `base`.

    Registry and manifest paths are data; this guard stops an entry such as
    '../../x' from reading or writing outside the intended directory.
    """
    base_abs = os.path.abspath(base)
    candidate = os.path.abspath(os.path.join(base_abs, relative))
    if os.path.commonpath([base_abs, candidate]) != base_abs:
        raise ValueError(f"Path '{relative}' escapes its base directory '{base_abs}'")
    return candidate
