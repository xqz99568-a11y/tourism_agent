# Day6 小任务四：运行审计指标与 M2/M3 原始输出统一

本任务解决正式实验结果是否便于论文复现和制表的问题。

## 实现目标

- 每条实验结果新增 `run_audit`，统一记录 Agent、工具、LLM、API、Token、费用和耗时相关审计指标。
- `run_audit` 只从方法输出和 trace 推导，不读取 gold、expected 或人工答案。
- 关键审计指标同步进入 `metrics`、CSV 和 `evaluation_summary.json`，便于直接生成论文表格。
- M2 `fixed_multi_agent` 与 M3 `adaptive_multi_agent` 的 `raw_output` 也满足 `ctp-experiment-output-v1`，不再只依赖最终 `output` 层补齐 Schema。
- 为兼容多轮复用逻辑，M2/M3 的结构化 `raw_output.raw_output` 保留原始证据快照，包含 `daily_itinerary`、`tool_results` 等字段。

## 代码落点

- `app/core/experiment_run_audit.py`
  - `RUN_AUDIT_SCHEMA_VERSION`
  - `build_run_audit()`
- `app/core/experiment_runner.py`
  - `_build_unified_result()`：构造并挂载 `run_audit`。
  - `_merge_run_audit_metrics()`：把审计指标并入结果 `metrics`。
  - `_attach_run_audit_metadata()`：把审计版本写入输出元数据。
  - `_build_research_method_output()`：让 M2/M3 原始输出满足统一 Schema。
  - `export_csv()` / `_flatten_result_for_csv()`：导出审计列。
- `app/core/independent_evaluator.py`
  - summary 和配对统计增加 LLM 调用、Token、阶段耗时等审计指标。

## 验收标准

小任务四完成后，必须满足：

1. 每条结果都有 `run_audit.schema_version = ctp-run-audit-v1`；
2. Agent/工具调用次数、成功/失败次数、计划-执行覆盖率可从 `run_audit.metrics` 读取；
3. CSV 中有 `run_audit_schema_version`、`agent_call_count`、`called_tool_count`、`successful_tool_call_count` 等审计列；
4. summary 可以聚合 LLM 调用数、Token、Agent/工具耗时等开销指标；
5. M2/M3 的 `raw_output.schema_version` 为 `ctp-experiment-output-v1`；
6. 不改变四方法调度策略、工具顺序、Prompt 或评价器判分规则。
