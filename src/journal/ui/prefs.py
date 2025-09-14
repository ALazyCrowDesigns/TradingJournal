from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PREFS_PATH = Path("./userprefs.json")

_DEFAULTS = {
    "current_profile_id": 1,  # Default profile ID
    "profiles": {
        # Profile-specific preferences will be stored here
        # Format: {profile_id: {preferences}}
    },
    "global": {
        # Global preferences that apply regardless of profile
        "window_geometry": None,
        "last_import_directory": None,
    },
    # Default profile preferences (used as template for new profiles)
    "default_profile_prefs": {
        "columns_visible": [
            "trade_date",
            "symbol",
            "side",
            "size",
            "entry",
            "exit",
            "pnl",
            "return_pct",
            "prev_close",
            "o",
            "h",
            "l",
            "c",
            "v",
            "gap_pct",
            "range_pct",
            "closechg_pct",
        ],
        "filters": {
            "symbol": "",
            "side": "",
            "date_from": None,
            "date_to": None,
            "pnl_min": None,
            "pnl_max": None,
            "has_ohlcv": False,
        },
        "page_size": 100,
        "order_by": "trade_date",
        "order_dir": "desc",
    },
}


def load_prefs() -> dict[str, Any]:
    if not PREFS_PATH.exists():
        return _DEFAULTS.copy()
    try:
        loaded_prefs = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
        # Migrate old format if necessary
        loaded_prefs = migrate_old_prefs(loaded_prefs)
        # Merge with defaults, ensuring all required keys exist
        merged_prefs = _DEFAULTS.copy()
        merged_prefs.update(loaded_prefs)
        return merged_prefs
    except Exception:
        return _DEFAULTS.copy()


def save_prefs(p: dict[str, Any]) -> None:
    from contextlib import suppress

    with suppress(Exception):
        PREFS_PATH.write_text(json.dumps(p, indent=2), encoding="utf-8")


def get_current_profile_id(prefs: dict[str, Any]) -> int:
    """Get the currently active profile ID"""
    return prefs.get("current_profile_id", 1)


def set_current_profile_id(prefs: dict[str, Any], profile_id: int) -> None:
    """Set the currently active profile ID"""
    prefs["current_profile_id"] = profile_id


def get_profile_prefs(prefs: dict[str, Any], profile_id: int) -> dict[str, Any]:
    """Get preferences for a specific profile"""
    profile_key = str(profile_id)

    # If profile preferences don't exist, create them from defaults
    if profile_key not in prefs.get("profiles", {}):
        if "profiles" not in prefs:
            prefs["profiles"] = {}
        prefs["profiles"][profile_key] = prefs["default_profile_prefs"].copy()

    return prefs["profiles"][profile_key]


def set_profile_prefs(
    prefs: dict[str, Any], profile_id: int, profile_prefs: dict[str, Any]
) -> None:
    """Set preferences for a specific profile"""
    profile_key = str(profile_id)

    if "profiles" not in prefs:
        prefs["profiles"] = {}

    prefs["profiles"][profile_key] = profile_prefs


def get_global_prefs(prefs: dict[str, Any]) -> dict[str, Any]:
    """Get global preferences"""
    return prefs.get("global", {})


def set_global_pref(prefs: dict[str, Any], key: str, value: Any) -> None:
    """Set a global preference"""
    if "global" not in prefs:
        prefs["global"] = {}

    prefs["global"][key] = value


def migrate_old_prefs(prefs: dict[str, Any]) -> dict[str, Any]:
    """Migrate old preference format to new profile-aware format"""
    # Check if this is an old format (has columns_visible directly)
    if "columns_visible" in prefs:
        # This is old format, migrate to new format
        old_prefs = prefs.copy()
        new_prefs = _DEFAULTS.copy()

        # Move old preferences to profile 1
        profile_1_prefs = {
            "columns_visible": old_prefs.get(
                "columns_visible", new_prefs["default_profile_prefs"]["columns_visible"]
            ),
            "filters": old_prefs.get("filters", new_prefs["default_profile_prefs"]["filters"]),
            "page_size": old_prefs.get(
                "page_size", new_prefs["default_profile_prefs"]["page_size"]
            ),
            "order_by": old_prefs.get("order_by", new_prefs["default_profile_prefs"]["order_by"]),
            "order_dir": old_prefs.get(
                "order_dir", new_prefs["default_profile_prefs"]["order_dir"]
            ),
        }

        new_prefs["profiles"]["1"] = profile_1_prefs
        new_prefs["current_profile_id"] = 1

        return new_prefs

    return prefs
