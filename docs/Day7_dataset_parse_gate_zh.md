# Day 7 小任务二：数据解析门禁与中文口径

本任务把实验数据从“格式上能跑”提升为“可用于论文实验的可审计数据”。

## 已加入的硬门禁

- 中文输入口径：严格模式下，每个可评估轮次的 `user_input` 必须是中文。
- 解析一致性：自然语言解析出的槽位必须与 `expected`/`hard_constraints`/`current_slots` 中的金标一致。
- 多轮变更审计：`changed_slots` 标注的槽位，必须能从当前用户话语中解析出新值。
- 多轮保持审计：`preserved_slots` 标注的槽位，必须能从上一轮可见历史中恢复，且当前话语不能给出冲突值。
- 数据集重复审计：检查当前数据集内部完全重复输入。
- 跨集合重复审计：支持通过 `comparison_files` 或命令行 `--compare-with` 检查开发集、烟雾集、正式测试集之间的重复输入。
- 高度近似审计：使用相似度阈值发现高度模板化、几乎重复的案例。
- 离线可行性审计：逐案例检查五城固定离线数据是否支持目标城市、天气场景、天数、景点数量等约束。

## 当前数据状态

- `experiments/ctp120_dev.json`
  - 数据版本：`2026-07-31-zh`
  - 20 个案例；
  - 26 个实际轮次；
  - 中文轮次比例：100%。

- `experiments/benchmark_test.json`
  - 数据版本：`2026-07-31-zh`
  - 8 个案例；
  - 10 个实际轮次；
  - 中文轮次比例：100%；
  - 已通过 `comparison_files: ["ctp120_dev.json"]` 与开发集做跨集重复检查。

## 推荐命令

```powershell
python experiments/validate_benchmark_dataset.py --benchmark experiments/ctp120_dev.json --expected-cases 20
python experiments/validate_benchmark_dataset.py --benchmark experiments/benchmark_test.json
```

正式测试集冻结前，建议：

```powershell
python experiments/build_day7_test_draft.py --strict
python experiments/validate_benchmark_dataset.py --benchmark experiments/benchmark.json --expected-cases 100
```
