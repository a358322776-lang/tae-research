# 最终测试集规格模板（final-v1）

> **状态：TEMPLATE-NOT-FROZEN——未冻结。** 本文件只是格式模板，
> 不含任何真实测试数据、不决定任何窗口与标的池。冻结（B3）须
> 单独批准；模板永远不得声称已冻结。

| 字段 | 模板值 | 说明 |
|---|---|---|
| format_version | `test-set-formats-v1` | 格式版本，见 `research-lab/testset_formats.py` |
| test_set_id | `final-v1` | 测试集标识 |
| status | `TEMPLATE-NOT-FROZEN` | 未冻结 |
| universe | `["TBD"]` | 标的池，冻结时单独批准 |
| windows.train | start/end 均为 `null` | 训练窗口占位 |
| windows.validation | start/end 均为 `null` | 验证窗口占位 |
| windows.final_test | start/end 均为 `null` | 最终测试窗口占位 |
| fields | open/high/low/close/volume | 字段列表 |
| exclusion_rules | `["TBD"]` | 排除规则，冻结时确定 |
| freeze_timestamp_ms | `null` | 冻结时间戳，模板中必须为空 |
| new_data_rule | 见正文 | 冻结后新数据自动划入最终测试集，不得用于训练/验证；实际划入动作须冻结事件批准 |

配套格式：`manifest-template.json`（清单格式，文件列表为空）、
`summary-template.json`（摘要格式，仅计数区间）。格式校验与
生成逻辑在 `research-lab/testset_formats.py`，测试在
`research-lab/test_testset_formats.py`。只读访问器、访问日志、
密封与冻结属 B2/B3，未批未建；`data/` 目录保持为空。
