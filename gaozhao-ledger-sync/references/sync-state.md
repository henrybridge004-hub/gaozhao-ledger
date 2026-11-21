# 全量、增量、去重与状态更新

## 1. 全量同步与每日增量的区别

| 维度 | 首次全量 | 每日增量 | 周期校验 |
|---|---|---|---|
| 触发条件 | 没有状态文件、首次接入、历史回填 | 每日 20:30 定时任务 | 建议周一或每周一次 |
| 时间范围 | 显式起止日期，例如 2026-10-01 到今天 | 最近 30 天 `applyTime` 滚动窗口 | 最近 90 天滚动窗口 |
| 列表拉取 | 分页拉全 | 分页拉全，用于发现状态变化 | 分页拉全 |
| stage-info 详情 | 范围内全部拉取 | 只给新增/内容变化的记录拉详情 | 全量或按异常清单复核 |
| 目标 | 建立基线和 recordId 映射 | 少抓详情、少写表、更新状态 | 发现漏抓、状态冲突和权限问题 |
| 写入 | 批量 create，保存 recordId | 同 key update，不重复 create | 只更新异常/变化记录 |

每日增量不是“只查昨天”。候选人可能在投递后数周才推进到二面、Offer、入职，所以列表仍用最近 30 天滚动窗口；节省 token 的关键是**跳过未变化记录的详情抓取和写入**。

## 2. 状态文件结构

状态文件路径由 `config.sync_state_file` 指定。示例见 `assets/sync_state.example.json`。

```json
{
  "version": 1,
  "last_successful_at": "2026-11-16T20:31:00+08:00",
  "last_cursor": "cursor-001",
  "runs": {
    "run-001": {
      "mode": "full",
      "started_at": "2026-11-16T20:30:00+08:00",
      "finished_at": "2026-11-16T20:31:00+08:00",
      "success": true,
      "window": {"start": "2026-10-01", "end": "2026-11-16"},
      "errors": []
    }
  },
  "records": {
    "resume-001::apply-job-001": {
      "first_seen_at": "2026-11-16T20:30:00+08:00",
      "last_seen_at": "2026-11-16T20:30:00+08:00",
      "last_detail_fetch_at": "2026-11-16T20:30:00+08:00",
      "content_hash": "<sha256>",
      "changed": false,
      "dingtalk_record_id": "rec-001",
      "last_status": "未入职",
      "last_written_at": "2026-11-16T20:31:00+08:00",
      "failures": []
    }
  }
}
```

状态文件必须原子写入：先写 `.tmp`，再替换正式文件，避免任务中断导致状态损坏。

## 3. 主键与去重

### 主键

- 标准主键：`resumeId + applyJobId`。
- 同一候选人投不同岗位：保留不同行，不合并。
- 同一候选人同一岗位重复出现：更新原行，不追加。
- 钉钉可见字段不新增外部 ID，因此外部 ID 映射保存在状态文件和同步报告里。

### 兜底键

如果历史记录没有外部 ID，用“候选人姓名 + 手机号 + 招聘岗位”生成兜底键；不能只按姓名匹配。多个候选匹配或手机号缺失时，进入异常清单让人工确认。

### 避免重复抓取

1. 每次仍先拉候选人列表，因为列表是发现状态变化的入口。
2. 对列表项做轻量哈希；哈希未变且状态字段未变时，跳过 stage-info 详情。
3. 只对新增、状态变化、新增面试、Offer/入职变化、失败重试的记录拉详情。
4. 查询钉钉记录时用 `--field-ids` 限制返回字段。
5. 已成功写入的 recordId 保存到状态文件，下次直接 update。
6. 不可变的基础信息可缓存；敏感信息不要扩散到公开文件。

## 4. 候选人状态变化更新

### 标准 upsert 规则

对同一个业务键：

1. 读取状态文件中的钉钉 `recordId`。
2. 拉取最新 stage-info 并生成标准字段 payload。
3. 计算内容哈希，与上一次哈希比较。
4. 哈希不变：跳过详情写入。
5. 哈希变化：只更新变化字段，保留原 recordId。
6. 写入成功后更新哈希、状态和最后写入时间。

### 常见状态变化

| 变化 | 处理方式 |
|---|---|
| 今天二面待定，过两天变成 Offer | 更新同一行的二面结果、Offer 情况、入职状态；不新建候选人 |
| 未评价后来补了面评 | 更新面试结果、评分、评语、数据状态，并从未评价数量中移除 |
| 新增三面/HR 面 | 更新三面时间和三面结果，保留已有一/二面字段 |
| Offer 被接受/拒绝/过期 | 更新 Offer 情况；待入职排名只统计接受/待入职/审批中状态 |
| 待入职变成已入职 | 更新入职状态和入职时间，从待入职排名移到入职排名 |
| 负责人变更 | 按当前 `jobOwners` 更新 HR 姓名；旧负责人信息进入同步报告 |
| 面试取消 | 保留取消记录，不把取消场次计入实际到面 |
| 系统外推荐、系统内安排面试 | 保留记录，推荐时间留空，备注特殊来源，不从台账排除 |

## 5. 失败与重试

- 单条详情失败：记录 `failures`，其他记录继续处理。
- 钉钉写入失败：保留本地 payload 和报告，下次根据 recordId 重试 update。
- 登录失效：停止写入，提示重新登录；不要用旧缓存冒充当天数据。
- 状态冲突：写入异常清单，必要时状态标“待复核”，不要猜入职。
- 本次运行只有全部目标写入成功并回读确认后，才更新 `last_successful_at`。

## 6. 周度表与看板联动

- 个人台账更新后，重新计算周度漏斗表；当前实例不支持公式字段，转化率需预计算。
- 周度表按推荐周归集，缺少 Offer 日期字段时不能按 Offer 日期归集。
- 跨周漏斗可能出现 >100%，因为当周到面/Offer 的候选人可能来自更早推荐周。
- 看板图表读取的是预计算结果，不会自动重算；同步任务必须显式更新周度表。

## 7. 最小执行伪代码

```text
load config and state
if state has no successful baseline: mode = full
else: mode = incremental
begin_run(mode, window)
candidate_list = fetch_resume_list(jobOwners, window)
for candidate in candidate_list:
    key = resumeId + applyJobId
    if mode == full or list_snapshot_changed(candidate):
        stage_info = fetch_stage_info(resumeId)
    payload = build_standard_payload(candidate, stage_info)
    if key in state and recordId exists: update changed fields
    else: create record and save recordId
rebuild weekly table and validate dashboard
finish_run and atomically save state
```
