# Day7 小任务八：最终交付验收报告

小任务八解决的是“所有 Day7 材料都生成以后，我到底能不能把这个 run 当作论文写作的最终证据”的问题。

它不会重新跑实验、不会调用大模型、也不会重新评分；它只读取正式实验目录里已经保存的材料，生成最后一份交付验收报告。

## 生成文件

在正式实验 run 目录中生成：

- `day7_delivery_pack.json`：机器可读的最终交付验收包；
- `day7_delivery_report.md`：人可读的最终交付验收报告。

同时写入 `experiment_manifest.json`：

- `results.day7_delivery_pack_json`
- `results.day7_delivery_report_md`
- `day7_delivery_pack`

## 它检查什么

小任务八把小任务七的投稿归档包作为核心依据，并额外确认：

- `paper_submission_pack.json` 已存在；
- `paper_submission_checklist.md` 已存在；
- 投稿归档包状态是 `submission_ready`；
- 投稿归档包允许写正式论文结论；
- 最终交付文件和关键 Markdown 材料可以记录 SHA-256。

只有当这些都通过，状态才会是：

```json
{
  "delivery_status": "delivery_ready",
  "paper_claims_allowed": true
}
```

如果状态是 `delivery_blocked`，说明不能把这次 run 当作最终论文证据，需要先看 `failed_checks`。

## 单独导出

```powershell
python experiments/export_day7_delivery_pack.py --run-dir experiments/results/formal_runs/<run_id> --min-cases 100 --strict
```

如果 `--strict` 返回非 0，说明 Day7 最终交付还没有准备好。

## 在正式链路中的位置

正式实验全链路现在会按下面顺序生成材料：

1. `formal_preflight_report.json`
2. `benchmark_results.csv/json`
3. `evaluation_summary.json`
4. `paper_analysis.json/md`
5. `formal_experiment_gate.json/md`
6. `paper_result_pack.json/md`
7. `paper_draft_pack.json` 和 `paper_draft.md`
8. `paper_submission_pack.json` 和 `paper_submission_checklist.md`
9. `day7_delivery_pack.json` 和 `day7_delivery_report.md`

也就是说，小任务八是 Day7 的“最后确认单”，不是新的实验方法。

## 你应该怎么看

- `delivery_ready`：可以进入人工论文改稿阶段；
- `delivery_blocked`：先修复阻塞项，不要急着写结论；
- 即使 `delivery_ready`，也仍然需要人工补真实文献、调整《电信科学》模板、核对图表编号。
