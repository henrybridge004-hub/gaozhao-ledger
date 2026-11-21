# -*- coding: utf-8 -*-
"""Build the system-field GaoZhao ledger from Xinrenxinshi raw JSON.

Inputs:
  --resume-list  getResumeList response JSON
  --stage-info   {resumeId: [stages...]} JSON captured from browser XHR
  --config       config.json (see assets/config.example.json)
  --out-dir      output directory

Outputs:
  ledger_system_fields.csv
  interview_feedback.csv
  funnel_by_hr.csv
  sync_report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def pick_list(obj: Any) -> list[dict]:
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        return []
    data = obj.get("data", obj)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "list", "records", "items", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def load_stage_map(path: Path) -> dict[str, list[dict]]:
    obj = load_json(path)
    if isinstance(obj, dict):
        if isinstance(obj.get("data"), dict):
            obj = obj["data"]
        if all(isinstance(v, list) for v in obj.values()):
            return {str(k): v for k, v in obj.items()}
        for key in ("stageInfo", "stage_info", "list", "records"):
            value = obj.get(key)
            if isinstance(value, dict) and all(isinstance(v, list) for v in value.values()):
                return {str(k): v for k, v in value.items()}
    if isinstance(obj, list):
        out = {}
        for item in obj:
            if not isinstance(item, dict):
                continue
            rid = item.get("resumeId") or item.get("id")
            stages = item.get("stages") or item.get("stageInfo") or item.get("data")
            if rid and isinstance(stages, list):
                out[str(rid)] = stages
        return out
    return {}


def tz_from_config(config: dict) -> timezone:
    name = config.get("timezone", "Asia/Shanghai")
    if name == "Asia/Shanghai":
        return timezone(timedelta(hours=8))
    return timezone.utc


def fmt_ts(value: Any, tz: timezone) -> str:
    if value is None or value == "" or value == 0 or value == "0":
        return ""
    if isinstance(value, str):
        return value
    try:
        timestamp = int(value)
        if abs(timestamp) >= 100_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


def time_reached(value: str, now: datetime) -> bool:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=now.tzinfo)
    except (TypeError, ValueError):
        return False
    return parsed <= now


def mask_mobile(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "*" in text:
        return text
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 11:
        return f"{digits[:3]}****{digits[-4:]}"
    return text


def clean_remark(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("备注："):
        text = text[3:].strip()
    return text


def to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_screen(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"已通过", "通过", "pass", "1"}:
        return "通过"
    if text in {"未通过", "不通过", "fail", "2"}:
        return "不通过"
    if text in {"未反馈", "未评价", "待反馈", "0", ""}:
        return "未反馈"
    if text in {"部分反馈", "部分评价"}:
        return "部分反馈"
    return text


def screen_from_log(log: dict) -> str:
    """Business-screen result from the recommendation log and its reviewers."""
    statuses = []
    if log.get("resultStatusDesc"):
        statuses.append(str(log["resultStatusDesc"]))
    for item in log.get("logItems") or []:
        if isinstance(item, dict) and item.get("resultStatusDesc"):
            statuses.append(str(item["resultStatusDesc"]))
    normalized = [normalize_screen(s) for s in statuses]
    if any(s == "不通过" for s in normalized):
        return "不通过"
    if any(s == "通过" for s in normalized):
        if any(s == "未反馈" for s in normalized):
            return "部分反馈"
        return "通过"
    if any(s == "部分反馈" for s in normalized):
        return "部分反馈"
    return "未反馈"


def parse_judgement(item: dict) -> list[str]:
    expand = item.get("expand") or {}
    raw = expand.get("judgement") if isinstance(expand, dict) else None
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == 4 and entry.get("labelName") and entry.get("value"):
            out.append(f"{entry['labelName']}: {entry['value']}")
        elif entry.get("type") == 2 and entry.get("labelName") and entry.get("value"):
            out.append(f"{entry['labelName']}: {entry['value']}")
    return out


def interview_from_log(log: dict, stage_name: str, tz: timezone) -> dict:
    info = log.get("interviewInfo") or {}
    items = [x for x in (log.get("logItems") or []) if isinstance(x, dict)]
    statuses = [str(x.get("resultStatusDesc") or "") for x in items]
    comments = [str(x.get("resultComment") or "").strip() for x in items if str(x.get("resultComment") or "").strip()]
    scores = [str(x.get("resultScore")) for x in items if x.get("resultScore") not in (None, "")]
    operators = [str(x.get("operator") or "").strip() for x in items if str(x.get("operator") or "").strip()]
    abilities = []
    for item in items:
        for ability in parse_judgement(item):
            if ability not in abilities:
                abilities.append(ability)

    has_pass = any("通过" in s and "未" not in s for s in statuses)
    has_fail = any("未通过" in s for s in statuses)
    has_unrated = any("未评价" in s or "未反馈" in s for s in statuses)
    has_content = bool(comments or scores)

    if has_pass and (has_fail or has_unrated):
        result = "部分评价"
    elif has_fail and has_unrated:
        result = "部分评价"
    elif has_pass:
        result = "通过"
    elif has_fail:
        result = "未通过"
    elif has_content:
        result = "部分评价"
    else:
        result = "未评价"

    if not has_content and not has_pass and not has_fail:
        data_status = "未评价"
    elif has_unrated:
        data_status = "部分评价"
    else:
        data_status = "已评价"

    score_text = ""
    if scores:
        unique_scores = []
        for s in scores:
            if s not in unique_scores:
                unique_scores.append(s)
        score_text = " / ".join(f"{s}/5" if "/" not in s else s for s in unique_scores)

    comment_text = ""
    if comments:
        if len(comments) == 1:
            comment_text = comments[0]
        else:
            parts = []
            for item in items:
                c = str(item.get("resultComment") or "").strip()
                op = str(item.get("operator") or "").strip()
                if c:
                    parts.append(f"{op}：{c}" if op else c)
            comment_text = "\n\n".join(parts)

    interviewer = "、".join(dict.fromkeys(operators))
    if not interviewer:
        interviewer = str(info.get("interviewerNames") or "").strip()

    return {
        "stage": stage_name,
        "raw_round": str(info.get("interviewRoundName") or ""),
        "time": info.get("interviewTime") or log.get("businessTime"),
        "time_text": fmt_ts(info.get("interviewTime") or log.get("businessTime"), tz),
        "operate_time": fmt_ts(log.get("operateTime"), tz),
        "interviewer": interviewer,
        "result": result,
        "score": score_text,
        "comment": comment_text,
        "ability": "；".join(abilities),
        "data_status": data_status,
        "raw_operators": operators,
        "canceled": bool(info.get("cancelReason") or log.get("cancelReason")),
    }


def effective_rounds(interviews: list[dict]) -> list[dict]:
    """Map raw rounds to first/second/third, including the 'stuck at first round' case."""
    ordered = sorted(interviews, key=lambda x: str(x.get("time") or ""))
    # Mark a second '业务面试-初试' on the same 一面 stage as actual second round.
    for i, current in enumerate(ordered):
        if "初试" not in current["raw_round"]:
            continue
        if "一面" not in current["stage"]:
            continue
        previous = [x for x in ordered[:i] if "初试" in x["raw_round"] and "一面" in x["stage"]]
        if not previous:
            continue
        prev = previous[-1]
        if current.get("canceled") or prev.get("canceled"):
            continue
        if not current.get("raw_operators") or not prev.get("raw_operators"):
            continue
        if set(current["raw_operators"]) == set(prev["raw_operators"]):
            continue
        if prev.get("data_status") == "已评价":
            continue
        current["effective_round"] = "二面"
        current["mapped_note"] = "系统仍挂一面，按业务实际映射二面"

    for item in ordered:
        if item.get("effective_round"):
            continue
        raw = item["raw_round"]
        stage = item["stage"]
        if "初试" in raw:
            item["effective_round"] = "一面"
        elif "复试" in raw:
            item["effective_round"] = "二面"
        elif "终试" in raw or "三面" in raw:
            item["effective_round"] = "三面"
        elif "HR" in raw or "HRBP" in raw:
            item["effective_round"] = "三面"
        elif "二面" in stage:
            item["effective_round"] = "二面"
        elif "三面" in stage:
            item["effective_round"] = "三面"
        else:
            item["effective_round"] = "一面"
    return ordered


# Values are restricted to the current DingTalk singleSelect options. Source
# states without an exact business equivalent stay blank and go to the report.
STATUS_TO_OFFER = {
    6: "接受offer", 7: "接受offer", 8: "接受offer", 9: "无",
    10: "无", 11: "无", 12: "无", 13: "无", 14: "无",
    30: "已发offer", 31: "接受offer", 32: "未发offer",
    33: "拒绝offer", 34: "接受offer", 37: "未发offer",
    50: "待入职", 52: "待入职",
    60: "录用审批中", 61: "未发offer", 62: "未发offer",
    2000: "无", 2001: "无", 2002: "无", 2003: "无", 2004: "无",
}
STATUS_TO_ONBOARD = {
    6: "已入职", 7: "已入职", 34: "已入职",
    50: "待入职", 60: "待入职（审批中）",
    **{status: "未入职" for status in (8, 9, 10, 11, 12, 13, 14, 30, 31, 32, 33, 37, 52, 61, 62, 2000, 2001, 2002, 2003, 2004)},
}
STATUS_DETAIL = {
    8: "源系统已离职；钉钉入职状态按未入职记录",
    9: "源系统已归档",
    11: "源系统待定",
    30: "offer待确认",
    32: "offer已过期",
    52: "待入职已过期",
    61: "offer审批通过，尚未确认已发送",
    62: "录用审批未通过",
}


def status_to_offer(status: int) -> str:
    return STATUS_TO_OFFER.get(status, "")


def status_to_onboard(status: int) -> str:
    return STATUS_TO_ONBOARD.get(status, "")


def find_recommend_log(stages: list[dict]) -> dict | None:
    for stage in stages:
        for log in stage.get("stageActionLogs") or []:
            if "推荐" in str(log.get("actionDesc") or ""):
                return log
    return None


def all_interviews(stages: list[dict], tz: timezone) -> list[dict]:
    out = []
    for stage in stages:
        for log in stage.get("stageActionLogs") or []:
            if "安排面试" in str(log.get("actionDesc") or ""):
                out.append(interview_from_log(log, str(stage.get("resumeStageDesc") or ""), tz))
    return out


def build_candidate(item: dict, stages: list[dict], config: dict, tz: timezone) -> tuple[list, list[dict], dict]:
    hr_name = str(config.get("hr_name") or "")
    status = to_int(item.get("resumeLibraryStatus"))
    apply_job_id = str(item.get("applyJobId") or "")
    recommend_log = find_recommend_log(stages)
    rec_time = fmt_ts(recommend_log.get("operateTime"), tz) if recommend_log else ""
    rec_remark = clean_remark(recommend_log.get("actionRemark")) if recommend_log else ""
    screen = screen_from_log(recommend_log) if recommend_log else "未推荐"

    interviews_all = all_interviews(stages, tz)
    canceled_interviews = [item for item in interviews_all if item.get("canceled")]
    interviews = effective_rounds([item for item in interviews_all if not item.get("canceled")])
    current_stage = ""
    for stage in stages:
        if stage.get("current"):
            current_stage = str(stage.get("resumeStageDesc") or "")
            break
    by_round: dict[str, dict] = {}
    for iv in interviews:
        slot = iv["effective_round"]
        if slot not in by_round or str(iv.get("time") or "") > str(by_round[slot].get("time") or ""):
            by_round[slot] = iv

    salary = str(item.get("lastSalary") or "").strip()
    expect = str(item.get("expectSalary") or "").strip()
    if salary and expect:
        salary_text = f"上一份{salary}；期望{expect}"
    elif salary:
        salary_text = f"上一份{salary}"
    elif expect:
        salary_text = f"期望{expect}"
    else:
        salary_text = ""

    if recommend_log:
        note = "按 jobOwners 口径纳入"
        comm_note = rec_remark or "已推荐"
        hr_result = screen if screen != "未反馈" else "未反馈"
        rec_pass = screen
    else:
        note = "按 jobOwners 口径纳入；系统无推荐记录"
        comm_note = "未走推荐，直接安排面试"
        hr_result = "未记录（无推荐/复筛）"
        rec_pass = "未推荐"

    if status in (50, 52):
        note += "；系统状态待入职，实际入职状态待招聘运营更新"
    if "入职" in current_stage and status not in (6, 7, 34, 50, 52):
        note += f"；状态待复核（currentStage={current_stage}，resumeLibraryStatus={status}）"
    if status in STATUS_DETAIL:
        note += f"；{STATUS_DETAIL[status]}"
    status_unmapped = status not in STATUS_TO_OFFER or status not in STATUS_TO_ONBOARD
    if status_unmapped:
        note += f"；resumeLibraryStatus={status}无已确认映射，Offer/入职字段留空待复核"
    if canceled_interviews:
        note += f"；已排除{len(canceled_interviews)}场取消面试"

    one = by_round.get("一面", {})
    two = by_round.get("二面", {})
    final = by_round.get("三面", {})

    row = [
        hr_name,
        str(item.get("name") or ""),
        str(item.get("channelDesc") or ""),
        str(item.get("workCity") or ""),
        str(item.get("applyJobName") or ""),
        mask_mobile(item.get("mobile")),
        str(item.get("lastCompany") or ""),
        str(item.get("lastJob") or ""),
        salary_text,
        comm_note,
        hr_result,
        rec_time,
        rec_pass,
        one.get("time_text", ""),
        "",
        one.get("result", ""),
        two.get("time_text", ""),
        "",
        two.get("result", ""),
        final.get("time_text", ""),
        "",
        final.get("result", ""),
        status_to_offer(status),
        status_to_onboard(status),
        "",
        note,
    ]

    feedback = []
    for iv in interviews:
        feedback.append([
            str(item.get("name") or ""),
            hr_name,
            str(item.get("applyJobName") or ""),
            iv["effective_round"],
            iv["time_text"],
            iv["interviewer"],
            iv["result"],
            iv["score"],
            iv["comment"],
            iv["ability"],
            iv["data_status"],
        ])

    audit = {
        "resumeId": item.get("resumeId"),
        "applyJobId": apply_job_id,
        "name": item.get("name"),
        "recommended": bool(recommend_log),
        "screen": screen,
        "interviews": interviews,
        "canceled_interviews": canceled_interviews,
        "status": status,
        "status_unmapped": status_unmapped,
        "salary_missing": not salary and not expect,
        "stage_type": item.get("stageTypeDesc"),
        "current_stage": current_stage,
    }
    return row, feedback, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-list", required=True, type=Path)
    parser.add_argument("--stage-info", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    config = load_json(args.config)
    tz = tz_from_config(config)
    candidates = pick_list(load_json(args.resume_list))
    stage_map = load_stage_map(args.stage_info)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ledger_rows = []
    feedback_rows = []
    audits = []
    missing_stage = []
    duplicates = Counter()

    for item in candidates:
        rid = str(item.get("resumeId") or "")
        stages = stage_map.get(rid) or []
        if not stages:
            missing_stage.append(rid)
        row, feedback, audit = build_candidate(item, stages, config, tz)
        key = (str(item.get("name") or ""), mask_mobile(item.get("mobile")), str(item.get("applyJobName") or ""))
        duplicates[key] += 1
        ledger_rows.append(row)
        feedback_rows.extend(feedback)
        audits.append(audit)

    with (out / "ledger_system_fields.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(LEDGER_HEADERS)
        writer.writerows(ledger_rows)

    with (out / "interview_feedback.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(INTERVIEW_HEADERS)
        writer.writerows(feedback_rows)

    # Funnel: one HR row; only aggregates, no candidate detail.
    hr_name = str(config.get("hr_name") or "")
    now = datetime.now(tz)
    received = len(ledger_rows)
    recommended = sum(1 for a in audits if a["recommended"])
    screen_pass = sum(1 for a in audits if a["screen"] == "通过")
    interview_scheduled = sum(1 for a in audits if a["interviews"])
    interviewed = 0
    interview_passed = 0
    offer = 0
    onboard = 0
    for a in audits:
        if any(time_reached(str(i.get("time_text") or ""), now) for i in a["interviews"]):
            interviewed += 1
        if any(i.get("result") == "通过" for i in a["interviews"]):
            interview_passed += 1
        if a["status"] in (30, 31, 34, 37, 50, 60, 61):
            offer += 1
        if a["status"] in (6, 7, 34):
            onboard += 1

    score_rules = config.get("score_rules") or {}
    points = 0
    for a in audits:
        if a["recommended"]:
            points += int(score_rules.get("recommend", 0) or 0)
        if a["screen"] == "通过":
            points += int(score_rules.get("screen_pass", 0) or 0)
        if a["interviews"]:
            points += int(score_rules.get("interview_scheduled", 0) or 0)
        if any(i.get("result") == "通过" for i in a["interviews"]):
            points += int(score_rules.get("interview_passed", 0) or 0)
        if a["status"] in (30, 31, 34, 37, 50, 60, 61):
            points += int(score_rules.get("offer", 0) or 0)
        if a["status"] in (6, 7, 34):
            points += int(score_rules.get("onboard", 0) or 0)

    with (out / "funnel_by_hr.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FUNNEL_HEADERS)
        writer.writerow([hr_name, "rolling_30d", received, recommended, screen_pass, interview_scheduled, interviewed, interview_passed, offer, sum(1 for a in audits if a["status"] in (50, 52)), onboard, points])

    duplicate_list = [
        {"name": k[0], "mobile": k[1], "job": k[2], "count": v}
        for k, v in duplicates.items() if v > 1
    ]
    unrated = sum(1 for a in audits for i in a["interviews"] if i.get("data_status") == "未评价")
    status_conflicts = [
        {"resumeId": a["resumeId"], "name": a["name"], "status": a["status"], "current_stage": a.get("current_stage")}
        for a in audits if a["status"] == 9 and "入职" in str(a.get("current_stage", ""))
    ]
    unresolved_statuses = [
        {"resumeId": a["resumeId"], "name": a["name"], "status": a["status"]}
        for a in audits if a.get("status_unmapped")
    ]

    report = {
        "hr_name": hr_name,
        "candidate_rows": len(ledger_rows),
        "interview_rows": len(feedback_rows),
        "recommended": recommended,
        "screen_pass": screen_pass,
        "interview_scheduled": interview_scheduled,
        "interviewed": interviewed,
        "interview_passed": interview_passed,
        "offer": offer,
        "onboard": onboard,
        "points": points,
        "missing_stage": missing_stage,
        "duplicate_keys": duplicate_list,
        "unrated_interviews": unrated,
        "status_conflicts": status_conflicts,
        "unresolved_statuses": unresolved_statuses,
        "canceled_interviews_excluded": sum(len(a.get("canceled_interviews") or []) for a in audits),
        "salary_missing_count": sum(1 for a in audits if a.get("salary_missing")),
        "not_recommended": sum(1 for a in audits if not a["recommended"]),
        "audit": audits,
    }
    if report["missing_stage"]:
        report["warning"] = "部分 resumeId 没有 stage-info，面试/推荐字段可能为空"
    with (out / "sync_report.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps({k: v for k, v in report.items() if k != "audit"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
