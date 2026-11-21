# -*- coding: utf-8 -*-
"""Validate generated ledger CSVs against a live DingTalk field snapshot."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from field_rules import build_catalog, require_fields, validate_cells

LEDGER_HEADERS = [
    "HR姓名", "候选人姓名", "来源渠道", "城市", "招聘岗位", "手机号",
    "最近任职公司", "上家任职职位", "薪资架构", "沟通备注", "HR沟通结果",
    "推荐简历时间", "简历推荐是否通过",
    "一面面试时间", "一面原因", "一面面试结果",
    "二面面试时间", "二面原因", "二面面试结果",
    "三面面试时间", "三面原因", "三面面试结果",
    "Offer情况", "入职状态", "入职时间", "备注",
]
INTERVIEW_HEADERS = [
    "候选人姓名", "HR", "招聘岗位", "面试轮次", "面试时间", "面试官",
    "面试结果", "评分", "面试评语", "能力项评分", "数据状态",
]
FUNNEL_HEADERS = [
    "HR", "周期", "接收简历", "推荐", "业务复筛通过", "安排面试",
    "实际面试", "面试通过", "offer", "待入职", "入职", "points",
]
SYSTEM_FIELDS = {
    "HR姓名": "4iqUuLZ", "候选人姓名": "MNkArlN", "来源渠道": "DsQMV4J",
    "城市": "jInv7wA", "招聘岗位": "dwQg9oA", "手机号": "sQgxES1",
    "最近任职公司": "h19Jcce", "上家任职职位": "ZTrJQ08", "薪资架构": "fvOMXI6",
    "沟通备注": "uwTE8Z2", "HR沟通结果": "r66IsE3", "推荐简历时间": "YoQTnWB",
    "简历推荐是否通过": "M1ChSRg", "一面面试时间": "bZrNGjr",
    "一面原因": "n5pJCfI", "一面面试结果": "mwv1H5x",
    "二面面试时间": "TKY0lvO", "二面原因": "TF6ydWI", "二面面试结果": "7NfUhqb",
    "三面面试时间": "jZHCn4d", "三面原因": "KPhawKu", "三面面试结果": "6n4KvRS",
    "Offer情况": "rbYLcli", "入职状态": "oWZ5bkr", "入职时间": "koS2hca", "备注": "9Wf7gUD",
}
ROUND_RESULT_FIELDS = {"一面": "mwv1H5x", "二面": "7NfUhqb", "三面": "6n4KvRS"}


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.reader(file))


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--interviews", required=True, type=Path)
    parser.add_argument("--funnel", type=Path)
    parser.add_argument("--fields-json", required=True, type=Path, help="Live dws field get/table get JSON")
    parser.add_argument("--strict", action="store_true", help="Return non-zero on any error")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    catalog = build_catalog(json.loads(args.fields_json.read_text(encoding="utf-8-sig")))
    require_fields(catalog, SYSTEM_FIELDS)

    ledger = read_csv(args.ledger)
    if not ledger:
        errors.append("台账为空")
    elif ledger[0] != LEDGER_HEADERS:
        errors.append(f"系统字段表头不一致：{ledger[0]}")
    if len(ledger) < 2:
        warnings.append("台账只有表头，没有数据行")

    rows = ledger[1:] if len(ledger) > 1 else []
    keys = Counter()
    hr_names = set()
    for line_number, row in enumerate(rows, start=2):
        if len(row) != len(LEDGER_HEADERS):
            errors.append(f"第 {line_number} 行列数 {len(row)}，应为 {len(LEDGER_HEADERS)}")
            continue
        hr_names.add(row[0])
        keys[(row[1], row[5], row[4])] += 1
        if "#REF!" in ",".join(row) or "#N/A" in ",".join(row):
            errors.append(f"第 {line_number} 行含 Excel 错误值")
        if not row[1] or not row[4]:
            errors.append(f"第 {line_number} 行缺候选人姓名或招聘岗位")
        cells = {SYSTEM_FIELDS[name]: value for name, value in zip(LEDGER_HEADERS, row) if value != ""}
        errors.extend(validate_cells(cells, catalog, f"ledger line {line_number}"))

    for key, count in keys.items():
        if count > 1:
            warnings.append(f"重复候选人：{key[0]} / {key[1]} / {key[2]} 出现 {count} 次")
    if len(hr_names) > 1:
        errors.append(f"个人台账出现多个 HR 姓名：{sorted(hr_names)}")

    interviews = read_csv(args.interviews)
    if not interviews:
        errors.append("面试明细为空")
    elif interviews[0] != INTERVIEW_HEADERS:
        errors.append(f"面试明细表头不一致：{interviews[0]}")
    interview_rows = interviews[1:] if len(interviews) > 1 else []
    for line_number, row in enumerate(interview_rows, start=2):
        if len(row) != len(INTERVIEW_HEADERS):
            errors.append(f"面试明细第 {line_number} 行列数 {len(row)}，应为 {len(INTERVIEW_HEADERS)}")
            continue
        if not row[0] or not row[3] or not row[4]:
            errors.append(f"面试明细第 {line_number} 行缺候选人/轮次/时间")
        if row[3] not in ROUND_RESULT_FIELDS:
            errors.append(f"面试明细第 {line_number} 行轮次异常：{row[3]}")
        elif row[6]:
            errors.extend(validate_cells(
                {ROUND_RESULT_FIELDS[row[3]]: row[6]}, catalog, f"interview line {line_number}"
            ))

    rec_by_name: dict[str, datetime] = {}
    for row in rows:
        if len(row) == len(LEDGER_HEADERS) and row[11]:
            parsed = parse_dt(row[11])
            if parsed:
                rec_by_name[row[1]] = parsed
    for line_number, row in enumerate(interview_rows, start=2):
        if len(row) != len(INTERVIEW_HEADERS):
            continue
        parsed = parse_dt(row[4])
        recommended = rec_by_name.get(row[0])
        if parsed and recommended and parsed < recommended:
            warnings.append(f"面试明细第 {line_number} 行面试时间早于推荐时间：{row[0]}")

    funnel_rows = 0
    if args.funnel:
        funnel = read_csv(args.funnel)
        if not funnel:
            errors.append("公开漏斗为空")
        else:
            if funnel[0] != FUNNEL_HEADERS:
                errors.append(f"公开漏斗表头不一致：{funnel[0]}")
            funnel_rows = max(0, len(funnel) - 1)
            forbidden = ("姓名", "手机号", "候选人", "面试评语", "最近任职公司", "上家任职职位")
            bad = [header for header in funnel[0] if any(word in header for word in forbidden)]
            if bad:
                errors.append(f"公开漏斗含候选人明细字段：{bad}")

    result = {
        "ledger_rows": len(rows),
        "interview_rows": len(interview_rows),
        "funnel_rows": funnel_rows,
        "hr_names": sorted(hr_names),
        "field_snapshot_count": len(catalog),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors and args.strict:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
