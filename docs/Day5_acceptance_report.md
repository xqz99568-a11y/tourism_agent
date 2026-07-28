# Day 5 验收报告说明

Day 5 的验收对象是“独立评价器 + 评价汇总 + 可复现实验证据链”，不是验证生成答案质量本身。

独立验收命令：

```bash
python experiments/run_day5_acceptance.py
```

脚本只使用固定离线验收数据：

- `experiments/day5_evaluation_acceptance_cases.json`
- `experiments/evaluation_rule_catalog.json`

每次运行会在独立目录下生成：

- `benchmark_results.csv`
- `benchmark_results.json`
- `evaluation_summary.json`
- `paper_tables.md`
- `experiment_manifest.json`
- `day5_acceptance_report.md`
- `traces/*.jsonl`

验收重点：

1. 验收数据覆盖规则目录声明的 8 类任务：完整规划、景点、天气、预算、多轮修改、天气调整、澄清、闲聊；
2. 四种方法均能产出统一实验结果；
3. 每条结果均包含独立评价报告；
4. summary 能按方法汇总 STSR、HCSR、Agent/Tool F1、完全匹配率、必要覆盖率、多余/重复调用、计划-实际一致率、执行成功率、Token 和费用字段；
5. summary 同时生成 `paired_statistics`，包含中位数、IQR、95% bootstrap CI、STSR 的 McNemar 检验和连续指标的 Wilcoxon 符号秩检验；
6. 重复实验先按 `case_id` 聚合，再进入方法汇总和 M3/M2 配对统计；
7. P0/P1 评价门槛会拦截错误 Schema、非法执行状态、重复 POI、缺少可验证工具结果、空工具结果、工具结果与输出矛盾、失败工具结果、天气调整错天数、澄清文本未真正追问、最终文本为空或与结构化证据冲突的输出；
8. summary 区分 `unique_case_count`、`method_case_count` 和 `raw_run_count`，避免把“方法 × 案例”误写成独立案例数；
9. manifest 记录评价器版本、规则目录 ID、规则目录路径和规则目录哈希；
10. 输出目录不可覆盖，旧验收结果只读保留。
