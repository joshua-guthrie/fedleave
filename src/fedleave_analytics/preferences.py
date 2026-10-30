"""Versioned analytics assertions beside existing GUI preferences, never ledgers."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from fedleave.planning import fingerprint
from fedleave_gui.settings import settings_path

from .planning_model import write_export

PREFERENCE_VERSION = 1


def analytics_preferences_path():
    return settings_path().with_name("analytics.json")


def source_preferences_key(snapshot):
    context = snapshot.get("calculation_context", {})
    return fingerprint({"backend": context.get("backend"), "data_store": context.get("data_store")})


def _valid_document(payload):
    return (
        isinstance(payload, dict)
        and type(payload.get("schema_version")) is int
        and payload["schema_version"] == PREFERENCE_VERSION
        and isinstance(payload.get("sources"), dict)
    )


def _validate_source(preferences):
    if (
        not isinstance(preferences, dict)
        or not isinstance(preferences.get("coverage", []), list)
        or any(not isinstance(row, dict) for row in preferences.get("coverage", []))
    ):
        raise ValueError("Malformed analytics coverage preferences; no historical coverage is assumed.")
    for key in ("excluded_years", "reference_years"):
        values = preferences.get(key, [])
        if not isinstance(values, list) or any(type(year) is not int for year in values):
            raise ValueError("Malformed analytics year preferences; no historical coverage is assumed.")
    strategy = preferences.get("budget_strategy", "even")
    if not isinstance(strategy, str) or strategy not in {"even", "earliest", "latest", "weighted"}:
        raise ValueError("Unsupported Leave Budget strategy preference.")


def load_preferences(snapshot):
    path = analytics_preferences_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"coverage": [], "excluded_years": []}
    except (OSError, ValueError) as exc:
        raise ValueError(f"Analytics preferences could not be read: {exc}") from exc
    if not _valid_document(payload):
        raise ValueError("Unsupported analytics preference schema; no historical coverage is assumed.")
    selected = payload["sources"].get(source_preferences_key(snapshot), {"coverage": [], "excluded_years": []})
    _validate_source(selected)
    return deepcopy(selected)


def save_preferences(snapshot, preferences):
    _validate_source(preferences)
    path = analytics_preferences_path().expanduser().resolve()
    store = snapshot.get("calculation_context", {}).get("data_store")
    if store:
        if path.is_relative_to(Path(store).expanduser().resolve()):
            raise ValueError("Analytics preferences must be outside the selected leave datastore.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {"schema_version": PREFERENCE_VERSION, "sources": {}}
    if not _valid_document(payload):
        raise ValueError("Cannot replace unsupported analytics preferences.")
    key = source_preferences_key(snapshot)
    # Another open analytics view may have saved its own keys since this view
    # loaded. Preserve those keys while replacing the explicitly supplied ones.
    previous = payload["sources"].get(key, {})
    _validate_source(previous)
    payload["sources"][key] = {**previous, **deepcopy(preferences)}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_export(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", snapshot)
