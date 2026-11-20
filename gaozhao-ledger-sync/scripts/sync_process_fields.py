#!/usr/bin/env python3
"""Build DingTalk AI-table upsert payloads from an HR process ledger workbook.

The script does not call DingTalk directly. It generates JSON files that can be
checked with `dws aitable record ... --dry-run` and then applied with dws.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from openpyxl import load_workbook

DEFAULT_MAPPING = {
    "人力管培": {
        "简历": "简历情况",
        "简历优劣": "简历初筛评价",
        "电联优劣": "电话沟通评价",
        "一面 面试情况": "一面面试情况",
        "面试优劣": "面试综合评价",
        "面评": "面试面评汇总",
        "二面 面试情况": "二面面试情况",
        "空列9": "二面面评",
        "三面 面试情况": "三面面试情况",
        "最新状态": "个人台账最新状态",
    },
    "中大产研内推": {
        "简历": "简历情况",
        "简历初筛情况": "简历初筛评价",
        "一面 面试情况": "一面面试情况",
        "面评": "一面面评",
        "二面 面试情况": "二面面试情况",
        "面评_2": "二面面评",
        "三面 面试情况": "三面面试情况",
        "面评_3": "三面面评",
        "最新状态": "个人台账最新状态",
    },
}


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalized(value: Any) -> str:
    return " ".join(text(value).split())


def date_text(value: Any) -> str:
    return text(value) or "至今"


def read_excel(input_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    workbook = load_workbook(input_path, data_only=True)
    result: Dict[str, List[Dict[str, Any]]] = {}
    for worksheet in workbook.worksheets:
        rows = list(worksheet.iter_rows(values_only=True))
        if not rows:
            result[worksheet.title] = []
            continue
        raw_headers = [text(cell) for cell in rows[0]]
        header_counts = {}
        headers = []
        for header in raw_headers:
            if not header:
                headers.append(header)
                continue
            header_counts[header] = header_counts.get(header, 0) + 1
            occurrence = header_counts[header]
            headers.append(header if occurrence == 1 else f"{header}_{occurrence}")
        records = []
        for row in rows[1:]:
            records.append({headers[index]: value for index, value in enumerate(row) if index < len(headers) and headers[index]})
        result[worksheet.title] = records
    return result


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def format_basic_resume(item: Dict[str, Any]) -> str:
    sections = []
    education_lines = []
    for exp in item.get("educationExperiences") or []:
        line = "·".join([text(exp.get("school")), text(exp.get("degreeDesc")), text(exp.get("major"))]).strip("·")
        if line:
            education_lines.append(f"{line}（{date_text(exp.get('startDate'))}-{date_text(exp.get('endDate'))}）")
    if education_lines:
        sections.append("教育经历：" + "；".join(education_lines))

    work_lines = []
    for exp in item.get("workExperiences") or []:
        line = f"{text(exp.get('companyName'))} - {text(exp.get('serveJob'))}".strip(" -")
        if line:
            work_lines.append(f"{line}（{date_text(exp.get('startDate'))}-{date_text(exp.get('endDate'))}）")
    if work_lines:
        sections.append("工作/实习经历：" + "；".join(work_lines))
    return "\n".join(sections)


def build_payloads(
    input_path: Path,
    table_path: Path,
    records_path: Path,
    out_dir: Path,
    mapping: Dict[str, Dict[str, str]],
    name_field: str,
    job_field: str,
    note_field: str,
    resume_basic_path: Optional[Path],
) -> Dict[str, Any]:
    table = load_json(table_path)["data"]["tables"][0]
    field_id_by_name = {field["fieldName"]: field["fieldId"] for field in table["fields"]}
    missing_target_fields = sorted({
        target_name
        for sheet_mapping in mapping.values()
        for target_name in sheet_mapping.values()
        if target_name not in field_id_by_name
    })
    if missing_target_fields:
        raise ValueError(f"Target table is missing fields: {missing_target_fields}")

    current_records = load_json(records_path)["data"]["records"]
    record_by_name = {}
    duplicate_names = []
    for record in current_records:
        name = text(record.get("cells", {}).get(name_field))
        if not name:
            continue
        if name in record_by_name:
            duplicate_names.append(name)
        record_by_name[name] = record

    basic_by_name = {}
    if resume_basic_path:
        basic_items = load_json(resume_basic_path).values()
        basic_by_name = {
            text(item.get("name")): item
            for item in basic_items
            if text(item.get("name"))
        }

    source_records = read_excel(input_path)
    updates = []
    creates = []
    update_details = []
    create_details = []
    field_counter: Counter = Counter()

    for sheet_name, records in source_records.items():
        if sheet_name not in mapping:
            continue
        sheet_mapping = mapping[sheet_name]
        for source_item in records:
            name = text(source_item.get("姓名"))
            if not name:
                continue

            cells = {}
            for source_header, target_name in sheet_mapping.items():
                value = text(source_item.get(source_header))
                if value:
                    field_id = field_id_by_name[target_name]
                    cells[field_id] = value
                    field_counter[target_name] += 1

            resume_field = field_id_by_name["简历情况"]
            if not cells.get(resume_field) and name in basic_by_name:
                fallback = format_basic_resume(basic_by_name[name])
                if fallback:
                    cells[resume_field] = fallback
                    field_counter["简历情况"] += 1

            if name in record_by_name:
                record = record_by_name[name]
                changed_cells = {}
                changes = []
                for field_id, target_value in cells.items():
                    actual_value = text(record.get("cells", {}).get(field_id))
                    if normalized(actual_value) != normalized(target_value):
                        changed_cells[field_id] = target_value
                        changes.append({"fieldId": field_id, "from": actual_value, "to": target_value})
                if changed_cells:
                    updates.append({"recordId": record["recordId"], "cells": changed_cells})
                    update_details.append({"name": name, "recordId": record["recordId"], "changes": changes})
            else:
                create_cells = dict(cells)
                create_cells[name_field] = name
                if sheet_name == "人力管培":
                    create_cells[job_field] = "人力资源管培生"
                create_cells[note_field] = (
                    "来自个人台账同步；招聘岗位待补"
                    if sheet_name == "中大产研内推"
                    else "来自个人台账同步"
                )
                creates.append({"cells": create_cells})
                create_details.append({"name": name, "sheet": sheet_name, "cell_count": len(create_cells)})

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "process_updates.json").write_text(json.dumps(updates, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "process_creates.json").write_text(json.dumps(creates, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "input": str(input_path),
        "total_records_returned": len(current_records),
        "duplicate_names_in_table": duplicate_names,
        "existing_records_to_update": len(updates),
        "new_records_to_create": len(creates),
        "update_cells": sum(len(item["cells"]) for item in updates),
        "create_cells": sum(len(item["cells"]) for item in creates),
        "field_fill_counter": dict(field_counter),
        "update_details": update_details,
        "create_details": create_details,
    }
    (out_dir / "process_sync_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate DingTalk process-field upsert payloads from Excel.")
    parser.add_argument("--input", required=True, type=Path, help="Personal ledger Excel workbook")
    parser.add_argument("--table-json", required=True, type=Path, help="Output of dws aitable table get")
    parser.add_argument("--records-json", required=True, type=Path, help="Output of dws aitable record list")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for generated payload files")
    parser.add_argument("--mapping-json", type=Path, help="Optional custom sheet/header-to-field mapping")
    parser.add_argument("--resume-basic-json", type=Path, help="Optional local resume basic data for fallback summaries")
    parser.add_argument("--name-field", default="MNkArlN")
    parser.add_argument("--job-field", default="dwQg9oA")
    parser.add_argument("--note-field", default="9Wf7gUD")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mapping = DEFAULT_MAPPING if args.mapping_json is None else load_json(args.mapping_json)
    report = build_payloads(
        input_path=args.input,
        table_path=args.table_json,
        records_path=args.records_json,
        out_dir=args.out_dir,
        mapping=mapping,
        name_field=args.name_field,
        job_field=args.job_field,
        note_field=args.note_field,
        resume_basic_path=args.resume_basic_json,
    )
    public_report = {key: value for key, value in report.items() if key != "update_details"}
    print(json.dumps(public_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
