# Day7 小任务三：真实模型 8 条烟雾实验

## 目的

Day7 pilot 用来在正式 100–150 条实验前，先证明“真实模型 + 四种方法 + 中文烟雾集 + Trace + 成本审计 + 结果门禁”整条链路能跑通。

这一步不是论文正式实验，不用它直接写论文结论；它的作用是暴露工程链路问题，确保后面正式实验不会把 API 额度浪费在错误配置上。

## 默认规模

`experiments/run_day7_pilot.py` 默认使用 `experiments/benchmark_test.json` 的完整中文烟雾集：

- 8 个顶层烟雾案例；
- 其中 2 个是双轮案例；
- 展开后共 10 个实际评测轮次；
- 4 种方法：`llm_direct`、`single_agent`、`fixed_multi_agent`、`adaptive_multi_agent`；
- 因此应生成 40 条原始结果；
- 每条原始结果应对应 1 个请求级 Trace，因此应生成 40 个 Trace 文件。

## 推荐命令

只做 preflight，不调用真实模型：

```powershell
python experiments/run_day7_pilot.py --preflight-only
```

运行真实模型 pilot：

```powershell
python experiments/run_day7_pilot.py
```

如果只是本地调试，也可以临时缩小规模，但缩小规模的结果不能作为 Day7 小任务三完成证据：

```powershell
python experiments/run_day7_pilot.py --max-cases 1 --methods fixed_multi_agent,adaptive_multi_agent
```

## 运行前环境要求

正式 pilot 默认会启用以下运行口径：

- `EXPERIMENT_STRICT_MODE=true`
- `EXPERIMENT_DISABLE_CACHE=true`
- `TRACE_SAVE_USER_MESSAGE=false`
- `LLM_TEMPERATURE=0`
- `LLM_MAX_TOKENS=4096`
- `LLM_TIMEOUT=60`
- `LLM_RETRY_MAX_ATTEMPTS=3`

同时必须存在可用的真实模型配置，例如：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`

当前项目目标配置为 OpenAI-compatible 中转接口和 `gpt-5-mini`。

## 验收产物

真实 pilot 成功后，运行目录位于：

```text
experiments/results/day7_pilot/<run_id>/
```

关键文件包括：

- `benchmark_results.csv`
- `benchmark_results.json`
- `evaluation_summary.json`
- `paper_tables.md`
- `experiment_manifest.json`
- `day7_pilot_preflight_report.json`
- `day7_pilot_gate.json`
- `day7_pilot_report.md`
- `paper_analysis.json`
- `paper_analysis.md`
- `day7_issue_report.json`
- `day7_fix_report.md`
- `traces/*.jsonl`

`day7_pilot_gate.json` 必须显示：

- `status = passed`
- `expected_result_count = 40`
- `actual_result_count = 40`
- `pilot_structure.case_count = 8`
- `pilot_structure.total_turn_count = 10`
- `pilot_structure.expected_trace_count = 40`
- `pilot_structure.actual_trace_file_count = 40`
- `checks.request_level_trace_count_matches = true`
- `checks.loaded_trace_count_matches = true`
- `checks.runtime_audit_recorded = true`
- `checks.mock_policy_satisfied = true`
- `checks.no_llm_fallback_recorded = true`

部分澄清或闲聊类样本在某些方法下可能没有业务 Agent，因此不强制每一个请求级 Trace 都包含 LLM 调用；但只要发生了 LLM 调用，就必须记录真实模型、运行参数、重试、token、时延和费用，且不能是 Mock 或 fallback。

`day7_issue_report.json` 和 `day7_fix_report.md` 属于 Day7 小任务四产物，用来把真实 pilot 暴露的问题按“基础设施错误、实验实现错误、方法真实失败”三类归档。它们不修改模型输出，也不把 pilot 分数升级为论文正式结果。

## 注意

这一步只验证真实实验链路和证据完整性，不强制要求 STSR、Agent F1、Tool F1 达到论文阈值。质量指标会保存下来，用于检查方法是否明显异常；正式论文结论仍以后续 100–150 条冻结测试集为准。
