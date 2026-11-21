#!/usr/bin/env python3
"""Build validated, non-destructive DingTalk updates from Tencent Meeting minutes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from field_rules import build_catalog, display, load_json, require_fields, validate_cells

ROUND_FIELD_IDS = {1: "Vf5E9zp", 2: "2Swql54", 3: "RTLxO9K"}
ROUND_TIME_IDS = {1: "bZrNGjr", 2: "TKY0lvO", 3: "jZHCn4d"}
REQUIRED_FIELDS = {
    "候选人姓名": "MNkArlN",
    "一面面试情况": "Vf5E9zp", "二面面试情况": "2Swql54", "三面面试情况": "RTLxO9K",
    "一面面试时间": "bZrNGjr", "二面面试时间": "TKY0lvO", "三面面试时间": "jZHCn4d",
}
REQUIRED_MANIFEST_KEYS = {"name", "recordId", "round", "recordFileId"}


def build_payload(
    manifest_path: Path,
    minutes_dir: Path,
    out_dir: Path,
    table_path: Path,
    records_path: Path,
    allow_nonempty_overwrite: bool = False,
) -> Dict[str, Any]:
    catalog = build_catalog(load_json(table_path))
    require_fields(catalog, REQUIRED_FIELDS)
    records = load_json(records_path)["data"]["records"]
    record_by_id = {str(item.get("recordId")): item for item in records}
    if len(record_by_id) != len(records):
        raise ValueError("Duplicate recordId in current DingTalk records")

    manifest: List[Dict[str, Any]] = load_json(manifest_path)
    if not isinstance(manifest, list):
        raise ValueError("Manifest must be a JSON array")
    updates = []
    details = []
    conflicts = []
    unchanged = []
    seen_rounds = set()
    seen_files = set()

    for index, item in enumerate(manifest, start=1):
        if not isinstance(item, dict) or set(item) != REQUIRED_MANIFEST_KEYS:
            raise ValueError(f"Manifest item {index} must contain exactly {sorted(REQUIRED_MANIFEST_KEYS)}")
        name = str(item["name"]).strip()
        record_id = str(item["recordId"]).strip()
        record_file_id = str(item["recordFileId"]).strip()
        try:
            round_number = int(item["round"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Manifest item {index} has an invalid round") from exc
        if not all((name, record_id, record_file_id)):
            raise ValueError(f"Manifest item {index} contains an empty required value")
        if round_number not in ROUND_FIELD_IDS:
            raise ValueError(f"Unsupported round {round_number}; expected 1, 2 or 3")
        round_key = (record_id, round_number)
        if round_key in seen_rounds:
            raise ValueError(f"Duplicate manifest target: {record_id}, round {round_number}")
        if record_file_id in seen_files:
            raise ValueError(f"Duplicate Tencent recordFileId in manifest: {record_file_id}")
        seen_rounds.add(round_key)
        seen_files.add(record_file_id)

        record = record_by_id.get(record_id)
        if record is None:
            raise ValueError(f"recordId not found in latest DingTalk records: {record_id}")
        cells_now = record.get("cells") or {}
        actual_name = display(cells_now.get("MNkArlN"))
        if actual_name != name:
            raise ValueError(f"Candidate mismatch for {record_id}: manifest={name!r}, table={actual_name!r}")
        if not display(cells_now.get(ROUND_TIME_IDS[round_number])):
            raise ValueError(f"Round {round_number} for {record_id} has no interview time; refusing to guess")

        minutes_path = minutes_dir / f"{record_file_id}.json"
        minutes_data = load_json(minutes_path)
        minute = str(minutes_data["data"]["meeting_minute"]["minute"] or "").strip()
        if not minute:
            raise ValueError(f"Empty smart minutes for manifest item {index}")
        field_id = ROUND_FIELD_IDS[round_number]
        target_value = f"腾讯会议智能纪要：\n{minute}"
        actual_value = display(cells_now.get(field_id))
        if actual_value == target_value:
            unchanged.append({"recordId": record_id, "round": round_number})
            continue
        if actual_value and not allow_nonempty_overwrite:
            conflicts.append({
                "recordId": record_id, "round": round_number, "fieldId": field_id,
                "reason": "目标面试情况已有内容，默认保护人工/现网内容",
            })
            continue

        cells = {field_id: target_value}
        cell_errors = validate_cells(cells, catalog, record_id)
        if cell_errors:
            raise ValueError("; ".join(cell_errors))
        updates.append({"recordId": record_id, "cells": cells})
        details.append({
            "recordId": record_id, "round": round_number, "fieldId": field_id,
            "minute_length": len(minute),
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tmeet_minutes_updates.json").write_text(
        json.dumps(updates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "records": len(updates),
        "update_cells": sum(len(item["cells"]) for item in updates),
        "allow_nonempty_overwrite": allow_nonempty_overwrite,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "unchanged": unchanged,
        "details": details,
    }
    (out_dir / "tmeet_minutes_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate protected DingTalk payloads from Tencent Meeting minutes.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--minutes-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--table-json", required=True, type=Path, help="Latest dws field/table snapshot")
    parser.add_argument("--records-json", required=True, type=Path, help="Latest dws record list JSON")
    parser.add_argument("--allow-nonempty-overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_payload(
        args.manifest, args.minutes_dir, args.out_dir, args.table_json,
        args.records_json, args.allow_nonempty_overwrite,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
