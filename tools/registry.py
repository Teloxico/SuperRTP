#!/usr/bin/env python3
"""
Read access to the SuperRTP registry: canonical asset metadata, provenance
records and per-target slot mappings.

Layout:
  registry/assets/<file>.json       asset metadata, keyed by its "id"
  registry/provenance/<file>.json   provenance record, keyed by its "asset_id"
  registry/slots/<target>.json      slot mapping for one engine target
  schemas/<name>.schema.json        JSON schemas for the three record kinds

Lookups are strict: unreadable JSON, duplicate ids and missing records raise
`RegistryError` instead of being skipped, because a silently ignored record
would let a build or validation run against the wrong source of truth.
"""

import os

from repo import REPO_ROOT, load_json, resolve_within

ASSETS_DIR = os.path.join(REPO_ROOT, "registry", "assets")
PROVENANCE_DIR = os.path.join(REPO_ROOT, "registry", "provenance")
SLOTS_DIR = os.path.join(REPO_ROOT, "registry", "slots")
SCHEMAS_DIR = os.path.join(REPO_ROOT, "schemas")


class RegistryError(ValueError):
    pass


def _index_by(directory: str, key: str) -> dict:
    """Maps record[key] -> (path, record) for every *.json file in `directory`."""
    index = {}
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(directory, fname)
        record = load_json(path)
        if not isinstance(record, dict) or key not in record:
            raise RegistryError(f"Registry record {path} has no '{key}' field")
        record_id = record[key]
        if record_id in index:
            raise RegistryError(f"Duplicate registry id '{record_id}' in {index[record_id][0]} and {path}")
        index[record_id] = (path, record)
    return index


def list_targets() -> list:
    """Targets with a slot mapping, e.g. ['rm2000', 'rm2003', ...]."""
    return sorted(f[:-len(".json")] for f in os.listdir(SLOTS_DIR) if f.endswith(".json"))


def slot_mapping_path(target: str) -> str:
    path = os.path.join(SLOTS_DIR, f"{target}.json")
    if not os.path.exists(path):
        raise RegistryError(f"Target slot mapping not found: {path}")
    return path


def load_slot_mapping(target: str) -> dict:
    mapping = load_json(slot_mapping_path(target))
    if mapping.get("target") != target:
        raise RegistryError(f"Slot mapping {slot_mapping_path(target)} declares target '{mapping.get('target')}', expected '{target}'")
    return mapping


def find_asset(asset_id: str):
    """Returns (metadata_path, metadata) for a canonical asset id."""
    index = _index_by(ASSETS_DIR, "id")
    if asset_id not in index:
        raise RegistryError(f"Asset metadata for id '{asset_id}' not found in registry/assets/")
    return index[asset_id]


def find_provenance(asset_id: str):
    """Returns (record_path, record) for the provenance of a canonical asset id."""
    index = _index_by(PROVENANCE_DIR, "asset_id")
    if asset_id not in index:
        raise RegistryError(f"Provenance record for '{asset_id}' not found in registry/provenance/")
    return index[asset_id]


def asset_source_path(asset_meta: dict) -> str:
    """Absolute path of an asset's canonical source file, confined to the repository."""
    return resolve_within(REPO_ROOT, asset_meta["file"])


def read_asset_source(asset_id: str) -> bytes:
    _, meta = find_asset(asset_id)
    with open(asset_source_path(meta), "rb") as f:
        return f.read()


def load_schema(name: str) -> dict:
    """Loads schemas/<name>.schema.json (name: 'asset', 'provenance' or 'slot_mapping')."""
    return load_json(os.path.join(SCHEMAS_DIR, f"{name}.schema.json"))


# Licenses accepted for redistributable assets. Anything else, including vague terms
# such as "free for games", is rejected (legal/CLEAN_ROOM_POLICY.md section 2).
PERMITTED_LICENSES = frozenset({
    "CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "CC-BY-SA-4.0",
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "OFL-1.1", "Public Domain",
})

# Evidence each provenance source type must carry (mirrors schemas/provenance.schema.json).
_REQUIRED_BY_SOURCE_TYPE = {
    "project_synthetic": ("creation_tool", ()),
    "externally_licensed": ("upstream_source", ("author", "url", "license_evidence")),
    "ai_generated": ("generation_metadata", ("model", "provider", "prompt", "parameters", "date")),
}


def verify_provenance(asset_id: str, source_sha256: str) -> dict:
    """
    Enforces the clean-room provenance rules for one asset and returns its record.

    The record must hash-match the canonical source, attest no proprietary-RTP or
    OpenRTP derivation, use a permitted license, and carry the evidence its source
    type requires. Test-only synthetic assets must be CC0-1.0.
    """
    _, prov = find_provenance(asset_id)
    if prov.get("sha256") != source_sha256:
        raise ValueError(f"Provenance hash mismatch: expected {prov.get('sha256')}, got {source_sha256}")

    attestation = prov.get("clean_room_attestation", {})
    for flag in ("proprietary_rtp_derived", "openrtp_derived"):
        if attestation.get(flag) is not False:
            raise ValueError(f"Provenance violation: {flag} must be false")

    source_type = prov.get("source_type")
    if source_type not in _REQUIRED_BY_SOURCE_TYPE:
        raise ValueError(f"Invalid source_type: {source_type}. Must be one of {sorted(_REQUIRED_BY_SOURCE_TYPE)}")

    license_str = prov.get("license")
    if license_str not in PERMITTED_LICENSES:
        raise ValueError(f"Provenance license violation: '{license_str}' is not an approved redistribution license: {sorted(PERMITTED_LICENSES)}")

    field, subfields = _REQUIRED_BY_SOURCE_TYPE[source_type]
    value = prov.get(field)
    if not value:
        raise ValueError(f"Provenance violation: source_type '{source_type}' requires non-empty '{field}'")
    for sub in subfields:
        if not isinstance(value, dict) or not value.get(sub):
            raise ValueError(f"Provenance violation: {source_type} requires non-empty {field}.{sub}")

    if source_type == "project_synthetic" and prov.get("test_only") and license_str != "CC0-1.0":
        raise ValueError(f"Provenance violation: test_only synthetic asset must be CC0-1.0, got {license_str}")
    return prov
