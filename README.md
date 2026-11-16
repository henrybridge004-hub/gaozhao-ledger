# 高招台账

仓库：<https://github.com/henrybridge004-hub/gaozhao-ledger>（公开）

> GitHub 仓库 slug 使用 `gaozhao-ledger`；中文“高招台账”作为 README 标题和仓库描述。

一个给 HR 团队复用的招聘台账工作流：从薪人薪事取数，生成固定 26 列个人台账、面试反馈明细和公开漏斗，再更新到钉钉表格。个人候选人明细互相不可见，HRD/招聘运营看全量；招聘漏斗和点数对全组公开并可排名。

## 这个仓库里有什么

```text
高招台账/
├── README.md                    # 你正在看的落地页
└── gaozhao-ledger-sync/         # 可直接放进 .user_skills 的 Skill
    ├── SKILL.md                 # AI 的主入口，先读这个
    ├── references/
    │   ├── field-mapping.md     # 26 列逐字段来源与特殊规则
    │   ├── source-api.md        # 薪人薪事 MCP 与浏览器接口
    │   ├── dingtalk-and-permissions.md
    │   └── scheduling.md
    ├── scripts/
    │   ├── build_ledger.py      # 原始 JSON → 台账/面试明细/漏斗
    │   └── validate_ledger.py   # 写表前校验
    └── assets/
        ├── config.example.json
        └── ledger_26col_header.csv
```

## 给其他 HR 的 AI：拿到链接后怎么用

把下面这段直接发给对方的 AI，并把 `<仓库链接>` 换成实际链接：

```text
请从这个仓库安装并使用高招台账 Skill：https://github.com/henrybridge004-hub/gaozhao-ledger

步骤：
1. 克隆/下载仓库，把 gaozhao-ledger-sync 整个目录放到你的 workspace/.user_skills/ 下；
2. 先读 gaozhao-ledger-sync/SKILL.md，再读 references/field-mapping.md 和 references/source-api.md；
3. 复制 assets/config.example.json 为 config.json，填我的 hr_name、owner_id、个人台账钉钉链接、公开漏斗钉钉链接；
4. 今天只做 dry-run：用薪人薪事 getResumeList 按 jobOwners 拉最近 30 天候选人，用浏览器同步 XHR 拉 stage-info，运行 scripts/build_ledger.py；
5. 输出 ledger_26col.csv、interview_feedback.csv、funnel_by_hr.csv、sync_report.json；
6. 不要写钉钉表。先告诉我：26 列是否齐、哪些面评缺失、哪些状态冲突、哪些候选人没有推荐记录。
```

第一次跑通后，再让它做两件事：

1. 把 `dry_run` 改成 `false`，按 `resumeId + applyJobId` 更新钉钉个人台账、面试反馈和公开漏斗。
2. 创建每日定时任务（参考 `references/scheduling.md`），默认 20:30；登录态失效时停止并提示，不写旧数据。

## 本机快速开始

Windows PowerShell：

```powershell
# 把 <你的 workspace> 换成你当前 Agent 的 workspace 路径
$skillDir = "<你的 workspace>\.user_skills"
Copy-Item -LiteralPath ".\gaozhao-ledger-sync" -Destination $skillDir -Recurse -Force
Copy-Item -LiteralPath "$skillDir\gaozhao-ledger-sync\assets\config.example.json" -Destination ".\config.json"
```

macOS / Linux：

```bash
mkdir -p ~/.doubao/agent_mode/workspace/.user_skills
cp -r gaozhao-ledger-sync ~/.doubao/agent_mode/workspace/.user_skills/
cp gaozhao-ledger-sync/assets/config.example.json ./config.json
```

具体 `.user_skills` 路径以你当前 Agent 环境为准；不要假设所有机器都是同一个路径。

## 配置

`config.json` 至少填：

```json
{
  "hr_name": "你的姓名",
  "owner_id": "你的薪人薪事招聘域 ownerId",
  "daily_run_time": "20:30",
  "date_window": {"mode": "rolling_days", "days": 30},
  "dingtalk": {
    "personal_ledger_url": "个人台账钉钉表格链接",
    "public_funnel_url": "公开漏斗钉钉表格链接"
  },
  "score_rules": {
    "recommend": 0,
    "screen_pass": 0,
    "interview_scheduled": 0,
    "interview_passed": 0,
    "offer": 0,
    "onboard": 0
  },
  "dry_run": true
}
```

说明：

- `owner_id` 用于 `jobOwners` 过滤；不能用 `recommendHR` 代替。
- 点数权重必须由 HRD 确认；没确认就全部填 0，不要自行发明。
- `config.json` 不要提交到公开仓库；每人一份，只放本地或私有目录。

## 第一次跑

```bash
python scripts/build_ledger.py \
  --resume-list ./raw/resume_list.json \
  --stage-info ./raw/stage_info.json \
  --config ./config.json \
  --out-dir ./out

python scripts/validate_ledger.py \
  --ledger ./out/ledger_26col.csv \
  --interviews ./out/interview_feedback.csv \
  --funnel ./out/funnel_by_hr.csv
```

先看 `out/sync_report.json`：

- `missing_stage`：哪些候选人没拉到流程详情；
- `duplicate_keys`：哪些候选人可能重复；
- `unrated_interviews`：多少场未评价；
- `status_conflicts`：状态与当前阶段冲突；
- `not_recommended`：多少人是“没走推荐、只安排面试”。

## 权限怎么落

推荐“三张表”而不是一张大表：

- 个人台账：本人 + HRD + 招聘运营；其他 HR 看不到。
- 面试反馈明细：同上；不放进公开表。
- 公开漏斗：全组可读，只放人数/场次/转化率/点数/排名，不放姓名、手机号、面评原文。

如果钉钉表格的行级权限没有验证过，不要用一张共享表赌权限；先做“个人表 + 汇总表”。

## 定时任务

- 默认每天 20:30，按团队习惯改。
- 增量用最近 30 天滚动窗口；只查昨天会漏掉推荐/复筛/面试推进。
- 按 `resumeId + applyJobId` 幂等 upsert，不整表覆盖。
- 登录态失效时停止，不用旧缓存冒充当天数据。

## 已知边界

- 薪人薪事 MCP 的 `getResumeInterviewList` 不返回面试官姓名、评分、评语；必须补浏览器详情接口。
- `getProcessSettingList` 可能无权限；不要依赖它枚举流程。
- 面试官姓名优先取 `logItems[].operator`；`interviewInfo` 里没有姓名。
- 费用会计等岗位可能“不推荐、只安排面试”；没有推荐日志不等于没招聘。
- 系统 `stageTypeDesc` 可能与当前投递不一致；以 `resumeLibraryStatus + 当前阶段 + 日志` 交叉核对。

## 发布到 GitHub

```bash
git init
git add README.md gaozhao-ledger-sync
git commit -m "Add gaozhao ledger sync skill"
git remote add origin <你的仓库地址>
git push -u origin main
```

发布前检查：

- 没有 `config.json`、Cookie、token、候选人完整手机号、面评原文。
- `README.md` 里的仓库链接已替换成真实链接。
- `gaozhao-ledger-sync/SKILL.md` 的 `name` 和 `description` 没被改坏。

## 许可

内部 HR 团队复用；对外发布前按公司数据与隐私要求脱敏。
