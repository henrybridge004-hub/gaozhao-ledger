# 钉钉 AI 表格生产资源

这些资源指向当前正式试点 Base。仓库公开发布的是入口和 ID，不包含登录凭证；实际可见范围以钉钉高级权限为准。

说明：周度漏斗分析表已重建，当前有效表 ID 为 `Y9ctSpD`；团队看板中的周度图表已同步重绑到该表。

## 资源总览

| 资源 | ID | 链接 |
|---|---|---|
| Base：高招台账（正式试点） | `vy20BglGWOexXo2KsDEk9jn9JA7depqY` | https://alidocs.dingtalk.com/i/nodes/vy20BglGWOexXo2KsDEk9jn9JA7depqY |
| 招聘管理（26 列台账） | `t4tIt8f` | https://alidocs.dingtalk.com/i/nodes/vy20BglGWOexXo2KsDEk9jn9JA7depqY?iframeQuery=entrance%3Ddata%26sheetId%3Dt4tIt8f |
| 周度漏斗分析 | `Y9ctSpD` | https://alidocs.dingtalk.com/i/nodes/vy20BglGWOexXo2KsDEk9jn9JA7depqY?iframeQuery=entrance%3Ddata%26sheetId%3DY9ctSpD |
| 高招团队周度复盘 | `dashboard-daf0fabe-e32a-47bb-a375-226bced30dbd` | https://alidocs.dingtalk.com/i/nodes/vy20BglGWOexXo2KsDEk9jn9JA7depqY?iframeQuery=entrance%3Ddata%26applicationId%3Ddashboard-daf0fabe-e32a-47bb-a375-226bced30dbd |

## 使用规则

1. 普通 HR 只填写并查看本人负责的候选人明细；公开漏斗和团队看板可查看全组聚合排名。
2. HRD Tracy、招聘运营晓欢可查看全量明细。
3. 首次接入时仍需填写自己的 `hr_name` 和薪人薪事 `owner_id`。
4. 首次运行必须先 dry-run，确认匹配记录、异常和权限后，再正式写入。
5. 若打开链接出现无权限提示，先联系管理员调整钉钉角色，不要绕过权限或复制到个人新表。
6. 每日同步必须按 `resumeId + applyJobId` 更新同一行，不重复创建候选人。

## 配置对应关系

`config.json` 中的 `dingtalk` 字段按以下值填写：

```json
{
  "base_id": "vy20BglGWOexXo2KsDEk9jn9JA7depqY",
  "ledger_table_id": "t4tIt8f",
  "weekly_table_id": "Y9ctSpD",
  "dashboard_id": "dashboard-daf0fabe-e32a-47bb-a375-226bced30dbd"
}
```
