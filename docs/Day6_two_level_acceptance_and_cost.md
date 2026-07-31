# Day6 两级验收与成本闭环

本阶段把验收拆成两层，避免把可复现的离线验收和不稳定的真实 API 连接混在一起。

## 1. FakeLLM 离线验收

命令：

```bash
python experiments/run_day6_acceptance.py
```

目标：

- 覆盖 8 类质量评价任务：完整规划、景点、天气、预算、多轮局部修改、天气调整、澄清、闲聊。
- 四种方法都运行这些质量单元，因此至少形成 `8 × 4 = 32` 个方法—案例评价单元。
- 多轮场景还会先真实执行预备轮，因此原始运行数大于 32。
- FakeLLM 的 trace 必须记录 `mock=true`，不能伪装成真实模型。
- 每次 LLM 调用必须记录 token、时延、Prompt 版本、Prompt 哈希和成本字段。

## 2. 真实 API 烟雾验收

命令示例：

```bash
$env:LLM_API_KEY="你的中转API Key"
$env:LLM_BASE_URL="https://api.vectorengine.ai/v1"
$env:LLM_MODEL="你要使用的模型名"
$env:LLM_PRICE_INPUT_PER_1K="按价格快照填写"
$env:LLM_PRICE_OUTPUT_PER_1K="按价格快照填写"
$env:LLM_PRICE_SNAPSHOT_DATE="2026-07-30"
$env:LLM_PRICE_SOURCE_URL="https://api.vectorengine.ai/pricing"
python experiments/run_real_api_smoke.py
```

生成文件：

- `real_api_smoke_result.json`：连接结果和响应摘要。
- `traces/*.jsonl`：真实调用 trace。
- `token_report.json`：输入、输出、总 token。
- `latency_report.json`：总时延、首 token 时延、LLM 调用时延。
- `cost_report.json`：实际费用可用性、标准化估算费用、价格快照。
- `real_api_smoke_manifest.json`：运行配置、价格快照和报告路径。

如果没有 `LLM_API_KEY`，脚本只会生成 `skipped` 证据；这不能作为真实 API 连接成功证明。

## 3. 成本字段口径

- `actual_cost`：供应商响应直接返回的费用；若供应商不返回则为 `null`，并记录 `actual_cost_status=not_reported_by_provider`。
- `standardized_estimated_cost`：用实际 token 数和本次运行冻结的价格快照计算出来的可复现实验费用。
- `estimated_cost`：当前与 `standardized_estimated_cost` 保持一致，用于兼容既有评价器和论文表格。
- FakeLLM 的 `actual_cost=0`，价格策略为 `mock_zero_cost`。

论文正式实验应优先报告 `standardized_estimated_cost`，并在实验设置中说明价格快照日期、来源 URL 和输入/输出 token 单价。
