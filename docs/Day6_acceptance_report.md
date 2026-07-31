# Day6 离线验收证据索引

本文件记录仓库内正式保存的 Day6 离线验收运行。它不是论文正式模型质量结果，只证明 Day6 实验基础设施、四方法链路、任务类型对齐、审计字段、成本字段和 trace 保存闭环已经跑通。

## 正式保存的运行

- run_id：`day6_acceptance_official_20260731T042300Z`
- 运行目录：`experiments/results/day6_acceptance/day6_acceptance_official_20260731T042300Z`
- 验收状态：`passed`
- 验收级别：`infrastructure_acceptance`
- 学术质量状态：`not_evaluated_with_fake_llm`
- 原始运行数：44
- 目标评价单元：32
- 任务类型对齐：32/32 通过，0 个 mismatch
- trace 文件数：44
- git commit：见运行目录下 `experiment_manifest.json`

## 已保存文件

- `benchmark_results.json`
- `benchmark_results.csv`
- `evaluation_summary.json`
- `paper_tables.md`
- `experiment_manifest.json`
- `day6_acceptance_report.md`
- `day6_acceptance_benchmark.json`
- `traces/*.jsonl`

## 使用边界

这次运行使用 `Day6OfflineLLM`，不调用外部 LLM 或旅游 API。因此：

1. 可以作为 Day6 离线链路验收证据；
2. 可以证明结果文件、manifest、paper tables、成本字段、token 字段和 trace 能正式保存；
3. 可以证明任务类型阻断门槛已生效；
4. 不能把 FakeLLM 下的 STSR 当作论文正式效果指标。

正式论文实验仍需使用真实模型或明确的人工/规则评价流程重新运行。
