# 个人过程台账同步流程

该流程用于把 HR 个人 Excel 中的简历、电话沟通和面试过程字段同步到钉钉 AI 表格，不替代官方系统字段自动同步。

## 1. 回读钉钉结构和记录

```powershell
dws aitable table get `
  --base-id <base_id> `
  --table-ids <ledger_table_id> `
  --format json | Set-Content -Encoding utf8 table.json

dws aitable record list `
  --base-id <base_id> `
  --table-id <ledger_table_id> `
  --limit 100 `
  --format json | Set-Content -Encoding utf8 records.json
```

记录超过 100 条时，按 CLI 返回的 cursor 继续分页，合并后再生成 payload。

## 2. 生成 upsert 载荷

```powershell
python gaozhao-ledger-sync/scripts/sync_process_fields.py `
  --input ./personal_ledger.xlsx `
  --table-json ./table.json `
  --records-json ./records.json `
  --out-dir ./out `
  --hr-value-json ./hr_value.json `
  --resume-basic-json ./resume_basic.json
```

`resume-basic-json` 可省略。它只在 Excel 没有“简历情况”且钉钉目标字段为空时作为本地结构化摘要来源；没有数据权限时不要伪造。

安全边界：

- 表内出现重名候选人时脚本直接中止，不猜测更新对象。
- 只要有新建记录，就必须显式传入 `--hr-value-json`；不得从现有行的多数 HR 推断。
- 非空目标字段默认受保护；内容不一致写入 `conflicts`，不生成该字段更新。
- 只有逐项确认冲突后，才可显式增加 `--allow-nonempty-overwrite`。
- 生成的载荷会按最新字段快照和实时 singleSelect 选项再次校验。

输出文件：

- `process_updates.json`：已存在候选人的字段更新。
- `process_creates.json`：未匹配候选人的新建记录；新建必须显式传入 `--hr-value-json`。
- `process_sync_report.json`：聚合同步报告，包含冲突数量；非空字段冲突不会被静默覆盖。

## 3. 先 dry-run

```powershell
dws aitable record update `
  --base-id <base_id> `
  --table-id <ledger_table_id> `
  --records-file ./out/process_updates.json `
  --dry-run

dws aitable record create `
  --base-id <base_id> `
  --table-id <ledger_table_id> `
  --records-file ./out/process_creates.json `
  --dry-run
```

## 4. 正式写入

```powershell
dws aitable record update `
  --base-id <base_id> `
  --table-id <ledger_table_id> `
  --records-file ./out/process_updates.json `
  --yes

dws aitable record create `
  --base-id <base_id> `
  --table-id <ledger_table_id> `
  --records-file ./out/process_creates.json `
  --yes
```

每批最多 100 条。先更新后新建，可减少同一轮同步中的重复匹配。

## 5. 回读验收

再次执行 table get 和 record list，检查：

1. 12 个过程字段均存在且类型为 text。
2. 上传 Excel 中的每个候选人都能匹配到记录。
3. 所有非空 Excel 单元格与钉钉记录一致。
4. 表内没有重名候选人。
5. 未确认岗位保持待补，不根据面试文本推断。

公开仓库只提交字段口径、脚本和聚合报告，不提交个人 Excel、完整手机号、简历详情、Cookie、token 或本地配置。
