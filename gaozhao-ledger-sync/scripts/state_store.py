"""Tiny persistent state store for GaoZhao ledger sync.

The store keeps one entry per stable business key so daily runs can skip
unchanged detail fetches and update existing DingTalk records instead of
creating duplicates. It uses only the Python standard library.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def content_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def business_key(resume_id: str, apply_job_id: str) -> str:
    return f"{str(resume_id)}::{str(apply_job_id)}"


def fallback_key(name: str, mobile: str, job_name: str) -> str:
    return "fallback::" + hashlib.sha256(
        canonical_json({"name": name, "mobile": mobile, "job": job_name}).encode("utf-8")
    ).hexdigest()


def empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "last_successful_at": None,
        "last_cursor": None,
        "runs": {},
        "records": {},
    }


def load_state(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return empty_state()
    with p.open("r", encoding="utf-8") as f:
        state = json.load(f)
    if not isinstance(state, dict) or "records" not in state:
        raise ValueError("Invalid sync state file")
    return state


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)


def begin_run(state: dict[str, Any], run_id: str, mode: str,
              at: str, window: dict[str, Any]) -> None:
    state.setdefault("runs", {})[run_id] = {
        "mode": mode,
        "started_at": at,
        "finished_at": None,
        "success": False,
        "window": window,
        "errors": [],
    }


def upsert_record(state: dict[str, Any], key: str, payload: dict[str, Any],
                  at: str, dingtalk_record_id: str | None = None) -> dict[str, Any]:
    records = state.setdefault("records", {})
    new_hash = content_hash(payload)
    previous = records.get(key)
    if not previous:
        record = {
            "key": key,
            "first_seen_at": at,
            "last_seen_at": at,
            "last_detail_fetch_at": at,
            "content_hash": new_hash,
            "changed": True,
            "dingtalk_record_id": dingtalk_record_id,
            "last_status": payload.get("入职状态") or payload.get("Offer情况"),
            "failures": [],
        }
    else:
        record = previous
        record["last_seen_at"] = at
        record["last_detail_fetch_at"] = at
        record["changed"] = record.get("content_hash") != new_hash
        record["content_hash"] = new_hash
        record["last_status"] = payload.get("入职状态") or payload.get("Offer情况") or record.get("last_status")
        if dingtalk_record_id:
            record["dingtalk_record_id"] = dingtalk_record_id
    records[key] = record
    return record


def mark_written(state: dict[str, Any], key: str,
                 record_id: str, at: str) -> None:
    record = state["records"][key]
    record["dingtalk_record_id"] = record_id
    record["changed"] = False
    record["last_written_at"] = at
    record["failures"] = []


def mark_failure(state: dict[str, Any], key: str,
                 error: str, at: str) -> None:
    record = state.setdefault("records", {}).get(key)
    if record is None:
        record = {"key": key, "first_seen_at": at, "last_seen_at": at,
                  "changed": True, "failures": []}
        state["records"][key] = record
    record.setdefault("failures", []).append({"at": at, "error": error})


def finish_run(state: dict[str, Any], run_id: str, success: bool,
               at: str, cursor: str | None = None,
               errors: list[str] | None = None) -> None:
    run = state["runs"][run_id]
    run["finished_at"] = at
    run["success"] = success
    run["errors"] = errors or []
    if success:
        state["last_successful_at"] = at
        if cursor is not None:
            state["last_cursor"] = cursor


def _selftest() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "sync_state.json"
        state = load_state(path)
        key = business_key("r1", "j1")
        begin_run(state, "run-1", "full", "2026-11-16T20:30:00+08:00",
                  {"start": "2026-10-01", "end": "2026-11-16"})
        rec = upsert_record(state, key, {"Offer情况": "无", "入职状态": "未入职"},
                            "2026-11-16T20:30:00+08:00")
        assert rec["changed"] is True
        mark_written(state, key, "rec-001", "2026-11-16T20:31:00+08:00")
        finish_run(state, "run-1", True, "2026-11-16T20:31:00+08:00", "cursor-1")
        save_state(path, state)
        reloaded = load_state(path)
        assert reloaded["records"][key]["dingtalk_record_id"] == "rec-001"
        # Same payload is unchanged; later status move remains on the same key.
        rec2 = upsert_record(reloaded, key, {"Offer情况": "待入职", "入职状态": "待入职"},
                             "2026-11-17T20:30:00+08:00")
        assert rec2["changed"] is True
        assert reloaded["records"][key]["dingtalk_record_id"] == "rec-001"
    print("state_store selftest OK")


if __name__ == "__main__":
    _selftest()
