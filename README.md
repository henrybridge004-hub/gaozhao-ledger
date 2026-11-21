# 高招台账

公开仓库：[gaozhao-ledger](https://github.com/henrybridge004-hub/gaozhao-ledger)

一个给 HR 团队复用的招聘台账工作流：从薪人薪事按 `jobOwners` 取数，生成个人台账、面试反馈明细、公开漏斗和团队看板，并更新到钉钉 AI 表格。当前共 38 个字段，已统一“一面/二面/三面”命名和默认视图列顺序；字段 ID、记录和单元格数据保持稳定。个人候选人明细互相不可见；HRD Tracy、招聘运营晓欢可看全量；漏斗、转化率和排名对全组公开。

## 目录

```text
gaozhao-ledger-sync/
├── SKILL.md
├── references/
│   ├── setup-checklist.md          # 首次登录、权限、ID 收集
│   ├── dingtalk-resources.md       # 正式试点 Base/表/看板真实链接
│   ├── sync-state.md               # 全量/增量、去重、状态更新
│   ├── aitable-api.md              # 钉钉 AI 表格 API
│   ├── field-mapping.md            # 38 个标准字段映射
│   ├── process-field-mapping.md    # 12 个过程字段映射
│   ├── process-sync.md             # 个人过程台账同步流程
│   ├── tencent-meeting-smart-minutes.md # 腾讯会议智能纪要同步
│   ├── stale-unevaluated-rule.md     # 超时未评价自动转未通过
│   ├── source-api.md               # 薪人薪事 MCP/浏览器接口
│   ├── dingtalk-and-permissions.md
│   └── scheduling.md
├── scripts/
│   ├── state_store.py              # 状态、哈希、recordId 映射
│   ├── field_rules.py              # 实时字段与单选选项校验
│   ├── build_ledger.py
│   ├── validate_ledger.py
│   ├── sync_process_fields.py      # 个人 Excel 过程字段载荷生成
│   ├── sync_tmeet_minutes.py       # 腾讯会议智能纪要载荷生成
│   └── apply_stale_unevaluated_rule.py # 超时未评价载荷生成
├── tests/
│   └── test_rules.py               # 无候选人数据的合成回归测试
└── assets/
    ├── config.example.json
    ├── sync_state.example.json
    └── ledger_system_fields_header.csv
```

## 给其他 HR 的 AI

把下面这段发给对方的 AI：

```text
请从 https://github.com/henrybridge004-hub/gaozhao-ledger 安装并使用 gaozhao-ledger-sync。
先读 SKILL.md 和 references/setup-checklist.md、references/dingtalk-resources.md，检查钉钉 dws、薪人薪事 MCP、内置浏览器登录和权限；
再复制 config.example.json、sync_state.example.json 生成我的配置和状态文件。
今天只做首次全量 dry-run，输出标准台账、面试反馈、同步报告和异常清单，不要写钉钉表。
```

## 正式试点钉钉资源

- Base：[高招台账（正式试点）](https://alidocs.dingtalk.com/i/nodes/vy20BglGWOexXo2KsDEk9jn9JA7depqY)
- [招聘管理（38 字段）](https://alidocs.dingtalk.com/i/nodes/vy20BglGWOexXo2KsDEk9jn9JA7depqY?iframeQuery=entrance%3Ddata%26sheetId%3Dt4tIt8f)
- [周度漏斗分析](https://alidocs.dingtalk.com/i/nodes/vy20BglGWOexXo2KsDEk9jn9JA7depqY?iframeQuery=entrance%3Ddata%26sheetId%3DY9ctSpD)
- [高招团队周度复盘](https://alidocs.dingtalk.com/i/nodes/vy20BglGWOexXo2KsDEk9jn9JA7depqY?iframeQuery=entrance%3Ddata%26applicationId%3Ddashboard-daf0fabe-e32a-47bb-a375-226bced30dbd)

完整 ID 和使用规则见 `gaozhao-ledger-sync/references/dingtalk-resources.md`。

## 首次使用

1. 确认钉钉 CLI：`dws version`、`dws auth status`；未登录则按 CLI 引导登录。
2. 确认薪人薪事 MCP 可调用，并在内置浏览器登录 `https://s.xinrenxinshi.com/staff/home`。
3. 回读钉钉 Base、标准招聘管理表、周度表、看板和字段 ID；配置模板只含占位符，必须逐项替换，不能沿用其他正式试点资源 ID。
4. 用 `dws aitable field get` 保存最新字段快照；`validate_ledger.py --fields-json ... --strict` 会按实时单选选项拦截非法值。
4. 配置权限：HRD/招聘运营看全量；普通 HR 只看本人明细；公开看板只放聚合数据。
5. 先跑全量 dry-run；确认后再写入钉钉并建立状态文件。
6. 最后创建每日 20:30 定时任务。

## 全量与增量

- 首次全量：显式时间范围，拉取全部列表和详情，建立 `resumeId + applyJobId -> dingtalk recordId` 映射。
- 每日增量：仍拉最近 30 天列表以发现状态变化，但只对新增/变化记录拉详情、更新原记录。
- 去重：同一 `resumeId + applyJobId` 永远更新同一行；历史记录缺少外部 ID 时用“姓名 + 手机号 + 岗位”兜底。
- 状态变化：例如“二面待定”后来变成“Offer/待入职”，只更新原 recordId，不重复创建。
- 周度表：当前实例不支持公式字段，转化率和漏斗数由同步任务预计算。

## 个人过程台账同步

1. 回读钉钉表结构和现有记录，按姓名匹配候选人；存在重名时脚本直接中止，先人工确认 recordId。
2. 使用 `scripts/sync_process_fields.py` 从个人 Excel 生成更新、新建和聚合报告三类 JSON；新建记录必须显式传入 `--hr-value-json`，不从其他记录猜 HR。
3. 非空目标字段默认受保护，内容不一致进入冲突清单；只有明确传入 `--allow-nonempty-overwrite` 才允许覆盖。
4. 先对 update/create 载荷执行 dws dry-run，确认后再写入，每批最多 100 条。
5. 12 个过程字段的 fieldId 和来源映射见 `references/process-field-mapping.md`；标准显示名和列顺序见 `references/field-mapping.md`。
6. 岗位、简历或面评没有可靠来源时留空并进入异常清单，不写“未抓取”，不从面试文本推断。

## 腾讯会议智能纪要同步

1. 使用 `tmeet record search` 按候选人、面试时间定位可访问录制，确认已生成智能纪要。
2. 使用 `tmeet record smart-minutes` 获取纪要，通过 manifest 关联钉钉记录和面试轮次。
3. 使用 `scripts/sync_tmeet_minutes.py` 生成钉钉更新载荷，必须同时传入最新 `--table-json` 和 `--records-json`；脚本核对 recordId、姓名、轮次和面试时间。
4. 目标面试情况已有不同内容时默认进入冲突清单，不覆盖；确认后才用 `--allow-nonempty-overwrite`。
5. 智能纪要只写入各轮“面试情况”，不改官方面试结果；详细步骤见 `references/tencent-meeting-smart-minutes.md`。

## 超时未评价规则

1. 使用 `scripts/apply_stale_unevaluated_rule.py`，同时传入最新记录和 `--table-json` 字段快照。
2. 最后一个有面试时间的阶段为“未评价”、严格超过 72 小时、无后续面试且无 Offer/入职下游状态时，才生成“未通过”载荷。
3. 时间必须带时区；Offer/入职按精确枚举判断；出现取消面试、非法枚举或时间异常时进入复核清单。
4. 当前表没有真实“状态变更时间”字段，72 小时以面试时间为代理；改期、补录记录必须人工复核。
5. 先 dws dry-run，正式写入后再次回读复核。

## 发布前检查

- 不提交 `config.json`、`sync_state.json`、Cookie、token、密码或验证码。
- 公开文件中没有候选人完整手机号、面评原文、最近公司等个人明细。
- 运行 `python gaozhao-ledger-sync/scripts/state_store.py` 确认状态工具自测通过。
- 运行 `python -m unittest discover -s gaozhao-ledger-sync/tests -p "test_*.py" -v`，确保合成回归测试全部通过。
- 用实时字段快照执行 `validate_ledger.py --strict`，确认没有非法枚举值。
- 用 Skill 校验工具确认目录结构有效。
