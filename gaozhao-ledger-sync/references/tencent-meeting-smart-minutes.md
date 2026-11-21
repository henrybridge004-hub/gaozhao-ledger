# 腾讯会议智能纪要同步

该流程用于把腾讯会议中已生成的面试智能纪要同步到钉钉 AI 表。智能纪要只写入对应轮次的“面试情况”字段，不替代官方面试结果。

## 字段映射

| 面试轮次 | 钉钉字段 | fieldId |
|---|---|---|
| 一面 | 一面面试情况 | `Vf5E9zp` |
| 二面 | 二面面试情况 | `2Swql54` |
| 三面 | 三面面试情况 | `RTLxO9K` |

写入时统一增加来源前缀：`腾讯会议智能纪要：`。

## 1. 检查 CLI 登录

```powershell
tmeet auth status
```

未登录或登录到错误企业时，先退出再重新授权：

```powershell
tmeet auth logout
tmeet auth login
```

授权页面必须选择正确的企业微信/企业身份。网页登录和 CLI 授权是两套会话，不能互相替代。

## 2. 搜索候选人录制

```powershell
tmeet record search `
  --query "<候选人姓名>" `
  --query-field all `
  --start "<面试日开始时间>" `
  --end "<面试日结束时间>" `
  --format json
```

重点检查：

- `has_smart_minutes=true`
- `record_file_id`
- `meeting_code`
- `record_start_time`、`record_end_time`
- snippets 中是否出现候选人姓名和智能纪要片段

对外只使用会议码，不暴露内部会议 ID。

## 3. 获取智能纪要

```powershell
tmeet record smart-minutes `
  --record-file-id "<record_file_id>" `
  --format json | Set-Content -Encoding utf8 ./minutes/<record_file_id>.json
```

只有录制已处理完成且当前账号有权限时，才能获取纪要。权限不足时走正式权限申请，不绕过访问控制。

## 4. 编写 manifest

```json
[
  {
    "name": "<候选人姓名>",
    "recordId": "<钉钉记录ID>",
    "round": 1,
    "recordFileId": "<腾讯会议录制文件ID>"
  }
]
```

`round` 仅支持 1、2、3。钉钉记录 ID 应来自最新一次 `dws aitable record list`，不要使用过期文件。

## 5. 生成钉钉更新载荷

```powershell
python gaozhao-ledger-sync/scripts/sync_tmeet_minutes.py `
  --manifest ./tmeet_manifest.json `
  --minutes-dir ./minutes `
  --table-json ./fields.json `
  --records-json ./records.json `
  --out-dir ./out
```

输出：

- `tmeet_minutes_updates.json`
- `tmeet_minutes_report.json`：包含冲突和未变化记录。

脚本会核对 manifest 字段完整性、重复目标、最新 recordId、候选人姓名、轮次和对应面试时间。目标“面试情况”已有不同内容时默认进入冲突清单，不生成覆盖；只有人工确认后才显式增加 `--allow-nonempty-overwrite`。

## 6. dry-run 后写入

```powershell
dws aitable record update `
  --base-id <base_id> `
  --table-id <ledger_table_id> `
  --records-file ./out/tmeet_minutes_updates.json `
  --dry-run

dws aitable record update `
  --base-id <base_id> `
  --table-id <ledger_table_id> `
  --records-file ./out/tmeet_minutes_updates.json `
  --yes
```

## 7. 回读验收

1. 重新执行 `dws aitable record list`。
2. 按 recordId 核对每个字段内容与生成载荷完全一致。
3. 确认官方“一面/二面/三面面试结果”没有被智能纪要改写。
4. 若同一候选人存在多个相似会议，以会议时间、候选人和 snippets 共同确认后再写入。

公开仓库不得提交智能纪要原文、逐字稿、个人 Excel、手机号、邮箱、会议内部 ID、Cookie、token 或本地配置。
