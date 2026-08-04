# Day7 小任务四：正式实验证据门禁与结果冻结

## 目的

小任务四解决的是正式实验跑完后的最后一个问题：

> 这些结果现在能不能作为论文证据？

前面的 preflight 只回答“实验能不能开始跑”。小任务四回答“实验跑完后，结果是否完整、可复现、可投稿前检查”。

它不会重新调用大模型，也不会重新评分，只读取已经保存的实验产物。

## 新增产物

正式实验 run 目录下会新增：

- `formal_experiment_gate.json`：机器可读的最终门禁结果
- `formal_experiment_report.md`：人可读的最终门禁报告
- `paper_analysis.json`
- `paper_analysis.md`

同时会把这些路径写回 `experiment_manifest.json`。

## 检查内容

formal gate 会检查：

- `formal_preflight_report.json` 是否存在且通过；
- `benchmark_results.csv/json`、`evaluation_summary.json`、`paper_tables.md`、`experiment_manifest.json` 是否存在；
- `paper_analysis.json/md` 是否存在；
- 独立案例数是否达到阈值，默认 100；
- 四种方法是否都存在；
- M3 与 M2 是否存在配对比较；
- result count 与 preflight 预期是否一致；
- 每条结果是否有 `run_audit`；
- 每条结果是否有论文需要的核心指标；
- trace 证据是否存在；
- 是否记录 LLM 调用；
- 是否误用了 mock LLM；
- 是否出现 silent fallback；
- manifest 是否记录 strict mode 和禁用缓存；
- trace 是否没有保存用户原文；
- method fairness contract 是否记录；
- 核心实验产物是否生成 SHA-256 哈希。

## 使用命令

如果正式实验已经跑完：

```powershell
python experiments/finalize_formal_experiment.py --run-dir experiments/results/formal_runs/<run_id> --min-cases 100 --strict
```

如果返回码不是 0，说明这次 run 还不能写成论文正式结论。

正式实验脚本也已经自动接入该门禁：

```powershell
python experiments/run_formal_experiment.py --expected-cases 100
```

如果希望正式实验脚本在结果不可投稿时直接返回失败：

```powershell
python experiments/run_formal_experiment.py --expected-cases 100 --strict-paper-readiness
```

## 论文使用边界

- `formal_experiment_gate.status = passed`：可以把已测指标写入论文实验结果。
- `formal_experiment_gate.status = failed`：只能用于调试，不能作为论文结论。
- pilot 结果即使完整，也仍然不是正式实验证据。
