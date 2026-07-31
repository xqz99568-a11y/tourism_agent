# Day 6 小任务六：20 条开发集

本轮补齐的是论文实验用的开发集，不是最终 100/120 条正式测试集。

## 文件分工

- `experiments/ctp120_dev.json`：20 条开发集，当前主要实验调试使用。
- `experiments/benchmark.json`：benchmark 索引文件，当前指向 `ctp120_dev.json`。
- `experiments/benchmark_test.json`：8 条 smoke 集，用于快速检查链路和字段格式。

## 开发集覆盖

`ctp120_dev.json` 包含 20 个 case，其中 6 个是正式多轮场景；展开后共有 26 个评价 turn。

覆盖任务类型：

- `trip_planning`
- `attraction_recommendation`
- `weather_query`
- `budget_query`
- `partial_replan`
- `weather_adjustment`
- `clarification`
- `general_chat`

覆盖离线城市：

- Beijing
- Hangzhou
- Xian
- Shenzhen
- Guilin

## 检查命令

```powershell
python experiments/validate_benchmark_dataset.py --benchmark experiments/ctp120_dev.json --expected-cases 20
python experiments/validate_benchmark_dataset.py --benchmark experiments/benchmark.json --expected-cases 20
python experiments/run_formal_experiment.py --benchmark experiments/benchmark.json --expected-cases 20 --preflight-only --skip-llm-config-check
```

如果后续扩展到正式论文结果集，应复制当前字段口径，增加到 100-120 条，并把 `benchmark.json` 指向冻结后的正式数据文件。
