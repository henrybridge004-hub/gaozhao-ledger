"""Shared DingTalk AI-table field and single-select validation helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def field_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data.get("fields"), list):
        return data["fields"]
    tables = data.get("tables") or []
    if tables and isinstance(tables[0], dict) and isinstance(tables[0].get("fields"), list):
        return tables[0]["fields"]
    raise ValueError("Field snapshot must contain data.fields or data.tables[0].fields")


def build_catalog(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}
    for field in field_list(payload):
        field_id = str(field.get("fieldId") or "").strip()
        name = str(field.get("fieldName") or "").strip()
        if not field_id or not name:
            raise ValueError("Every field must have a non-empty fieldId and fieldName")
        if field_id in catalog:
            raise ValueError(f"Duplicate fieldId: {field_id}")
        if name in names:
            raise ValueError(f"Duplicate fieldName: {name} ({names[name]}, {field_id})")
        options = {
            str(item.get("name") or "").strip()
            for item in (field.get("config") or {}).get("options") or []
            if str(item.get("name") or "").strip()
        }
        catalog[field_id] = {**field, "option_names": options}
        names[name] = field_id
    return catalog


def require_fields(catalog: dict[str, dict[str, Any]], expected: dict[str, str]) -> None:
    """Require exact name -> fieldId mappings; extra table fields are allowed."""
    by_name = {field["fieldName"]: field_id for field_id, field in catalog.items()}
    errors = []
    for name, expected_id in expected.items():
        actual_id = by_name.get(name)
        if actual_id is None:
            errors.append(f"missing field {name} ({expected_id})")
        elif actual_id != expected_id:
            errors.append(f"field {name} expected {expected_id}, got {actual_id}")
        elif catalog[expected_id]["fieldName"] != name:
            errors.append(f"fieldId {expected_id} is not {name}")
    if errors:
        raise ValueError("Field snapshot mismatch: " + "; ".join(errors))


def display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or value.get("value") or "").strip()
    if isinstance(value, list):
        return "；".join(filter(None, (display(item) for item in value)))
    return str(value).strip()


def validate_cells(
    cells: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    context: str = "record",
) -> list[str]:
    errors = []
    for field_id, raw_value in cells.items():
        field = catalog.get(field_id)
        if field is None:
            errors.append(f"{context}: unknown fieldId {field_id}")
            continue
        if field.get("type") != "singleSelect" or raw_value in (None, ""):
            continue
        value = display(raw_value)
        allowed = field.get("option_names") or set()
        if value not in allowed:
            errors.append(
                f"{context}: {field['fieldName']}={value!r} is not in {sorted(allowed)!r}"
            )
    return errors


def validate_records(
    records: Iterable[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
) -> list[str]:
    errors = []
    for record in records:
        record_id = str(record.get("recordId") or "<new>")
        errors.extend(validate_cells(record.get("cells") or {}, catalog, record_id))
    return errors
