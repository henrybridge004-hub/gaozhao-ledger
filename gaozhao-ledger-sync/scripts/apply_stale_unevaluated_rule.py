# -*- coding: utf-8 -*-
"""Build stale-unevaluated updates with strict enums, timezone and cancel guards."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from field_rules import build_catalog, display, load_json, require_fields, validate_cells

NAME_FIELD = "MNkArlN"
JOB_FIELD = "dwQg9oA"
OFFER_FIELD = "rbYLcli"
ENTRY_FIELD = "oWZ5bkr"
ROUNDS = [
    {"round": 1, "time": "bZrNGjr", "situation": "Vf5E9zp", "review": "78MqIBw", "result_field": "mwv1H5x", "reason_field": "n5pJCfI"},
    {"round": 2, "time": "TKY0lvO", "situation": "2Swql54", "review": "wj2JA1l", "result_field": "7NfUhqb", "reason_field": "TF6ydWI"},
    {"round": 3, "time": "jZHCn4d", "situation": "RTLxO9K", "review": "DWPu6oG", "result_field": "6n4KvRS", "reason_field": "KPhawKu"},
]
REQUIRED_FIELDS = {
    "候选人姓名": NAME_FIELD, "招聘岗位": JOB_FIELD, "Offer情况": OFFER_FIELD, "入职状态": ENTRY_FIELD,
    "一面面试时间": "bZrNGjr", "一面面试情况": "Vf5E9zp", "一面面评": "78MqIBw", "一面面试结果": "mwv1H5x", "一面原因": "n5pJCfI",
    "二面面试时间": "TKY0lvO", "二面面试情况": "2Swql54", "二面面评": "wj2JA1l", "二面面试结果": "7NfUhqb", "二面原因": "TF6ydWI",
    "三面面试时间": "jZHCn4d", "三面面试情况": "RTLxO9K", "三面面评": "DWPu6oG", "三面面试结果": "6n4KvRS", "三面原因": "KPhawKu",
}
BLOCKING_OFFER_STATES = {"已发offer", "拒绝offer", "接受offer", "录用审批中", "offer已接受（待入职）", "待入职"}
BLOCKING_ENTRY_STATES = {"待入职", "已入职", "放弃入职", "待入职（审批中）"}


def parse_time(value):
    text = display(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO time: {text}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Time must include an explicit timezone: {text}")
    return parsed


def has_blocking_downstream(offer: str, entry: str) -> bool:
    return offer in BLOCKING_OFFER_STATES or entry in BLOCKING_ENTRY_STATES


def is_canceled_round(cells: dict, info: dict) -> bool:
    text = " ".join(
        display(cells.get(info[key]))
        for key in ("situation", "review", "result_field", "reason_field")
    ).lower()
    return "取消" in text or "cancel" in text


def evaluate_records(records: list[dict], catalog: dict, now: datetime, stale_days: int = 3):
    cutoff = now - timedelta(days=stale_days)
    updates, eligible, skipped, unevaluated = [], [], [], []
    for record in records:
        record_id = str(record.get("recordId") or "")
        cells = record.get("cells") or {}
        name = display(cells.get(NAME_FIELD))
        record_errors = validate_cells(cells, catalog, record_id)
        if record_errors:
            skipped.append({"recordId": record_id, "name": name, "reason": "字段/枚举校验失败", "errors": record_errors})
            continue

        round_infos = []
        try:
            for config in ROUNDS:
                round_infos.append({
                    **config,
                    "interview_time": parse_time(cells.get(config["time"])),
                    "result": display(cells.get(config["result_field"])),
                })
        except ValueError as exc:
            skipped.append({"recordId": record_id, "name": name, "reason": str(exc)})
            continue

        unevaluated_rounds = [info for info in round_infos if info["result"] == "未评价"]
        if unevaluated_rounds:
            unevaluated.append({
                "recordId": record_id, "name": name, "job": display(cells.get(JOB_FIELD)),
                "rounds": [
                    {"round": info["round"], "time": info["interview_time"].isoformat() if info["interview_time"] else ""}
                    for info in unevaluated_rounds
                ],
            })
        scheduled = [info for info in round_infos if info["interview_time"] is not None]
        if not scheduled:
            if unevaluated_rounds:
                skipped.append({"recordId": record_id, "name": name, "reason": "未评价但缺少面试时间，无法计算时长"})
            continue
        if any(is_canceled_round(cells, info) for info in scheduled):
            skipped.append({"recordId": record_id, "name": name, "reason": "存在取消面试或取消相关记录，需人工复核"})
            continue

        last_scheduled = max(scheduled, key=lambda info: info["round"])
        if last_scheduled["result"] != "未评价":
            continue
        later_rounds = [info for info in round_infos if info["round"] > last_scheduled["round"]]
        reasons = []
        if any(info["interview_time"] is not None for info in later_rounds):
            reasons.append("已安排后续面试")
        if any(
            display(cells.get(info["result_field"])) or display(cells.get(info["review"]))
            or display(cells.get(info["situation"])) or display(cells.get(info["reason_field"]))
            for info in later_rounds
        ):
            reasons.append("后续轮次已有状态或记录")
        if has_blocking_downstream(display(cells.get(OFFER_FIELD)), display(cells.get(ENTRY_FIELD))):
            reasons.append("已有Offer、录用或入职下游状态")
        if last_scheduled["interview_time"] > now:
            reasons.append("最后一轮面试时间尚未发生")
        if last_scheduled["interview_time"] >= cutoff:
            reasons.append(f"未评价时长未超过{stale_days}天")
        if reasons:
            skipped.append({
                "recordId": record_id, "name": name, "last_round": last_scheduled["round"],
                "reason": "；".join(reasons),
            })
            continue

        age_hours = round((now - last_scheduled["interview_time"]).total_seconds() / 3600, 1)
        eligible.append({
            "recordId": record_id, "name": name, "job": display(cells.get(JOB_FIELD)),
            "last_round": last_scheduled["round"],
            "interview_time": last_scheduled["interview_time"].isoformat(),
            "age_hours": age_hours,
        })
        updates.append({"recordId": record_id, "cells": {last_scheduled["result_field"]: "未通过"}})

    for payload in updates:
        errors = validate_cells(payload["cells"], catalog, payload["recordId"])
        if errors:
            raise ValueError("Generated update failed option validation: " + "; ".join(errors))
    return updates, eligible, skipped, unevaluated


def main():
    parser = argparse.ArgumentParser(description="Build stale unevaluated interview update payload")
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--table-json", type=Path, required=True, help="Latest dws field/table snapshot")
    parser.add_argument("--out-updates", type=Path, required=True)
    parser.add_argument("--out-report", type=Path, required=True)
    parser.add_argument("--now", help="ISO timestamp with explicit timezone; defaults to local aware time")
    parser.add_argument("--stale-days", type=int, default=3)
    args = parser.parse_args()
    if args.stale_days < 0:
        raise ValueError("--stale-days must be non-negative")
    now = parse_time(args.now) if args.now else datetime.now().astimezone()
    catalog = build_catalog(load_json(args.table_json))
    require_fields(catalog, REQUIRED_FIELDS)
    records = load_json(args.records)["data"]["records"]
    updates, eligible, skipped, unevaluated = evaluate_records(records, catalog, now, args.stale_days)

    args.out_updates.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_updates.write_text(json.dumps(updates, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "rule": {
            "status": "未评价", "target_status": "未通过", "stale_days": args.stale_days,
            "now": now.isoformat(), "cutoff": (now - timedelta(days=args.stale_days)).isoformat(),
            "strict_over_stale_threshold": True,
            "duration_basis": "面试时间代理；无真实状态变更时间，改期/补录记录需人工复核",
            "offer_guard": sorted(BLOCKING_OFFER_STATES),
            "entry_guard": sorted(BLOCKING_ENTRY_STATES),
        },
        "record_count": len(records), "unevaluated_record_count": len(unevaluated),
        "eligible_count": len(updates), "skipped_count": len(skipped),
        "eligible": eligible, "skipped": skipped, "all_unevaluated": unevaluated,
    }
    args.out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "record_count": len(records), "unevaluated_record_count": len(unevaluated),
        "eligible_count": len(updates), "skipped_count": len(skipped),
        "out_updates": str(args.out_updates), "out_report": str(args.out_report),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
