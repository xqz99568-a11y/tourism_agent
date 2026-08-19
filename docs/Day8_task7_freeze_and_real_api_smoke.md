# Day8 任务7：正式实验冻结与真实 API 烟测记录

本文件记录 Day8 修复后的最终冻结前检查。它不是正式实验结果，也不包含任何论文结论，只说明当前代码、数据和运行环境是否具备进入正式实验的条件。

## 任务目的

任务7只做三件事：

1. 确认 Day8 代码、题库、评价器、天气快照、铁路快照和预算金标已经通过机器测试；
2. 用一次极小规模真实 API 调用证明中转 API、trace、token、时延和成本记录链路可用；
3. 创建 Git 冻结分支和冻结标签，为后续正式实验提供可复现起点。

## 已执行检查

```powershell
python -m py_compile app\core\experiment_runner.py app\core\formal_experiment_preflight.py app\core\formal_experiment_gate.py app\core\day8_delivery_pack.py app\core\formal_artifact_integrity.py experiments\run_formal_experiment.py experiments\run_real_api_smoke.py experiments\build_day8_delivery_pack.py
python -m pytest tests/test_experiment_runner.py tests/test_day6_formal_run_preflight.py tests/test_day8_delivery_pack.py tests/test_day7_formal_gate.py tests/test_day6_real_api_smoke.py -q
python -m pytest -q
python experiments\build_day8_delivery_pack.py
python experiments\run_real_api_smoke.py --run-id day8_task7_real_api_smoke_20260819T000000Z --timeout 60 --max-tokens 128 --allow-missing-config
```

## 检查结论

- 语法检查通过；
- 最小相关测试通过：83 passed；
- 全量测试通过：727 passed，1 skipped；
- Day8 交付包在 Git 冻结前只剩 `git_worktree_clean` 一项阻塞；
- 真实 API 烟测通过，`connection_verified=true`；
- 真实 API 烟测记录了 token、时延、成本估算和 trace；
- 真实 API 烟测中 `mock=false`、`fallback=false`；
- 已检查烟测证据目录，未发现 API Key 写入结果文件。

## 真实 API 烟测证据

证据目录：

```text
experiments/results/real_api_smoke/day8_task7_real_api_smoke_20260819T000000Z/
```

核心文件：

- `real_api_smoke_manifest.json`
- `real_api_smoke_result.json`
- `token_report.json`
- `latency_report.json`
- `cost_report.json`
- `price_snapshot.json`
- `real_api_smoke_report.md`
- `traces/*.jsonl`

## 论文使用边界

可以写：

- 正式实验前完成了真实 API 连通性烟测；
- 烟测确认 trace、token、时延和标准化成本记录链路可用；
- 正式实验前冻结了代码、题库、评价规则、天气快照、铁路票价快照和预算金标。

不能写：

- 不能把这次烟测当作正式实验结果；
- 不能用烟测结果证明 M3 优于 M2；
- 不能声称正式实验已经完成；
- 不能声称天气或票价是在正式实验运行时实时刷新。

