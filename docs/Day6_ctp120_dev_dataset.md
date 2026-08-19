# Day 6 小任务六：20 条开发集

本轮补齐的是论文实验用的开发集，不是最终 CTP100 正式主基准。

## 文件分工

- `experiments/ctp120_dev.json`：20 条历史开发集，当前只用于调试、回归和跨集重复检查。
- `experiments/benchmark.json`：正式主实验入口，当前只指向 `experiments/ctp100_formal_v2.json`；旧 `experiments/ctp120_test_draft.json` 仅作为历史草稿保留，不再作为正式入口。
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
