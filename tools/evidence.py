#!/usr/bin/env python3
"""
Shared building blocks for runtime verification evidence
(`artifacts/runtime/<target>/<category>/verification_evidence.json`).

Every verifier binds the same kinds of facts: pinned identities, file hashes, runtime
logs, a negative control and screenshots. These helpers keep those checks uniform and
their failure messages stable. Messages follow the pattern "<what> mismatch: expected X,
got Y"; the tamper tests match on the "<what> mismatch" prefix, so keep it when editing.
"""

import hashlib
import json
import os

from repo import load_json, parse_iso_timestamp, sha256_file, write_json


class EvidenceError(ValueError):
    """An evidence record disagrees with the files or rules it is supposed to bind."""


def load_evidence(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Verification evidence file not found: {path}")
    evidence = load_json(path)
    if not isinstance(evidence, dict):
        raise EvidenceError(f"Verification evidence {path} must contain a JSON object")
    return evidence


def write_evidence(path: str, evidence: dict, trailing_newline: bool = True) -> None:
    write_json(path, evidence, trailing_newline=trailing_newline)
    print(f"Wrote verification evidence to {path}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def expect_field(evidence: dict, field: str, expected, label: str = None) -> None:
    """Requires evidence[field] == expected; the message starts with '<label> mismatch'."""
    actual = evidence.get(field)
    if actual != expected:
        raise EvidenceError(f"{label or f'Evidence {field}'} mismatch: expected {expected!r}, got {actual!r}")


def check_file_hash(path: str, expected: str, label: str) -> str:
    """
    Requires the SHA-256 of `path` to equal `expected`.

    `label` names the bound value, e.g. "Target manifest hash"; failures read
    "<label> mismatch: expected ..., got ...". Returns the actual hash.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"{label}: file not found at {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise EvidenceError(f"{label} mismatch: expected {expected}, got {actual}")
    return actual


def check_timestamp(evidence: dict, field: str) -> None:
    parse_iso_timestamp(evidence.get(field, ""), field)


def config_sha256(config: dict, indent=None) -> str:
    """
    Hash of a portable runtime configuration object.

    Two historical encodings are in use and both are hash-bound in committed evidence:
    RMXP/RMVX serialize with sort_keys and indent=2, RMVX Ace with sort_keys only.
    """
    return hashlib.sha256(json.dumps(config, sort_keys=True, indent=indent).encode("utf-8")).hexdigest()


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def check_negative_control(evidence: dict, expected_missing: str, expected_diagnostic: str) -> dict:
    """
    Validates the `negative_control` block shared by the EasyRPG and mkxp-z verifiers:
    status, the asset expected to be missing, the diagnostic, and a screenshot entry
    whose hash agrees with the `screenshots` table.
    """
    neg = evidence.get("negative_control")
    require(isinstance(neg, dict), "Missing or invalid negative_control sub-object in evidence")
    require(neg.get("status") == "VERIFIED", f"negative_control.status mismatch: expected 'VERIFIED', got {neg.get('status')!r}")
    require(neg.get("expected_missing_asset") == expected_missing,
            f"negative_control.expected_missing_asset mismatch: expected '{expected_missing}', got {neg.get('expected_missing_asset')!r}")
    require(neg.get("diagnostic") == expected_diagnostic,
            f"negative_control.diagnostic mismatch: expected '{expected_diagnostic}', got {neg.get('diagnostic')!r}")
    shots = evidence.get("screenshots", {})
    shot = neg.get("screenshot")
    require(bool(shot) and shot in shots, f"negative_control screenshot '{shot}' not present in evidence screenshots")
    require(neg.get("screenshot_sha256") == shots[shot], "negative_control screenshot_sha256 mismatch with screenshots table")
    return neg


def check_log(artifacts_dir: str, evidence: dict, kind: str, required_text=()) -> str:
    """
    Verifies the `<kind>_runtime_log` hash (kind: 'positive' or 'negative') and that the
    log contains every string in `required_text`. Returns the log text.
    """
    name = evidence.get(f"{kind}_runtime_log", f"{kind}_runtime.log")
    path = os.path.join(artifacts_dir, name)
    check_file_hash(path, evidence.get(f"{kind}_runtime_log_sha256"), f"{kind.capitalize()} runtime log hash")
    text = read_text(path)
    for needle in required_text:
        require(needle in text, f"Expected diagnostic '{needle}' not found in {kind} runtime log")
    return text


def check_screenshots(artifacts_dir: str, screenshots: dict, inspect) -> None:
    """
    Verifies every screenshot hash, then re-runs pixel inspection.

    `inspect(name, path)` returns a short status string or raises.
    """
    for name, expected in screenshots.items():
        path = os.path.join(artifacts_dir, name)
        check_file_hash(path, expected, f"Screenshot '{name}' SHA-256")
        print(f"  [PASS] {name}: SHA-256 match, {inspect(name, path)}")
