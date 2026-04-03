"""
Usage tracker — tracks document uploads and queries per tier.
Data is persisted in usage_data.json.
"""

import json
from pathlib import Path

DATA_FILE = Path(__file__).parent / "usage_data.json"

TIERS = {
    "tier_1": {
        "name": "Starter",
        "documents_max": 2,
        "queries_max": 50,
    },
    "tier_2": {
        "name": "Pro",
        "documents_max": 50,
        "queries_max": "unlimited",
    },
}

_DEFAULT = {
    "tier_key": "tier_1",
    "documents_used": 0,
    "queries_used": 0,
}


def _load() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return dict(_DEFAULT)


def _save(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, indent=2))


def get_status() -> dict:
    data = _load()
    tier_key = data.get("tier_key", "tier_1")
    tier = TIERS.get(tier_key, TIERS["tier_1"])
    docs_used = data.get("documents_used", 0)
    queries_used = data.get("queries_used", 0)
    queries_max = tier["queries_max"]

    can_upload = docs_used < tier["documents_max"]
    can_query = queries_max == "unlimited" or queries_used < queries_max

    return {
        "tier_key": tier_key,
        "tier": tier["name"],
        "documents_used": docs_used,
        "documents_max": tier["documents_max"],
        "queries_used": queries_used,
        "queries_max": queries_max,
        "can_upload": can_upload,
        "can_query": can_query,
    }


def record_upload() -> dict:
    data = _load()
    data["documents_used"] = data.get("documents_used", 0) + 1
    _save(data)
    return get_status()


def record_query() -> dict:
    data = _load()
    data["queries_used"] = data.get("queries_used", 0) + 1
    _save(data)
    return get_status()


def set_tier(tier_num: int) -> dict:
    key = f"tier_{tier_num}"
    if key not in TIERS:
        raise ValueError(f"Unknown tier: {tier_num}")
    data = _load()
    data["tier_key"] = key
    _save(data)
    return get_status()


def reset() -> dict:
    _save(dict(_DEFAULT))
    return get_status()
