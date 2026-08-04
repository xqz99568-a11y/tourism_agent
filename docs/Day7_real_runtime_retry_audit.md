# Day7 小任务一：真实参数与重试审计修正

本任务修正的是正式实验中最容易“看起来规范、实际不规范”的部分：报告参数必须等于真实 API 请求参数，重试次数必须完全可审计。

## 已修正内容

- LLM 调用会按以下优先级解析运行参数：
  1. 单次调用显式参数；
  2. client 构造时显式参数；
  3. 当前环境变量；
  4. `settings.llm` 默认值。
- 因此即使 `settings` 模块已经提前加载，正式脚本后续写入的 `LLM_TEMPERATURE=0`、`LLM_TIMEOUT=60`、`LLM_RETRY_MAX_ATTEMPTS=3` 仍会进入真实 API 请求。
- OpenAI 兼容 SDK 内部重试已设置为 `max_retries=0`，避免隐藏调用。
- 项目级重试只允许：
  - HTTP 429；
  - HTTP 5xx；
  - 网络超时。
- 普通 `RuntimeError`、`JSONDecodeError` 等程序/解析错误不会重试。
- 正式实验默认最大尝试次数统一为 3，即“初次请求 + 最多额外重试两次”。
- formal preflight 会拦截 `LLM_RETRY_MAX_ATTEMPTS != 3` 的正式实验。

## 为什么重要

如果 manifest 写的是 `temperature=0`，但真实 API 收到的是 `temperature=0.2`，论文实验就不可复现；如果 SDK 内部还在自动重试，Trace 里看到的调用次数就小于真实请求次数，也会破坏成本和时延审计。

小任务一修完后，正式实验应以 Trace 中的 `request_options` 和 `retry` 为准核对真实参数与重试证据。
