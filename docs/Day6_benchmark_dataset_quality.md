# Day 6 小任务七：正式 benchmark 数据集质量门禁

本任务补齐的是“案例能否作为论文实验数据”的检查，不调用大模型，也不消耗 API。

## 目的

正式实验不能只保证代码能跑，还必须保证每个案例都有独立评价器能读取的金标。否则 100 个案例跑完后，STSR、Agent F1、Tool F1 等指标会缺失或不可信。

## 新增能力

- `app/core/benchmark_dataset_validator.py`
  - 检查 `case_id` 和多轮 `turn_id` 是否重复；
  - 检查每个单轮案例或多轮 turn 是否有 `user_input`；
  - 检查是否存在 `expected`/`gold` 等金标；
  - 检查 `task_type` 是否属于冻结评价规则目录；
  - 检查 `accepted_agent_sets`、`accepted_tool_sets`、`required_tools`、`forbidden_tools` 是否使用合法 Agent/工具名；
  - 检查旅游任务是否能解析到五城固定离线数据；
  - 检查完整规划、多轮修改、天气调整、澄清、闲聊等任务是否具备必要标注。

- `experiments/validate_benchmark_dataset.py`
  - 独立数据集检查命令，不跑实验、不调用 LLM。

- `app/core/formal_experiment_preflight.py`
  - 正式 preflight 报告新增 `benchmark_quality`；
  - 严格正式模式下，缺金标、非法工具、非法 Agent、不可评价案例会阻止正式运行。

## 使用命令

开发期检查可以先用 warning-only：

```powershell
python experiments/validate_benchmark_dataset.py --benchmark experiments/benchmark_test.json --dev
```

正式 100 案例冻结前必须使用严格检查：

```powershell
python experiments/validate_benchmark_dataset.py --benchmark experiments/benchmark.json --expected-cases 100
```

正式运行前的总闸门仍然是：

```powershell
python experiments/run_formal_experiment.py --benchmark experiments/benchmark.json --expected-cases 100 --preflight-only --skip-llm-config-check
```

## 对标注者的最小要求

每个案例至少要有：

- `case_id`
- `user_input`
- `expected.task_type`
- `expected.accepted_agent_sets`
- `expected.accepted_tool_sets`
- 需要证据的任务要有 `expected.required_tools`
- 闲聊/澄清类任务要禁止生成工具：`expected.forbidden_tools`
- 完整规划要有可程序检查的硬约束，例如 `duration_days`、`min_attractions`、`max_pois_per_day`、`budget_limit`
- 多轮修改要标注 `changed_slots`，建议同时标注 `preserved_slots`

`experiments/benchmark_test.json` 现在只适合作为 smoke 输入；正式论文数据集必须补齐上述标注。
