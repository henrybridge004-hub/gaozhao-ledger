---
name: gaozhao-ledger-sync
description: 高招台账自动同步：从薪人薪事按 jobOwners 拉取候选人与面试流程，生成标准个人台账、面试反馈明细、公开漏斗和团队看板，并更新钉钉 AI 表格；支持把个人 Excel 中的 12 个简历/面试过程字段、腾讯会议智能纪要同步到钉钉。适用于首次搭建高招台账、每日增量同步、补历史数据、核对台账口径、配置“个人明细互相不可见但漏斗公开排名”，以及让其他 HR 的 AI 复用同一套登录、去重、状态更新和定时任务流程。
---

# 高招台账自动同步

## What this skill does

把薪人薪事招聘数据整理成 HRD 可用的高招台账，并保持 fieldId、记录和单元格数据稳定：

1. **个人台账**：38 个标准字段，一人一行；候选人明细只对本人、HRD、招聘运营可见。
2. **面试反馈明细**：一场面试一行，保留面试官、结果、评分、评语、能力项。
3. **公开漏斗/团队看板**：只放人数、场次、转化率、点数和排名，不放候选人明细。
4. **全量与增量同步**：首次建立基线；每日按状态文件跳过未变化记录，更新同一行而不是重复创建。
5. **个人过程字段同步**：12 个文本字段承接个人 Excel 中的简历、电话沟通和各轮面试过程信息。
6. **腾讯会议智能纪要同步**：通过腾讯会议 CLI 获取已处理完成的智能纪要，写入对应轮次的面试情况字段。
7. **超时未评价治理**：最后一轮面试“未评价”超过 3 天且无后续面试时，仅把该轮结果改为“未通过”。

## Non-negotiables

- **38 个标准字段按业务流程展示**：基础信息 → 简历/沟通 → 一面 → 二面 → 三面 → 汇总 → Offer/入职 → 备注；完整 fieldId 和顺序以 `references/field-mapping.md` 为准。
- **12 个过程字段不替代官方结果字段**；字段名、fieldId 和来源映射以 `references/process-field-mapping.md` 为准。
- **腾讯会议智能纪要只写面试情况字段，不改官方面试结果**；同步口径以 `references/tencent-meeting-smart-minutes.md` 为准。
- **超时未评价只改最后一轮结果字段**：严格超过 72 小时、无后续面试且无积极下游状态时改为“未通过”，不自动补原因或面评。
- **HR 姓名取 `jobOwners` 当前负责人**，不要只取 `recommendHR`。
- **个人明细不进公开漏斗**；公开漏斗只允许聚合数字。
- **不整表覆盖**：按 `resumeId + applyJobId` 幂等 upsert；历史记录没有外部 ID 时用“姓名 + 手机号 + 岗位”兜底。
- **不采信单一状态字段**：以 `resumeLibraryStatus + 当前投递阶段 + 流程日志` 交叉核对。
- **不编造面评/面试官**：没有填写就写“未评价”。
- **不把密码、Cookie、token 写进配置、日志、回复或 GitHub**。

## Inputs

复制 `assets/config.example.json` 为 `config.json`，至少填写：

- `hr_name`、`owner_id`、`timezone`。
- `sync_state_file`：默认 `./sync_state.json`。
- `full_crawl`：首次全量回填的显式起止日期。
- `incremental`：每日滚动窗口和详情抓取策略；默认最近 30 天、只抓变化详情。
- `dingtalk`：`base_id`、`ledger_table_id`、`weekly_table_id`、`dashboard_id` 和对应 URL。
- `score_rules`：HRD 未确认点数权重前全部保留 0。
- `dry_run`：首次必须为 `true`。

## Mode decision

1. 加载 config 和状态文件；状态文件不存在或没有成功基线时，强制走**全量模式**。
2. 全量模式：拉取显式时间范围内全部列表和详情，建立 `resumeId + applyJobId -> dingtalk recordId` 映射。
3. 增量模式：每日仍拉最近 30 天列表，但只对新增/变化记录拉 stage-info、更新变化字段。
4. 周期校验：建议每周用 90 天窗口复核漏抓和状态冲突。

详细机制见 `references/sync-state.md`。

## Workflow

### 1. Preflight

- 读取 `config.json`、状态文件和钉钉表头，确认 38 个标准字段和默认视图列顺序。
- 用 `dws aitable field get` 保存最新字段快照；所有生成载荷先按 fieldId、fieldName 和实时 singleSelect 选项校验。
- 配置模板只含占位符，正式 Base/表/看板 ID 必须显式填写，禁止沿用其他 HR 的生产资源。
- 检查钉钉 `dws auth status`、薪人薪事 MCP 和内置浏览器登录态。
- 登录失效时停止写入，让用户在内置浏览器完成登录；不要用旧缓存冒充当天数据。
- `dry_run=true` 时只产出 CSV/报告，不写钉钉。

### 2. Pull candidate list

优先用薪人薪事 MCP 的候选人列表接口（实际工具名以当前环境 `tool_search` 为准）：

- 过滤 `jobOwners`，`type=2`，`values` 放 `{"value": owner_id}`。
- 加时间窗口；分页拉全，不要只取第一页。
- 只取需要的字段，避免大响应。

### 3. Pull stage/evaluation detail

- 全量模式：对范围内所有记录拉 stage-info。
- 增量模式：只对新增、列表哈希变化、状态变化或失败重试的记录拉详情。
- 浏览器详情接口必须在已登录的 `s.xinrenxinshi.com` 页面内用同步 XHR 调用；不要用不带 Cookie 的外部 HTTP 请求。

### 4. Build and validate

```powershell
python scripts/build_ledger.py `
  --resume-list ./raw/resume_list.json `
  --stage-info ./raw/stage_info.json `
  --config ./config.json `
  --out-dir ./out
python scripts/validate_ledger.py `
  --ledger ./out/ledger_system_fields.csv `
  --interviews ./out/interview_feedback.csv `
  --funnel ./out/funnel_by_hr.csv `
  --fields-json ./raw/fields.json `
  --strict
```

必须确认标准表头一致、业务键不重复、状态映射可解释、公开漏斗不含候选人明细。

### 5. Upsert to DingTalk AI table

1. 查询钉钉现有记录和状态文件中的 recordId 映射。
2. 按内容哈希拆成新增、更新、未变化三组。
3. 新增记录批量 create，已有记录按 recordId update；每批最多 100 条。
4. 成功后把 recordId、内容哈希和写入时间保存到状态文件。
5. 失败记录保留在失败队列，下次重试；不重复提交已成功记录。

### 6. Sync personal process fields

- 回读最新表结构和记录，使用 `scripts/sync_process_fields.py` 从个人 Excel 生成 process update/create 载荷。
- 表内重名直接中止；新建记录必须显式传入 `--hr-value-json`，不得从其他行推断 HR。
- 非空目标字段默认进入冲突清单，不覆盖；只有人工确认差异后才允许显式使用 `--allow-nonempty-overwrite`。
- 先分别执行 dws record update/create 的 dry-run；确认后再写入。
- 未确认的招聘岗位、简历和面评保持待补，不根据面试文本推断。
- 详细步骤见 `references/process-sync.md`，字段映射见 `references/process-field-mapping.md`。

### 7. Sync Tencent Meeting smart minutes

- 使用 `tmeet record search` 定位候选人录制，确认 `has_smart_minutes=true`，再用 `tmeet record smart-minutes` 获取纪要。
- 通过 manifest 关联钉钉 recordId、面试轮次和 recordFileId，使用 `scripts/sync_tmeet_minutes.py` 并同时传入最新 `--table-json`、`--records-json` 生成更新载荷。
- 脚本必须核对 recordId、候选人姓名、轮次和对应面试时间；非空目标默认进入冲突清单，不直接覆盖。
- 智能纪要只写对应轮次的面试情况字段，不改官方面试结果；详细步骤见 `references/tencent-meeting-smart-minutes.md`。

### 8. Apply stale unevaluated rule

- 使用 `scripts/apply_stale_unevaluated_rule.py`，同时传入最新 `--records` 和 `--table-json`，回读面试时间、结果、后续轮次和 Offer/入职状态。
- 时间必须带时区，Offer/入职按精确枚举判断；取消面试、非法选项或时间异常一律进入复核清单。
- 仅当最后一个已安排面试阶段为“未评价”且严格超过 72 小时、无后续面试、无积极下游状态时，生成该轮结果改为“未通过”的更新载荷。
- 先 dry-run，正式写入后再次回读，并复核符合条件的记录数为 0；详细口径见 `references/stale-unevaluated-rule.md`。

### 9. Rebuild weekly table and dashboard

- 个人台账更新后，重新计算并写入周度漏斗表。
- 当前实例不支持公式字段时，转化率使用 number/percent 预计算。
- 图表更新是完整配置替换；图表创建后如显示名被改，需要再更新名称。
- 窗口过窄时只能查看，不能编辑布局；拉宽浏览器后再调整。

### 10. Report

只汇报聚合结果和异常：新增、更新、跳过、未评价、缺推荐时间、状态冲突、登录失效；不展示候选人姓名、手机号或面评原文。

## First-time setup

1. 按 `references/setup-checklist.md` 完成钉钉、薪人薪事 MCP、浏览器登录和权限配置。
2. 回读 Base、表、字段和选项 ID，填写 `config.json`。
3. 先跑一次全量 `dry_run`，核对 CSV、轮次映射和异常清单。
4. 确认后写入钉钉，建立状态文件和 recordId 映射。
5. 再创建每日 20:30 定时任务。

## Scheduling

用当前环境的 `create_cron_job` 创建每日任务，不要只回复“我会每天跑”。

- `title`：`高招台账每日同步`
- `schedule_type`：`cron`
- `schedule`：按 `config.daily_run_time`，例如 `30 20 * * *`
- `runtime_type`：默认云端；只有任务必须依赖本地文件或本地浏览器登录态时才用本地。
- `query` 必须写清配置路径、增量同步、状态文件、登录失效停止、只汇报聚合结果。

## Using this skill from a GitHub link

其他 HR 的 AI 拿到仓库链接后：

1. 克隆/下载仓库，把 `gaozhao-ledger-sync` 整个目录放到 `workspace/.user_skills/`。
2. 先读 `SKILL.md`，再按任务读取 `setup-checklist.md`、`dingtalk-resources.md`、`sync-state.md`、`aitable-api.md`。
3. 复制 `config.example.json` 和 `sync_state.example.json`，生成自己的配置和状态文件。
4. 先完成登录/权限检查，再跑全量 dry-run；确认后才允许写入和定时任务。
5. 每人一份配置，不把个人配置提交到公开仓库。

可直接发给其他 AI 的一句话：

> 请使用 `gaozhao-ledger-sync` Skill。先读 `SKILL.md` 和 `references/setup-checklist.md`，检查钉钉、薪人薪事登录和权限；今天只做首次全量 dry-run，输出标准台账、面试反馈、同步报告和异常清单，不要写钉钉表。

## Failure handling

- 薪人薪事登录失效：停止写入并提示重新登录。
- 钉钉表头被改：停止写入，先核对标准字段和默认视图列顺序。
- 同一候选人多个岗位：按 `resumeId + applyJobId` 分行，不合并。
- 状态冲突：写入异常清单，必要时标“待复核”，不要猜入职。
- 系统外推荐、系统内安排面试：保留记录，推荐时间留空并备注特殊情况。

## References

- `references/setup-checklist.md`：首次登录、权限、ID 收集和验收清单。
- `references/dingtalk-resources.md`：正式试点 Base、招聘管理表、周度表和团队看板的真实链接。
- `references/sync-state.md`：全量/增量差异、状态文件、去重、状态变化和重试。
- `references/aitable-api.md`：钉钉 AI 表格、记录、图表和 upsert API。
- `references/field-mapping.md`：38 个标准字段、fieldId、轮次映射和人工保护口径。
- `references/process-field-mapping.md`：12 个过程字段、fieldId 和个人 Excel 映射。
- `references/process-sync.md`：个人过程台账的回读、dry-run、写入和验收流程。
- `references/tencent-meeting-smart-minutes.md`：腾讯会议智能纪要的检索、生成载荷和验收流程。
- `references/stale-unevaluated-rule.md`：超时未评价自动转未通过的判定、跳过条件和写入边界。
- `references/source-api.md`：薪人薪事 MCP、浏览器 XHR 和字段限制。
- `references/dingtalk-and-permissions.md`：钉钉表结构与权限分层。
- `references/scheduling.md`：定时任务模板和登录态处理。
- `scripts/field_rules.py`：字段目录、fieldId/fieldName 和实时 singleSelect 选项校验。
- `scripts/state_store.py`：状态文件、内容哈希、recordId 映射和重试辅助。
- `scripts/build_ledger.py`：原始 JSON → 标准台账/面试明细/漏斗。
- `scripts/validate_ledger.py`：写表前校验。
- `scripts/sync_process_fields.py`：个人 Excel → 钉钉过程字段 update/create 载荷。
- `scripts/sync_tmeet_minutes.py`：腾讯会议智能纪要 → 钉钉 update 载荷。
- `scripts/apply_stale_unevaluated_rule.py`：超时未评价 → 未通过更新载荷。
- `assets/config.example.json`、`assets/sync_state.example.json`：配置和状态模板。
