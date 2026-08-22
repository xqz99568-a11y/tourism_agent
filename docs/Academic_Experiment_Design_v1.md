# 学术实验设计冻结说明 v2

本文件对应 `experiments/academic_experiment_design_v1.json`，用于把 Day8 后的论文实验边界固定下来。它不包含实验结果，也不调用大模型。

> 说明：文件名仍保留 `_v1`，是为了兼容现有 preflight 和 delivery pack 的固定路径；当前文件内部设计版本已经升级为 `CTP-GMAS-ACADEMIC-DESIGN-v2`。

## 0. v2 相比 v1 增加了什么

v2 不是重新换题，也不是改变论文方法，而是把正式实验运行控制补充冻结：

- 每条 `case × method` 结果在正式运行时启用子进程级硬超时隔离，避免单次中转 API 卡死导致整轮实验停住；
- LLM provider 记录必须从 `LLM_BASE_URL` 推断，VectorEngine 中转 API 统一记录为 `vectorengine_openai_compatible`；
- trace、manifest、real API smoke、price snapshot 中的 provider/cost 口径必须一致；
- 正式 CTP100 全量实验前必须先完成 20 题四方法联调，用来检查 API 稳定性、trace 完整性、耗时/token/成本字段、超时隔离和评价器可计算性；
- API 失败、超时、解析失败等结果必须保留为实验事实，不能选择性删除后重跑到成功。
- 正式结果必须透明报告 Agent 决策归一化诊断指标，区分“大模型原始决策可直接执行”和“经确定性归一化修复后可执行”。

## 1. 为什么要重新冻结实验设计

CTP100 题库已经在 Day8 修复过程中被我们反复检查过：天气、铁路、预算、意图识别和评价金标都围绕它做过修正。因此，论文里不能把 CTP100 描述成“完全未见测试集”。

更严谨的说法是：

> CTP100 是开发后冻结的受控主基准，用于四方法主实验比较。

为了增强论文可信度，额外增加 CTP30 封闭验证集。它只在主实验设计、代码、数据和评价规则冻结后使用，不用于继续调参。

## 2. 数据集分层

| 数据 | 规模 | 用途 | 是否允许调参 |
| --- | ---: | --- | --- |
| CTP20 Dev | 20 案例 | 开发、调试、发现系统问题 | 允许 |
| CTP100 Main | 100 案例 / 130 轮 | 四方法主实验，报告主要表格 | 冻结后不允许 |
| CTP30 Sealed | 30 案例 / 30 轮 | M2 与 M3 的额外封闭验证 | 运行后不允许 |

CTP30 不进入 `experiments/benchmark.json`，也不作为正式主实验入口。它只能通过单独的封闭验证命令使用。

## 3. 方法比较

主实验仍比较四种方法：

- M0：`llm_direct`
- M1：`single_agent`
- M2：`fixed_multi_agent`
- M3：`adaptive_multi_agent`

核心论文比较是 M3 相对 M2。CTP30 封闭验证只运行 M2 和 M3，目的是检查主实验结论方向是否在额外案例上保持一致。

## 4. 统计方案

统计方案在正式结果产生前冻结：

- 主指标：STSR；
- 次指标：HCSR、BPCR、Agent F1、Tool F1、调用次数、Token、时延和标准化估计费用；
- 配对单位：`case_id`；
- 置信区间：95% paired bootstrap；
- 二值指标检验：McNemar；
- 连续指标检验：Wilcoxon signed-rank；
- 多个次要指标采用 Holm-Bonferroni 校正；
- 重复实验必须先按 `case_id` 聚合，不能把重复运行当作更多独立样本。

## 4.1 决策归一化诊断指标

Task F 真实 API 复验显示，多 Agent 决策中存在一部分格式不规范但可由确定性归一化程序修复的情况。因此正式实验必须额外报告以下诊断指标：

- `raw_decision_success_rate`：`raw_decision_success_count / agent_decision_total`，表示模型原始 Agent 决策无需程序修复即可执行的比例；
- `normalizer_recovery_rate`：`normalizer_recovery_count / agent_decision_total`，表示模型原始 Agent 决策不规范、但被确定性归一化程序修复后可执行的比例；
- `pipeline_completion_rate`：`pipeline_completion_count / result_count`，表示 case-method-turn 级结果最终完成的比例。

这些指标只作为系统稳定性和可执行性诊断指标，不作为论文主要效果指标。M0/M1 若不存在多 Agent 决策，则 `agent_decision_total` 为 0，决策率记为 null，但仍统计 `pipeline_completion_rate`。

## 5. 论文表述边界

允许写：

- 本研究在开发后冻结的 CTP100 受控主基准上进行四方法比较；
- 额外使用 CTP30 封闭验证集检查 M3 相对 M2 的结论稳健性；
- 天气、铁路、预算数据均为冻结快照，不在正式实验阶段联网刷新。

禁止写：

- CTP100 是完全未见测试集；
- CTP30 被用于调参后仍作为封闭验证；
- 实验天气或铁路票价是运行时实时数据；
- 只根据系统自评或个案展示证明方法有效；
- 跑出失败后选择性删除或重跑到成功。

## 6. 任务4完成标准

任务4完成后必须满足：

1. `experiments/academic_experiment_design_v1.json` 存在并通过机器校验；
2. `experiments/ctp100_formal_v2.json` 明确声明自身是开发后冻结受控主基准，而不是完全未见测试集；
3. `experiments/ctp30_sealed_validation_v1.json` 存在，且与开发集、烟雾集、Day8开发验收集和 CTP100 无重复/近重复可见输入；
4. `experiments/benchmark.json` 仍只指向 CTP100，不把 CTP30 混入主实验入口；
5. Day8 交付包必须把本设计校验纳入 ready 检查。

## 7. 任务5正式门禁补充

任务5完成后，正式实验还必须通过启动前和结束后的双门禁：

1. 启动前 preflight 检查 CTP100 入口、Day8 delivery pack、Git 清洁状态、冻结数据哈希、评价规则目录哈希和独立评价器代码哈希；
2. 实验 manifest 记录同一份正式证据综合哈希，保证运行时没有换题库、换数据或换评价器；
3. 结束后 final gate 检查 520 条原始方法结果、合法执行状态、trace 完整性、无 API 失败/超时、无 LLM fallback，以及 STSR/HCSR/BPCR 是否可计算；
4. 结果报告必须包含决策归一化诊断指标，缺少 `raw_decision_success_rate`、`normalizer_recovery_rate` 或 `pipeline_completion_rate` 时不得进入论文结论；
5. 结果报告必须区分 `experiment_integrity_passed` 与 `hypothesis_supported`，不得因为假设不被支持而删除或重跑失败结果。

## 8. 任务6断点续跑补充

正式实验允许在程序或中转 API 中断后使用 `--resume` 技术性续跑，但这不是“选择性重跑”。续跑必须满足同一 `run_id`、同一 Git commit、同一题库哈希、同一方法契约、同一模型参数、同一随机种子以及同一天气、铁路和预算金标哈希；否则必须开启新的 run，不能混入原实验。

续跑以 `case_id + turn_id + method + repeat_index` 为唯一键跳过已完成结果。已经保存的失败结果也属于实验证据，不能删除后重跑到成功；最终 gate 会如实判断这些失败是否影响 `experiment_integrity_passed`。
