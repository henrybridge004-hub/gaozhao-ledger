from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import apply_stale_unevaluated_rule as stale
import build_ledger
import sync_process_fields as process
import sync_tmeet_minutes as tmeet
from field_rules import build_catalog, validate_cells

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=TZ)


def field(field_id, name, field_type="text", options=()):
    item = {"fieldId": field_id, "fieldName": name, "type": field_type}
    if options:
        item["config"] = {"options": [{"name": value} for value in options]}
    return item


def snapshot():
    fields = [
        field("MNkArlN", "候选人姓名"), field("dwQg9oA", "招聘岗位"),
        field("9Wf7gUD", "备注"), field("4iqUuLZ", "HR姓名", "member"),
        field("QIviPdN", "简历情况"), field("UUBlTiK", "简历初筛评价"),
        field("59ymyJZ", "电话沟通评价"), field("Vf5E9zp", "一面面试情况"),
        field("ioAkX6m", "面试综合评价"), field("g2vCkka", "面试面评汇总"),
        field("78MqIBw", "一面面评"), field("2Swql54", "二面面试情况"),
        field("wj2JA1l", "二面面评"), field("RTLxO9K", "三面面试情况"),
        field("DWPu6oG", "三面面评"), field("Yne7Zvj", "个人台账最新状态"),
        field("bZrNGjr", "一面面试时间", "date"), field("TKY0lvO", "二面面试时间", "date"),
        field("jZHCn4d", "三面面试时间", "date"), field("n5pJCfI", "一面原因"),
        field("TF6ydWI", "二面原因"), field("KPhawKu", "三面原因"),
        field("mwv1H5x", "一面面试结果", "singleSelect", ["通过", "未通过", "未评价", "部分评价"]),
        field("7NfUhqb", "二面面试结果", "singleSelect", ["通过", "未通过", "未评价"]),
        field("6n4KvRS", "三面面试结果", "singleSelect", ["通过", "未通过"]),
        field("rbYLcli", "Offer情况", "singleSelect", ["无", "未发offer", "已发offer", "拒绝offer", "接受offer", "录用审批中", "offer已接受（待入职）", "待入职"]),
        field("oWZ5bkr", "入职状态", "singleSelect", ["未入职", "待入职", "已入职", "放弃入职", "待入职（审批中）"]),
    ]
    return {"data": {"fields": fields}}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class FieldRuleTests(unittest.TestCase):
    def setUp(self):
        self.catalog = build_catalog(snapshot())

    def test_invalid_single_select_is_an_error(self):
        errors = validate_cells({"rbYLcli": "offer已拒绝"}, self.catalog)
        self.assertEqual(len(errors), 1)
        self.assertIn("not in", errors[0])

    def test_current_status_mapping_uses_real_options(self):
        offer_options = self.catalog["rbYLcli"]["option_names"]
        entry_options = self.catalog["oWZ5bkr"]["option_names"]
        for status in build_ledger.STATUS_TO_OFFER:
            self.assertIn(build_ledger.status_to_offer(status), offer_options)
            self.assertIn(build_ledger.status_to_onboard(status), entry_options)
        self.assertEqual(build_ledger.status_to_offer(999999), "")
        self.assertEqual(build_ledger.status_to_onboard(999999), "")

    def test_millisecond_timestamp_is_supported(self):
        self.assertTrue(build_ledger.fmt_ts(1793527200000, TZ).startswith("2026-"))

    def test_canceled_interview_is_excluded(self):
        item = {
            "resumeId": "r1", "applyJobId": "j1", "name": "测试候选人",
            "applyJobName": "测试岗位", "resumeLibraryStatus": 10,
        }
        stages = [{
            "resumeStageDesc": "面试阶段", "current": True,
            "stageActionLogs": [{
                "actionDesc": "安排面试", "businessTime": 1793527200,
                "interviewInfo": {
                    "interviewRoundName": "业务初试", "interviewTime": 1793527200,
                    "cancelReason": "候选人取消", "interviewerNames": "测试面试官",
                },
                "logItems": [{"resultStatusDesc": "未评价"}],
            }],
        }]
        row, feedback, audit = build_ledger.build_candidate(item, stages, {"hr_name": "测试HR"}, TZ)
        self.assertEqual(row[13], "")
        self.assertEqual(feedback, [])
        self.assertEqual(audit["interviews"], [])
        self.assertEqual(len(audit["canceled_interviews"]), 1)
        self.assertIn("已排除1场取消面试", row[-1])


class StaleRuleTests(unittest.TestCase):
    def setUp(self):
        self.catalog = build_catalog(snapshot())

    def record(self, offer="无", entry="未入职", note=""):
        return {
            "recordId": "r1",
            "cells": {
                "MNkArlN": "测试候选人", "dwQg9oA": "测试岗位",
                "bZrNGjr": "2026-11-01T10:00:00+08:00",
                "mwv1H5x": {"name": "未评价"},
                "Vf5E9zp": note,
                "rbYLcli": {"name": offer}, "oWZ5bkr": {"name": entry},
            },
        }

    def test_negative_offer_text_is_not_positive(self):
        self.assertFalse(stale.has_blocking_downstream("无offer", "未入职"))
        self.assertTrue(stale.has_blocking_downstream("拒绝offer", "未入职"))
        self.assertTrue(stale.has_blocking_downstream("无", "放弃入职"))

    def test_naive_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            stale.parse_time("2026-11-21T12:00:00")

    def test_negative_offer_is_not_accepted_as_valid_option(self):
        updates, _, skipped, _ = stale.evaluate_records(
            [self.record(offer="无offer")], self.catalog, NOW
        )
        self.assertEqual(updates, [])
        self.assertEqual(skipped[0]["reason"], "字段/枚举校验失败")

    def test_canceled_round_is_skipped(self):
        updates, _, skipped, _ = stale.evaluate_records(
            [self.record(note="本场面试已取消")], self.catalog, NOW
        )
        self.assertEqual(updates, [])
        self.assertIn("取消", skipped[0]["reason"])

    def test_exact_72_hours_does_not_trigger(self):
        record = self.record()
        exact_now = datetime.fromisoformat("2026-11-04T10:00:00+08:00")
        updates, _, skipped, _ = stale.evaluate_records([record], self.catalog, exact_now)
        self.assertEqual(updates, [])
        self.assertIn("未超过3天", skipped[0]["reason"])
        later = exact_now + timedelta(seconds=1)
        updates, _, _, _ = stale.evaluate_records([record], self.catalog, later)
        self.assertEqual(len(updates), 1)


class ProcessAndMinutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.fields_path = self.dir / "fields.json"
        write_json(self.fields_path, snapshot())

    def tearDown(self):
        self.temp.cleanup()

    def workbook(self):
        path = self.dir / "input.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.title = "人力管培"
        sheet.append(["姓名", "简历"])
        sheet.append(["测试候选人", "新内容"])
        book.save(path)
        return path

    def test_duplicate_name_aborts(self):
        records = {"data": {"records": [
            {"recordId": "r1", "cells": {"MNkArlN": "测试候选人"}},
            {"recordId": "r2", "cells": {"MNkArlN": "测试候选人"}},
        ]}}
        records_path = self.dir / "records.json"
        write_json(records_path, records)
        with self.assertRaisesRegex(ValueError, "Duplicate candidate names"):
            process.build_payloads(
                self.workbook(), self.fields_path, records_path, self.dir / "out",
                process.DEFAULT_MAPPING, "MNkArlN", "dwQg9oA", "9Wf7gUD", "4iqUuLZ",
                [{"userId": "test"}], None,
            )

    def test_nonempty_process_field_is_protected(self):
        records = {"data": {"records": [
            {"recordId": "r1", "cells": {"MNkArlN": "测试候选人", "QIviPdN": "人工内容"}},
        ]}}
        records_path = self.dir / "records.json"
        write_json(records_path, records)
        report = process.build_payloads(
            self.workbook(), self.fields_path, records_path, self.dir / "out",
            process.DEFAULT_MAPPING, "MNkArlN", "dwQg9oA", "9Wf7gUD", "4iqUuLZ",
            [{"userId": "test"}], None,
        )
        self.assertEqual(report["existing_records_to_update"], 0)
        self.assertEqual(report["conflict_count"], 1)

    def test_minutes_existing_content_is_protected(self):
        records = {"data": {"records": [{
            "recordId": "r1", "cells": {
                "MNkArlN": "测试候选人", "bZrNGjr": "2026-11-01T10:00:00+08:00",
                "Vf5E9zp": "人工纪要",
            },
        }]}}
        records_path = self.dir / "records.json"
        manifest_path = self.dir / "manifest.json"
        write_json(records_path, records)
        write_json(manifest_path, [{"name": "测试候选人", "recordId": "r1", "round": 1, "recordFileId": "m1"}])
        minutes_dir = self.dir / "minutes"
        minutes_dir.mkdir()
        write_json(minutes_dir / "m1.json", {"data": {"meeting_minute": {"minute": "新纪要"}}})
        report = tmeet.build_payload(
            manifest_path, minutes_dir, self.dir / "out", self.fields_path, records_path
        )
        self.assertEqual(report["records"], 0)
        self.assertEqual(report["conflict_count"], 1)


if __name__ == "__main__":
    unittest.main()
