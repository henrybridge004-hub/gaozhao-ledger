# 薪人薪事数据源

## 1. MCP 与浏览器分工

| 数据 | 首选 | 说明 |
|---|---|---|
| 候选人列表/岗位/渠道/城市/公司/职位/状态 | 薪人薪事 MCP `getResumeList` | 分页拉全 |
| 候选人详情/期望薪资/完整手机号 | `getResumeDetail` | 台账只存脱敏号 |
| 面试轮次/时间/结果 | `getResumeInterviewList` | 有轮次和时间，但无面试官姓名、无评分/评语 |
| 推荐时间/推荐备注/业务复筛结果/面评/能力项 | 浏览器详情接口 | MCP 不返回，必须补 |

## 2. `getResumeList`

实际工具名以当前环境 `tool_search` 返回为准；常见为 `mcp__xrxs__recruitment_getresumelist`。

已验证过滤方式：

```json
{
  "filters": [
    {
      "key": "jobOwners",
      "type": 2,
      "values": [{"value": "<ownerId>"}]
    },
    {
      "key": "applyTime",
      "type": 1,
      "values": ["<startUnix>", "<endUnix>"]
    }
  ],
  "pageNum": 1,
  "pageSize": 100
}
```

注意：

- `jobOwners` / `recommendHR` 的 `type` 必须是 `2`，`values` 必须是对象 `{"value": ownerId}`；裸字符串会报 `is not of type 'object'`。
- `recommendHR` 是“推荐人”视角，不能代表台账归属；台账按 `jobOwners` 当前负责人。
- `getResumeList` 不筛选时 `count` 可达百万级，不要直接拉全库。
- 日期时间戳按 `Asia/Shanghai` 换算。示例：`2026-10-01 00:00:00` = `1790784000`；`2026-11-17 00:00:00` = `1794844800`（覆盖 11/16 全天）。
- 每日增量不要只查昨天：流程推进可能发生在投递后很久。默认用最近 30 天 `applyTime` 滚动窗口，按 `resumeId + applyJobId` 更新已有行。

已验证返回字段：

`resumeId,name,mobile,email,sexDesc,age,degreeDesc,school,major,workAge,lastCompany,lastJob,lastSalary,industry,applyJobName,applyJobId,channelDesc,workCity,currentStatus,resumeLibraryStatusDesc,stageTypeDesc,customStageDesc,workExperiences,educationExperiences`

## 3. 浏览器详情接口

页面：`https://s.xinrenxinshi.com/recruitment/detail?resumeId=<resumeId>`

内部接口：

```text
https://s.xinrenxinshi.com/recruitment/service/ajax-get-resume-detail-stage-info?resumeId=<resumeId>&talentCompanyId=
```

必须用页面内**同步 XHR**，不要用 `bu.http_get`：

```javascript
(function () {
  var id = "<resumeId>";
  var xhr = new XMLHttpRequest();
  xhr.open("GET", "https://s.xinrenxinshi.com/recruitment/service/ajax-get-resume-detail-stage-info?resumeId=" + id + "&talentCompanyId=", false);
  xhr.send();
  return xhr.responseText;
})()
```

原因：`bu.http_get` 不自动带页面 Cookie，会返回 `{"code":2006,"message":"请先登录"}`；页面内同步 XHR 才带登录态。`bu.js` 只支持同步结果，异步 `fetch` 的 Promise 写法会报错。

其他可用接口：

- `ajax-get-resume-basic?resumeId=<id>&talentCompanyId=`：基础信息、`recommenderId`、`recommendReason`、`channelDesc`、`applyTime`。
- `ajax-get-resume-message-board-by-resumeId?resumeId=<id>`：留言板。
- `ajax-get-resume-detail-operations?...`：可执行操作，不含 offer 明细。
- `ajax-check-auto-generate-interview-question?resumeId=<id>`：自动生成面试题标记。

登录失效时用 `interaction.request_action` 让用户接管浏览器；不要在未登录状态继续抓取或编造数据。

## 4. `stageActionLogs` 结构

每个阶段含：

- `resumeStageDesc`、`stageTypeDesc`、`current`、`sort`
- `stageActionLogs[]`

日志字段：

`actionDesc, actionRemark, operator, operateTime, businessTime, resultStatus, resultStatusDesc, recommendInfo, interviewInfo, hireInfo, examInfo, evaluationInfo, logItems`

关键语义：

- `推荐简历` 日志：推荐时间用 `operateTime`，不是 `businessTime`；`actionRemark` 是推荐备注；`resultStatusDesc` 是业务复筛结果（`已通过/未通过/未反馈`）。
- `安排面试` 日志：`businessTime` 是实际面试时间；`operateTime` 是安排面试的操作时间；`interviewInfo` 含 `interviewId, roundId, interviewRounds, interviewRoundName, interviewTypeDesc, interviewAddress, meetingLink...`。
- `interviewInfo` **不含面试官姓名**；面试官/评价人取 `logItems[].operator`。
- `evaluationInfo` 可能为 `null`；面评在 `logItems[].resultComment`、`resultScore`、`resultStatusDesc`、`expand.judgement`。
- `logItems[].expand.judgement` 是 JSON 字符串；解析后 `type=4` 为能力项，`labelName` 是能力项名，`value` 是候选人得分档位；`type=2` 是“做我下属/同事/上级愿意吗”；`resultComment` 是面评原文。

## 5. 已知限制

- `getProcessSettingList` 可能无权限；不要依赖它枚举流程。
- `getResumeDetail` 不含推荐人、推荐备注、面试反馈正文；不要用它补推荐人。
- `getResumeInterviewList` 的 `interviewerNames` 可能为空；不要用它判断没有面试官。
- 同名候选人很多；必须用 `resumeId + 岗位 + 手机号` 复核，不要只按姓名搜索。
- 状态字段可能不一致：例如 `stageTypeDesc` 显示“入职”，`resumeLibraryStatus` 仍是“已归档”；台账以 `resumeLibraryStatus + 当前投递阶段` 为准，冲突写“待复核”。

## 6. 抓取顺序

1. `getResumeList` 分页拉候选人，保存 `raw/resume_list.json`。
2. 对每个 `resumeId` 用浏览器同步 XHR 拉 stage-info，保存 `raw/stage_info.json`。
3. 如需期望薪资/完整手机号，再按需拉 `getResumeDetail`；不要全量拉详情，避免慢和敏感数据扩散。
4. 把原始 JSON 交给 `scripts/build_ledger.py`，不要手工拼标准字段。
