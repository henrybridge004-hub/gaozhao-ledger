# 钉钉 AI 表格 API 调用

## 1. 命令边界

处理 `.able` / AI 表格时使用 `dws aitable`，不要用普通 sheet 能力。

常用资源：

```text
dws aitable base       get/list/search/create/update
dws aitable table      get/create/update/delete
dws aitable field      get/create/update/delete/search-options
dws aitable record     query/create/update/delete
dws aitable dashboard  get/create/update/delete
dws aitable chart      get/create/update/delete/widgets-example
```

通用建议：

- 机器读取结果时加 `--format json`。
- Windows 下长 JSON 用 `--records-file`，避免命令行截断。
- 查询记录时用 `--field-ids` 只取需要的字段，减少 token。
- 写操作先加 `--dry-run` 预览，确认后再实际执行。
- 不写入 filterUp、lookup 等只读字段；当前实例不支持公式字段时，转化率用 number 预计算。

## 2. 读取 Base、表和字段

```bash
dws aitable base get --base-id <baseId> --format json
dws aitable table get --base-id <baseId> --table-id <tableId> --format json
dws aitable field get --base-id <baseId> --table-id <tableId> --format json
```

字段回读用于确认：

- fieldId 与字段名的对应关系。
- 单选/多选选项 ID 和选项名称。
- 日期、人员、数字、百分比等字段的真实类型。
- 标准字段是否完整，默认视图列顺序是否符合口径。

## 3. 查询记录

按条件分页：

```bash
dws aitable record query \
  --base-id <baseId> \
  --table-id <tableId> \
  --field-ids "MNkArlN,dwQg9oA,oWZ5bkr" \
  --filters '{"operator":"and","operands":[{"operator":"exist","operands":["MNkArlN"]}]}' \
  --limit 100 --format json
```

按已知 recordId 精准读取：

```bash
dws aitable record query \
  --base-id <baseId> --table-id <tableId> \
  --record-ids rec1,rec2 --format json
```

注意：

- record query 的单选过滤值传**选项名称字面量**，不是选项 ID。
- 日期过滤使用 `date_eq/before/after/not_before/not_after`。
- 自动翻页用 `--all`；大表必须设置合理 `--page-limit`。
- 公式、lookup、关联字段默认不返回，需要显式加入 `--field-ids`。

## 4. 新增记录

`records.json`：

```json
[
  {
    "cells": {
      "4iqUuLZ": [{"userId": "<staffId>", "corpId": "<corpId>"}],
      "MNkArlN": "张三",
      "dwQg9oA": "招聘岗位",
      "M1ChSRg": {"id": "<optionId>", "name": "通过"},
      "YoQTnWB": "2026-10-09T10:00:00+08:00"
    }
  }
]
```

执行：

```bash
dws aitable record create \
  --base-id <baseId> --table-id <tableId> \
  --records-file ./records.json --format json
```

常见写入格式：

- text/telephone/email：字符串。
- number：数字。
- singleSelect：`{"id":"<optionId>","name":"<选项名>"}`；不确定 ID 时先回读。
- date：RFC3339 或毫秒时间戳。
- user：`[{"userId":"<staffId>","corpId":"<corpId>"}]`。
- url：`{"text":"显示名","link":"https://..."}`。

不存在的单选值可能被自动创建，因此不要在未回读选项时直接写新状态。

## 5. 更新记录

`updates.json`：

```json
[
  {
    "recordId": "rec-001",
    "cells": {
      "7NfUhqb": {"id": "<optionId>", "name": "通过"},
      "rbYLcli": {"id": "<optionId>", "name": "待入职"},
      "oWZ5bkr": {"id": "<optionId>", "name": "待入职"}
    }
  }
]
```

执行：

```bash
dws aitable record update \
  --base-id <baseId> --table-id <tableId> \
  --records-file ./updates.json --format json
```

只传变化字段；未传字段保持原值。候选人从“二面待定”变成“Offer/待入职”时，更新同一个 `recordId`，不能新建第二条。

## 6. 幂等 upsert 流程

1. 查询钉钉现有记录，只取同步所需字段。
2. 优先用状态文件中的 `resumeId + applyJobId -> dingtalk_record_id` 映射。
3. 表内没有外部 ID 字段时，用“姓名 + 手机号 + 岗位”兜底；仍冲突则进异常，不自动写入。
4. 对比内容哈希，拆成 `creates`、`updates`、`unchanged` 三组。
5. 每批最多 100 条，调用 create/update。
6. 成功后把返回的 recordId 和写入时间保存到状态文件。
7. 失败的记录保留在失败队列，下次重试；不重复提交已成功的记录。

## 7. 仪表盘和图表

```bash
dws aitable dashboard get --base-id <baseId> --dashboard-id <dashboardId> --format json
dws aitable chart get --base-id <baseId> --dashboard-id <dashboardId> --chart-id <chartId> --format json
dws aitable chart widgets-example --format json
```

经验规则：

- 图表创建后显示名可能被改成默认名，需要再调用 chart update 修正。
- chart update 是完整配置替换，不能只传一个标题字段。
- 图表过滤里的单选值通常使用选项 ID；记录查询过滤使用选项名称，两者不要混用。
- 图表数据源表必须绑定正确；周度表指标用 field 汇总，台账记录数用 record-count。
- 窗口过窄时只能查看，不能编辑布局；拉宽浏览器后再调整。

## 8. 写后处理

- 周度漏斗和转化率不是公式字段，源数据变化后要重新计算并写入。
- 个人台账更新完成后，再更新周度表和看板。
- 每次同步保留 `sync_report.json`，记录新增、更新、跳过、失败和异常；不记录密码、Cookie、token。
