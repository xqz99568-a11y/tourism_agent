# Day 7 小任务六：成本预测与模型冻结

## 目的

本任务使用真实开发集运行结果回答三个问题：

1. 四种方法分别消耗多少 Token、费用和时延；
2. 按 100 个统计案例、约 130 个实际轮次、520 条“轮次—方法”结果外推，正式实验大概需要多少钱；
3. 成本和运行参数是否足够稳定，可以冻结模型与实验参数。

这份报告只处理“成本与运行参数冻结”，不代表方法质量已经达到投稿水平。

## 当前冻结参数

当前 Day 7 协议为：

- 模型：`gpt-5-mini`
- temperature：`0`
- max_tokens：`4096`
- timeout_seconds：`60`
- retry_max_attempts：`3`
- reasoning_effort：`minimal`
- deterministic_research_final_answer：`true`
- strict_mode：`true`
- cache_disabled：`true`
- 价格快照：输入 `$0.25 / 1M tokens`，输出 `$2.00 / 1M tokens`
- 价格来源 URL：`https://api.vectorengine.ai/pricing`
- USD→CNY 汇率：`7.30`

说明：正式运行前如果价格变化，应通过脚本参数显式更新价格快照，而不是让代码隐式漂移。

## 运行命令

对指定开发集 run 生成成本报告：

```powershell
python experiments\freeze_day7_cost_model.py `
  --run-dir experiments\results\day7_dev\<run_id> `
  --strict-freeze
```

如果不加 `--strict-freeze`，脚本仍会生成报告，但不会把失败状态伪装成已冻结。

## 当前真实状态

旧开发集 `day7_dev_gpt5mini_repair2_20260802T053000Z` 的成本文件不能作为冻结证据，因为当时 Trace 中标准化费用为 0，价格来源是默认零价格。

最终成本冻结基于以下开发集目录：

```text
experiments/results/day7_dev/day7_dev_gpt5mini_4096_final14_detanswer_20260803T1410CST/
```

该轮已经产生非零价格快照和非零标准化成本估算：

- 开发集估算费用：`4.468857 CNY`；
- 正式 100 案例 / 约 520 条结果线性外推：`22.344285 CNY`；
- 含 10% 网络与重试余量的正式实验预算：`24.578714 CNY`；
- 两周总预算估算：`34.410199 CNY`；
- 预算门限通过：开发集 ≤15 元，正式实验 ≤75 元，两周总预算 ≤150 元。

重新生成后的成本报告已经通过冻结门禁：

- `status=passed`
- `paper_claims_allowed=false`
- `freeze_status=frozen_for_cost_and_runtime`
- `rerun_required=false`
- `failed_checks=[]`
- 216 次 LLM 调用中，Trace 价格来源均不是 `zero_default`；
- `trace_standardized_cost_sum=0.61217225 USD`；
- `empty_and_token_capped_call_count=0`。
- `deterministic_research_final_answer=true` 已纳入运行时冻结检查。

注意：这里的费用是“真实 Token 用量 × 冻结价格快照”的标准化估算，不是 API 供应商返回的真实账单。当前成本、Token、价格快照和运行参数已经可以冻结；论文主实验结论仍必须来自后续 100 案例正式实验。

## 论文写作边界

可以写：

- 使用统一模型与统一参数；
- 使用固定价格快照进行标准化成本估算；
- 使用开发集真实 Token 统计线性外推正式实验预算；
- 当前预算低于两周实验预算上限；
- 成本与运行参数在 Day 7 开发集证据上已冻结。

不能写：

- 当前开发集结果已经可作为最终论文实验；
- 当前成本报告证明 M3 方法质量优于 M2；
- 标准化估算费用就是 API 供应商真实账单；
- 忽略“开发集只是诊断集，正式结论需等 100 案例主实验”的边界。

## 下一步

成本冻结已经完成。下一步不再是为成本继续重跑，而是使用同一版最终代码、同一组冻结参数进入 100 案例正式实验；如果投稿前供应商价格发生变化，需要显式更新价格快照并重新生成成本报告。
