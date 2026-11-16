---
name: gaozhao-ledger-sync
description: 高招台账自动同步：从薪人薪事按 jobOwners 拉取候选人与面试流程，生成固定 26 列个人台账、面试反馈明细和公开漏斗，并更新钉钉表格。适用于首次搭建高招台账、每日增量同步、补历史数据、核对台账口径、配置“个人明细互相不可见但漏斗公开排名”，以及让其他 HR 的 AI 复用同一套流程。
---

# 高招台账自动同步

## What this skill does

把薪人薪事的招聘数据整理成 HRD 可用的高招台账，并保持 HR 原有 26 个字段不变：

1. **个人台账**：26 列，一人一行，候选人明细只对本人、HRD、招聘运营可见。
2. **面试反馈明细**：一场面试一行，保留面试官、结果、评分、评语、能力项。
3. **公开漏斗**：只放人数/场次/转化率/点数，不放候选人姓名、手机号、面评等明细；HR 之间可见并排名。
4. **每日同步**：定时拉取薪人薪事增量，按 `resumeId + applyJobId` 更新已有行、追加新行，不整表覆盖。

## Non-negotiables

- **26 列顺序不变**：`HR姓名、候选人姓名、来源渠道、城市、招聘岗位、手机号、最近任职公司、上家任职职位、薪资架构、沟通备注、HR沟通结果、推荐简历时间、简历推荐是否通过、一轮面试时间、未通过/未参加/考虑中具体原因、一轮面试结果、二轮面试时间、未通过/未参加/考虑中具体原因、二轮面试结果、终面面试时间、未通过/未参加/考虑中具体原因、终面面试结果、offer情况、入职状态、入职时间、备注`。
- **HR 姓名取 `jobOwners` 当前负责人**，不要只取 `recommendHR`。`recommendHR` 只用于判断“是否由本人推荐”，不能代表台账归属。
- **个人明细不进公开漏斗**。公开漏斗只允许聚合数字；任何姓名、手机号、最近公司、面评原文都不能出现在公开表。
- **不整表覆盖**。按 `resumeId + applyJobId` 幂等 upsert；先读现有表，再改目标行/追加新行。
- **不采信单一状态字段**。`stageTypeDesc` 可能与当前投递不一致；以 `resumeLibraryStatus + 当前投递阶段 + 流程日志` 交叉核对。
- **不编造面评/面试官**。没有填写就写“未评价”；面试官优先取 `logItems[].operator`，不要用 `interviewInfo` 里不存在的姓名字段硬填。
- **不把密码、Cookie、token 写进配置、日志、回复或 GitHub**。登录态交给连接器/浏览器会话。

## Inputs

首次运行前准备一个 `config.json`，可复制 `assets/config.example.json`：

- `hr_name`：台账里的 HR 姓名，例如“你的姓名”。
- `owner_id`：薪人薪事招聘域 ownerId；用于 `jobOwners` 过滤。
- `timezone`：默认 `Asia/Shanghai`。
- `daily_run_time`：每日执行时间，默认 `20:30`，按团队习惯改。
- `date_window`：首次回填的起止日期；每日增量用滚动窗口，不要只查昨天。
- `dingtalk.personal_ledger_url`：个人台账钉钉表格链接。
- `dingtalk.public_funnel_url`：公开漏斗钉钉表格链接。
- `score_rules`：HRD 确认过的点数权重；没确认就全部设为 0，不要自行发明。
- `dry_run`：首次必须 `true`。

## Daily workflow

### 0. Preflight

1. 读取 `config.json` 和目标钉钉表头，确认 26 列顺序没有被改。
2. 确认当前登录态：薪人薪事 MCP 可调用；浏览器已登录 `s.xinrenxinshi.com`。
3. 确认今天是增量还是回填；增量默认用“最近 30 天 applyTime 滚动窗口”，避免只查昨天漏掉流程推进。
4. 设置 `dry_run=true` 时只产出 CSV/报告，不写钉钉表。

### 1. Pull candidate list from Xinrenxinshi

优先用薪人薪事 MCP 的 `getResumeList`（实际工具名以当前环境 `tool_search` 为准）：

- 过滤 `jobOwners`，`type=2`，`values` 放对象 `{"value": owner_id}`。
- 加 `applyTime` 起止时间；时间戳按 `Asia/Shanghai` 换算成 Unix 秒。
- 分页拉全，不要只取第一页。
- 需要字段：`resumeId,name,mobile,applyJobId,applyJobName,channelDesc,workCity,lastCompany,lastJob,lastSalary,resumeLibraryStatus,resumeLibraryStatusDesc,stageTypeDesc`。

详细调用和已知字段限制见 `references/source-api.md`。

### 2. Pull stage/evaluation detail

MCP 的 `getResumeInterviewList` 不返回面试官姓名、评分、评语原文；必须补浏览器详情接口：

- 在已登录的 `s.xinrenxinshi.com` 页面内，用**同步 XMLHttpRequest** 请求
  `https://s.xinrenxinshi.com/recruitment/service/ajax-get-resume-detail-stage-info?resumeId=<resumeId>&talentCompanyId=`。
- 把结果按 `resumeId` 存成 `{"resumeId": [stages...]}` 的 JSON。
- 不要用 `bu.http_get` 直接调，它不带 Cookie 会返回 2006 未登录；页面内同步 XHR 才带登录态。
- 登录失效时走 `interaction.request_action` 让用户接管浏览器，不要猜数据。

### 3. Build the 26-column ledger

```bash
python scripts/build_ledger.py \
  --resume-list ./raw/resume_list.json \
  --stage-info ./raw/stage_info.json \
  --config ./config.json \
  --out-dir ./out
```

产出：

- `out/ledger_26col.csv`：26 列个人台账。
- `out/interview_feedback.csv`：面试反馈明细。
- `out/funnel_by_hr.csv`：公开漏斗聚合。
- `out/sync_report.json`：新增/更新/跳过数量、异常清单。

字段来源与特殊规则见 `references/field-mapping.md`。

### 4. Validate before writing

```bash
python scripts/validate_ledger.py \
  --ledger ./out/ledger_26col.csv \
  --interviews ./out/interview_feedback.csv \
  --funnel ./out/funnel_by_hr.csv
```

必须通过：

- 26 列表头完全一致，顺序不变。
- 同一 `候选人姓名 + 手机号 + 招聘岗位` 不重复。
- 面试时间不早于推荐时间；结束时间不早于开始时间。
- offer/入职状态与 `resumeLibraryStatus` 对得上；对不上进异常清单。
- 公开漏斗只有聚合字段，没有候选人明细。

### 5. Write to DingTalk

按 `references/dingtalk-and-permissions.md` 执行。核心规则：

1. 先读目标表现有 `resumeId` 或业务键；没有业务键时用 `候选人姓名 + 手机号 + 招聘岗位` 兜底。
2. 存在则只更新变化字段；不存在则追加到末尾。
3. 不删除、不重排、不清空整表。
4. 公开漏斗只写聚合行；个人台账只写本人范围。
5. 第一次先 `dry_run`，把 `ledger_26col.csv` 给用户确认，再开写入。

### 6. Update funnel and report

公开漏斗至少包含：接收简历、推荐、业务复筛通过、安排面试、实际面试、面试通过、offer、待入职/入职，以及 config 中定义的 points。排名按 points 或 HRD 指定指标；HR 之间可见，候选明细不可见。

### 7. Reply with a short sync report

只汇报聚合结果和异常：

- 新增/更新多少行，面试多少场，未评价多少场。
- 本次异常：状态不一致、缺面试官、面评为空、重复候选人。
- 不把候选人姓名、手机号、面评原文贴到公开渠道。

## First-time setup

1. 复制 `assets/config.example.json` 为 `config.json`，填 `hr_name`、`owner_id`、两个钉钉表链接。
2. 先做一次 **30 天 dry-run**，核对 26 列、轮次映射、未评价数量。
3. 确认钉钉表权限：个人台账只有本人 + HRD/招聘运营；公开漏斗全组可读。
4. 再开每日定时。

## Scheduling

用当前环境的 `create_cron_job` 创建每日任务；不要只回复“我会每天跑”。

- `title`：`高招台账每日同步`
- `schedule_type`：`cron`
- `schedule`：按 `config.daily_run_time`，例如 `30 20 * * *`
- `query` 必须包含：本次请求由「高招台账每日同步」定时任务触发；读取 `config.json`；执行 `dry_run=false` 的增量同步；完成后只汇报聚合结果与异常；登录态失效时停止并提示用户。
- 默认 `runtime_type=1`（云端）；只有任务必须读本地文件/本地浏览器登录态时才用 `2`。

详细定时任务模板和登录态处理见 `references/scheduling.md`。

## Using this skill from a GitHub link

其他 HR 的 AI 拿到仓库链接后，按以下顺序执行：

1. 克隆/下载仓库，把 `gaozhao-ledger-sync` 整个目录放到它的 `workspace/.user_skills/` 下。
2. 让 AI 先读 `SKILL.md`，再读 `references/field-mapping.md` 和 `references/source-api.md`。
3. 复制 `assets/config.example.json` 为 `config.json`，填自己的 `hr_name`、`owner_id`、钉钉表链接。
4. 先跑 `dry_run`，只生成 CSV，不写钉钉；确认后再开写入和定时任务。
5. 不要把所有人的 `config.json` 聚在一个公开仓库里；每人一份，权限按人隔离。

可直接发给其他 AI 的一句话：

> 请使用仓库里的 `gaozhao-ledger-sync` Skill。先读 `SKILL.md`、`references/field-mapping.md`、`references/source-api.md`，再按 `assets/config.example.json` 生成我的 `config.json`。今天只做 dry-run，输出 `ledger_26col.csv`、`interview_feedback.csv`、`sync_report.json`，不要写钉钉表；先告诉我异常和缺失字段。

## Failure handling

- 薪人薪事登录失效：停止写入，提示用户重新登录；不要用旧缓存冒充当天数据。
- 浏览器接口 2006：切回页面内同步 XHR；仍失败则只产出 API 可见字段，并标记“面试评价未抓取”。
- 钉钉表头被改：停止写入，先恢复 26 列顺序。
- 同一候选人多个岗位：按 `resumeId + applyJobId` 分行，不合并。
- 状态冲突：保留原始状态到 `sync_report.json`，台账写“待复核”，不要猜入职。

## References

- `references/field-mapping.md`：26 列逐列来源、轮次映射、评价提取、异常规则。
- `references/source-api.md`：薪人薪事 MCP、浏览器 XHR、字段限制、时间戳。
- `references/dingtalk-and-permissions.md`：钉钉表结构、权限分层、写入策略、漏斗口径。
- `references/scheduling.md`：每日定时任务模板、增量窗口、登录态与幂等。
- `scripts/build_ledger.py`：原始 JSON → 26 列台账/面试明细/漏斗。
- `scripts/validate_ledger.py`：写表前校验。
- `assets/config.example.json`：配置模板。
- `assets/ledger_26col_header.csv`：26 列表头模板。
