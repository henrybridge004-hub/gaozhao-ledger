# 高招台账

公开仓库：[gaozhao-ledger](https://github.com/henrybridge004-hub/gaozhao-ledger)

一个给 HR 团队复用的招聘台账工作流：从薪人薪事按 `jobOwners` 取数，生成固定 26 列个人台账、面试反馈明细、公开漏斗和团队看板，并更新到钉钉 AI 表格。个人候选人明细互相不可见；HRD Tracy、招聘运营晓欢可看全量；漏斗、转化率和排名对全组公开。

## 目录

```text
gaozhao-ledger-sync/
├── SKILL.md
├── references/
│   ├── setup-checklist.md          # 首次登录、权限、ID 收集
│   ├── sync-state.md               # 全量/增量、去重、状态更新
│   ├── aitable-api.md              # 钉钉 AI 表格 API
│   ├── field-mapping.md            # 26 列字段映射
│   ├── source-api.md               # 薪人薪事 MCP/浏览器接口
│   ├── dingtalk-and-permissions.md
│   └── scheduling.md
├── scripts/
│   ├── state_store.py              # 状态、哈希、recordId 映射
│   ├── build_ledger.py
│   └── validate_ledger.py
└── assets/
    ├── config.example.json
    ├── sync_state.example.json
    └── ledger_26col_header.csv
```

## 给其他 HR 的 AI

把下面这段发给对方的 AI：

```text
请从 https://github.com/henrybridge004-hub/gaozhao-ledger 安装并使用 gaozhao-ledger-sync。
先读 SKILL.md 和 references/setup-checklist.md，检查钉钉 dws、薪人薪事 MCP、内置浏览器登录和权限；
再复制 config.example.json、sync_state.example.json 生成我的配置和状态文件。
今天只做首次全量 dry-run，输出 26 列台账、面试反馈、同步报告和异常清单，不要写钉钉表。
```

## 首次使用

1. 确认钉钉 CLI：`dws version`、`dws auth status`；未登录则按 CLI 引导登录。
2. 确认薪人薪事 MCP 可调用，并在内置浏览器登录 `https://s.xinrenxinshi.com/staff/home`。
3. 回读钉钉 Base、26 列表、周度表、看板和字段 ID。
4. 配置权限：HRD/招聘运营看全量；普通 HR 只看本人明细；公开看板只放聚合数据。
5. 先跑全量 dry-run；确认后再写入钉钉并建立状态文件。
6. 最后创建每日 20:30 定时任务。

## 全量与增量

- 首次全量：显式时间范围，拉取全部列表和详情，建立 `resumeId + applyJobId -> dingtalk recordId` 映射。
- 每日增量：仍拉最近 30 天列表以发现状态变化，但只对新增/变化记录拉详情、更新原记录。
- 去重：同一 `resumeId + applyJobId` 永远更新同一行；历史记录缺少外部 ID 时用“姓名 + 手机号 + 岗位”兜底。
- 状态变化：例如“二面待定”后来变成“Offer/待入职”，只更新原 recordId，不重复创建。
- 周度表：当前实例不支持公式字段，转化率和漏斗数由同步任务预计算。

## 发布前检查

- 不提交 `config.json`、`sync_state.json`、Cookie、token、密码或验证码。
- 公开文件中没有候选人完整手机号、面评原文、最近公司等个人明细。
- 运行 `python scripts/state_store.py` 确认状态工具自测通过。
- 用 Skill 校验工具确认目录结构有效。
