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
