# Day 7 小任务五：20 条开发集真实实验

## 目的

本任务用于把 Day 7 从 8 条 smoke 试跑扩展到完整开发集真实运行。它的作用是发现方法问题、验证 Trace 与成本字段、估算正式实验预算；它不是最终投稿实验结果。

默认实验规模：

- 20 个顶层开发案例；
- 26 个实际对话轮次；
- 4 种方法：`llm_direct`、`single_agent`、`fixed_multi_agent`、`adaptive_multi_agent`；
- 26 × 4 = 104 条原始结果；
- 104 行 CSV；
- 104 个请求级 Trace。

## 冻结运行参数

当前 Day 7 协议要求：

- `EXPERIMENT_STRICT_MODE=true`
- `EXPERIMENT_DISABLE_CACHE=true`
- `TRACE_SAVE_USER_MESSAGE=false`
- `LLM_TEMPERATURE=0`
- `LLM_MAX_TOKENS=4096`
- `LLM_TIMEOUT=60`
- `LLM_RETRY_MAX_ATTEMPTS=3`
- `LLM_REASONING_EFFORT=minimal`
- `EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER=true`

运行脚本会在实验进程内强制设置这些值，避免 shell 中残留的旧环境变量（尤其是 `LLM_MAX_TOKENS=1024`）污染实验。
其中 `EXPERIMENT_DETERMINISTIC_RESEARCH_FINAL_ANSWER=true` 表示：工具证据和结构化 Agent 输出已经生成后，最终答案由确定性渲染器生成，不再额外调用 LLM 生成最终 JSON。这是冻结实验协议的一部分，正式实验也必须保持一致。

## 运行命令

先做不消耗 API 的预检：

```powershell
python experiments\run_day7_dev_experiment.py --preflight-only
```

真实运行：

```powershell
python experiments\run_day7_dev_experiment.py --strict-dev-gate
```

如果只是本地检查脚本和数据结构，暂时没有 LLM Key，可以使用：

```powershell
python experiments\run_day7_dev_experiment.py --preflight-only --skip-llm-config-check
```

## 主要产物

运行目录默认位于：

```text
experiments/results/day7_dev/<run_id>/
```

核心产物包括：

- `benchmark_results.json`：104 条原始结果；
- `benchmark_results.csv`：104 行表格结果；
- `evaluation_summary.json`：开发集评价汇总；
- `paper_tables.md`：论文表格草稿；
- `experiment_manifest.json`：真实运行 manifest；
- `traces/`：104 个请求级 Trace；
- `day7_dev_preflight_report.json`：运行前门禁；
- `day7_dev_gate.json`：开发集证据门禁；
- `day7_dev_report.md`：人类可读验收报告。

## 当前真实状态

旧的 `1024 max_tokens` 开发实验不能作为正常学术实验证据，因为大量调用撞上输出上限。

最终一轮 `4096 max_tokens` 开发集重跑目录为：

```text
experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/
```

该轮已经通过开发集证据门禁：

- 104/104 条结果完整生成；
- 104 个 Trace 完整生成；
- 四种方法各 26 条；
- `max_tokens=4096` 运行参数检查通过；
- Mock、fallback、cache hit 均为 0；
- 输出上限命中率为 0.0%，低于 5% 门限；
- `empty_and_token_capped_call_count=0`；
- `day7_dev_gate.json` 中 `status=passed`，`failed_checks=[]`。
- manifest 与 gate 均已记录 `deterministic_research_final_answer=true`。

该轮仍记录 1 条 `single_agent` 基础设施失败，原因是一次真实连接错误触发实验看门狗超时；开发集基础设施失败率为 0.96%，低于 5% 门限，因此不阻塞 Day 7 开发集验收。开发集结果仍只用于方法修正、成本外推和进入正式实验前的诊断，不应写成最终论文主实验结论。

本轮开发集评价中，M3（`adaptive_multi_agent`）达到：

- STSR：1.0；
- HCSR：1.0；
- Agent 选择 F1：1.0；
- Tool 选择 F1：1.0。

M3 已达到小任务四中预先规定的开发集关闭门限：STSR ≥ 0.70，且 HCSR 不低于 M2。

## 验收口径

`day7_dev_gate.json` 会检查：

1. 原始结果是否为 `26 × 4 = 104`；
2. CSV 是否为 104 行；
3. 每种方法是否各有 26 条结果；
4. 四方法逐轮配对是否完整；
5. 多轮案例状态是否按“同方法、同案例、同 repeat”隔离；
6. Mock、fallback、cache hit 是否为 0；
7. Trace 数量是否为 104；
8. manifest 参数是否与请求级 Trace 一致；
9. token、费用、时延字段是否完整；
10. 输出上限风险是否低于协议门限；
11. 是否存在“空正文且撞上输出上限”的调用。

方法真实失败不会被美化。如果 M3 质量仍低于 M2，开发集结果只能用于诊断和修正，不能直接写成论文最终结论。
