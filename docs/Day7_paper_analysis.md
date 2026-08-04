# Day7 小任务三：实验结果论文分析包

## 目的

小任务三解决的是“跑完实验以后，如何把结果整理成论文能用的证据”的问题。

它不重新调用大模型、不重新评分、不改变四种方法的实现，只读取已经保存的实验结果：

- `benchmark_results.json`
- `benchmark_results.csv`
- `evaluation_summary.json`
- `paper_tables.md`
- `experiment_manifest.json`
- `traces/`
- 如果是 Day7 pilot，还会读取 `day7_pilot_gate.json`

然后生成两个新文件：

- `paper_analysis.json`：机器可读的论文分析证据包
- `paper_analysis.md`：人可读的论文分析报告

## 为什么需要这一层

原来的 `paper_tables.md` 主要是表格；它能展示分数，但不能清楚回答这些投稿前必须检查的问题：

1. 这次运行是不是 pilot，还是正式实验？
2. pilot 结果能不能写进论文结论？
3. 正式实验是否满足最小样本量？
4. 四种方法是否都跑了？
5. M3 和 M2 是否有可配对比较？
6. 是否误用了 mock LLM？
7. 是否出现 fallback？
8. strict mode、禁用缓存、trace 脱敏是否被记录？
9. M3 相对 M2 的 token、调用次数、成本、时延节省率是多少？
10. 主要失败规则集中在哪些任务上？

小任务三就是把这些问题变成固定的、可复查的文件。

## 使用命令

Day7 pilot 跑完后会自动生成分析包，不需要额外命令。

如果要手动分析某一次运行：

```powershell
python experiments/analyze_experiment_run.py --run-dir experiments/results/day7_pilot/<run_id>
```

正式 100–150 案例实验跑完后，建议使用严格模式：

```powershell
python experiments/analyze_experiment_run.py --run-dir experiments/results/formal_runs/<run_id> --profile formal --min-cases 100 --strict-readiness
```

如果 `--strict-readiness` 返回非 0，说明这次运行还不能作为论文正式实验结论。

## readiness 状态含义

| 状态 | 含义 | 是否能写成论文结论 |
|---|---|---|
| `analysis_only` | pilot 证据完整，可用于调试和小样本检查 | 否 |
| `ready` | 正式实验满足复现与证据要求 | 是，只能写已测指标 |
| `not_ready` | 正式实验存在缺失项 | 否 |
| `failed` | pilot 或分析输入存在失败检查 | 否 |

## 论文里应该怎么用

正式实验通过后，优先使用：

- `paper_tables.md`：放入论文表格初稿
- `paper_analysis.md`：写实验分析段落
- `paper_analysis.json`：保留为可复现实验证据
- `experiment_manifest.json`：写实验设置、模型配置、数据集哈希、运行配置

注意：pilot 的 `paper_analysis.md` 只能用于检查链路，不应该写成“本文方法优于基线”的结论。
