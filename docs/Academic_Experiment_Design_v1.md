# 学术实验设计冻结说明 v1

本文件对应 `experiments/academic_experiment_design_v1.json`，用于把 Day8 后的论文实验边界固定下来。它不包含实验结果，也不调用大模型。

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
4. 结果报告必须区分 `experiment_integrity_passed` 与 `hypothesis_supported`，不得因为假设不被支持而删除或重跑失败结果。

## 8. 任务6断点续跑补充

正式实验允许在程序或中转 API 中断后使用 `--resume` 技术性续跑，但这不是“选择性重跑”。续跑必须满足同一 `run_id`、同一 Git commit、同一题库哈希、同一方法契约、同一模型参数、同一随机种子以及同一天气、铁路和预算金标哈希；否则必须开启新的 run，不能混入原实验。

续跑以 `case_id + turn_id + method + repeat_index` 为唯一键跳过已完成结果。已经保存的失败结果也属于实验证据，不能删除后重跑到成功；最终 gate 会如实判断这些失败是否影响 `experiment_integrity_passed`。
