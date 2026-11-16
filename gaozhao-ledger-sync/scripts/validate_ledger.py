# -*- coding: utf-8 -*-
"""Validate the generated 26-column ledger before writing to DingTalk."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

LEDGER_HEADERS = [
    "HR姓名", "候选人姓名", "来源渠道", "城市", "招聘岗位", "手机号",
    "最近任职公司", "上家任职职位", "薪资架构", "沟通备注", "HR沟通结果",
    "推荐简历时间", "简历推荐是否通过",
    "一轮面试时间", "未通过/未参加/考虑中具体原因（若未放弃无需填写）", "一轮面试结果",
    "二轮面试时间", "未通过/未参加/考虑中具体原因（若未放弃无需填写）", "二轮面试结果",
    "终面面试时间", "未通过/未参加/考虑中具体原因（若未放弃无需填写）", "终面面试结果",
    "offer情况", "入职状态", "入职时间", "备注",
]
INTERVIEW_HEADERS = [
    "候选人姓名", "HR", "招聘岗位", "面试轮次", "面试时间", "面试官",
    "面试结果", "评分", "面试评语", "能力项评分", "数据状态",
]
FUNNEL_HEADERS = [
    "HR", "周期", "接收简历", "推荐", "业务复筛通过", "安排面试",
    "实际面试", "面试通过", "offer", "待入职", "入职", "points",
]


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


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
    parser.add_argument("--funnel", type=Path, help="公开漏斗 CSV；提供时检查是否混入候选人明细")
    parser.add_argument("--strict", action="store_true", help="有 error 时返回非 0")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    ledger = read_csv(args.ledger)
    if not ledger:
        errors.append("台账为空")
    else:
        if ledger[0] != LEDGER_HEADERS:
            errors.append(f"26 列表头不一致：{ledger[0]}")
        if len(ledger) < 2:
            warnings.append("台账只有表头，没有数据行")

    rows = ledger[1:] if len(ledger) > 1 else []
    keys = Counter()
    hr_names = set()
    for i, row in enumerate(rows, start=2):
        if len(row) != len(LEDGER_HEADERS):
            errors.append(f"第 {i} 行列数 {len(row)}，应为 {len(LEDGER_HEADERS)}")
            continue
        hr_names.add(row[0])
        keys[(row[1], row[5], row[4])] += 1
        if "#REF!" in ",".join(row) or "#N/A" in ",".join(row):
            errors.append(f"第 {i} 行含 Excel 错误值")
        if not row[1] or not row[4]:
            errors.append(f"第 {i} 行缺候选人姓名或招聘岗位")

    for key, count in keys.items():
        if count > 1:
            warnings.append(f"重复候选人：{key[0]} / {key[1]} / {key[2]} 出现 {count} 次")

    if len(hr_names) > 1:
        errors.append(f"个人台账出现多个 HR 姓名：{sorted(hr_names)}")

    interviews = read_csv(args.interviews)
    if not interviews:
        errors.append("面试明细为空")
    else:
        if interviews[0] != INTERVIEW_HEADERS:
            errors.append(f"面试明细表头不一致：{interviews[0]}")
    for i, row in enumerate(interviews[1:] if len(interviews) > 1 else [], start=2):
        if len(row) != len(INTERVIEW_HEADERS):
            errors.append(f"面试明细第 {i} 行列数 {len(row)}，应为 {len(INTERVIEW_HEADERS)}")
            continue
        if not row[0] or not row[3] or not row[4]:
            errors.append(f"面试明细第 {i} 行缺候选人/轮次/时间")
        if row[3] not in ("一轮", "二轮", "终面"):
            warnings.append(f"面试明细第 {i} 行轮次异常：{row[3]}")
        if row[6] not in ("通过", "未通过", "部分评价", "未评价", "邀约待确认"):
            warnings.append(f"面试明细第 {i} 行结果异常：{row[6]}")

    # Interview time should not predate recommendation time for the same candidate.
    rec_by_name: dict[str, datetime] = {}
    for row in rows:
        if len(row) == len(LEDGER_HEADERS) and row[11]:
            dt = parse_dt(row[11])
            if dt:
                rec_by_name[row[1]] = dt
    for i, row in enumerate(interviews[1:] if len(interviews) > 1 else [], start=2):
        if len(row) != len(INTERVIEW_HEADERS):
            continue
        dt = parse_dt(row[4])
        rec = rec_by_name.get(row[0])
        if dt and rec and dt < rec:
            warnings.append(f"面试明细第 {i} 行面试时间早于推荐时间：{row[0]}")

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
            bad = [h for h in funnel[0] if any(word in h for word in forbidden)]
            if bad:
                errors.append(f"公开漏斗含候选人明细字段：{bad}")

    result = {
        "ledger_rows": len(rows),
        "interview_rows": max(0, len(interviews) - 1),
        "funnel_rows": funnel_rows,
        "hr_names": sorted(hr_names),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors and args.strict:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
