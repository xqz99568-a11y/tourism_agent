# Day6 小任务三：M0/M1 结构化输出与工具证据

本任务解决 M0/M1 在正式实验中的输出可审计问题。

## 实现目标

- M0 `llm_direct` 必须直接返回 `ctp-experiment-output-v1` 严格 JSON；程序只解析和验证，不再把自由文本包装成成功结果。
- M1 `single_agent` 的最终回答也必须是严格 JSON；任务内容字段由 M1 生成，Agent/工具证据字段由程序注入。
- M0/M1 JSON 解析失败、缺少必需字段或字段类型错误时，方法输出必须标记为 `failed`，不能自动修复为成功。
- M1 的 `tool_results` 只能来自 `ToolExecutor.execute()` 的真实返回，或工具参数解析失败时生成的标准失败记录，不能从最终回答文本反推。
- 约束检查器和独立评估器使用同一份 `tool_results` 判断工具证据。
- 工具调用失败时，M1 的方法输出、统一输出和实验行状态都必须标记为 `failed`。

## 代码落点

- `app/core/experiment_runner.py`
  - `_run_llm_direct()`：要求 M0 直接生成统一 JSON，并解析失败即失败。
  - `_run_single_agent()`：要求 M1 工具循环结束后输出统一 JSON，并收集 `planned_tools`、`called_tools` 和真实 `tool_results`。
  - `_parse_strict_structured_llm_json()`：只接受严格 JSON 对象，不抽取 Markdown 代码块，不做文本修复。
  - `_structured_llm_validation_errors()`：校验 M0/M1 必需字段、字段类型，以及 M0 不得包含 Agent/工具证据。
  - `_build_structured_llm_method_output()`：把 LLM 生成的任务内容和程序注入的证据合并为统一实验输出。
  - `_single_agent_tool_result_payload()`：把真实工具结果标准化为可审计字典。
  - `_failed_single_agent_tool_result()`：记录工具参数解析失败等未成功工具行为。

## 测试落点

- `tests/test_day6_m0_m1_structured_output.py`
- `tests/test_experiment_runner.py`
- `tests/test_research_tools.py`
