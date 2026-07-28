# Day 5 Step 1：独立评测规则目录

Step 1 只做一件事：冻结论文评测口径。后续代码只能按 `experiments/evaluation_rule_catalog.json` 打分，不能等结果出来后再改规则。

## 固定内容

- 任务类型：完整规划、景点推荐、天气查询、预算查询、多轮修改、天气调整、信息不足追问、闲聊。
- 规则状态：`passed`、`failed`、`na`。`na` 不进入 HCSR 分母。
- STSR：所有适用的 `stsr_gate` 通过，且没有适用的 `hcsr` 失败，案例才算成功。
- HCSR：通过的适用硬约束数量 / 全部适用硬约束数量。
- Agent/工具指标：只用于分析调度正确性和效率，不替代任务成功率。
- P0 修订：新增 `G_FINAL_ANSWER_CONSISTENT`，空最终回答、最终文字与结构化 POI/预算/天气证据不一致时，不能进入成功样本。
- P1 修订：HCSR 始终按金标任务类型选择适用规则；`execution_status` 只允许 `completed`、`failed`、`clarification`，且 `failed` 不进入成功样本。

## 评测器边界

评测器必须独立于生成链路：

- 不看方法名来偏置任务质量评分。
- 不调用 LLM、联网搜索或实时旅游 API。
- 不补全、不重试、不修复方法输出。
- 只读取结构化输出、trace 和固定离线数据证据。
- 工具成功必须有 `research_tool_result_v1` 结果包，不能只凭“调用过工具”的 trace 记录判定成功。
- `research_tool_result_v1` 的 `success` 结果必须包含非空 `data`，且 POI、天气、预算输出必须与工具结果一致；`no_result` 不能支撑已经生成的结构化结果。
- 澄清任务不仅要在元数据声明缺失字段，最终回答也必须真正向用户询问这些字段。
- 天气调整如果能确定受影响日期，`weather_adjustments` 必须覆盖对应日期。
- 原始输出、trace、manifest 和评测报告只追加保存。

## 验收

本步完成后应具备：

- Day5 分支：`paper/day5-independent-evaluator`。
- 机器可读规则目录：`experiments/evaluation_rule_catalog.json`。
- 测试锁定规则 ID、任务覆盖、三态语义和独立评测器边界。

真正逐案例评分逻辑留到 Step 3；Step 2 先补齐方法输出中评测器需要读取的结构化字段。
