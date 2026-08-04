# Day 6 小任务六：20 条开发集

本轮补齐的是论文实验用的开发集，不是最终 100/120 条正式测试集。

## 文件分工

- `experiments/ctp120_dev.json`：20 条开发集，当前主要实验调试使用。
- `experiments/benchmark.json`：benchmark 索引文件，Day 7 小任务七后已指向正式测试集草稿 `ctp120_test_draft.json`；开发集仍由 Day7 开发集脚本显式读取 `ctp120_dev.json`。
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
python experiments/validate_benchmark_dataset.py --benchmark experiments/benchmark.json --expected-cases 100
python experiments/run_formal_experiment.py --benchmark experiments/benchmark.json --expected-cases 100 --preflight-only --skip-llm-config-check
```

如果需要继续复现 20 条开发集，请直接使用 `experiments/ctp120_dev.json` 或 `experiments/run_day7_dev_experiment.py`；不要再把开发集结果当作正式测试集结论。
