# Day7 小任务七：论文投稿归档包

## 目的

小任务七解决的是“正式实验、结果材料和论文初稿都生成以后，投稿前到底该检查什么”的问题。

它不会重新跑实验，不会调用大模型，也不会重新评分。它只读取已有正式实验目录，把关键证据集中整理成：

- `paper_submission_pack.json`：机器可读的投稿归档包；
- `paper_submission_checklist.md`：人可读的投稿前检查清单。

你可以把它理解为最后的“装箱单”：实验协议、正式门禁、原始结果、评价汇总、论文结果材料包、论文初稿、trace hash 和复现实验命令都放在同一个清单里。

## 新增产物

正式实验 run 目录下会新增：

- `paper_submission_pack.json`
- `paper_submission_checklist.md`

同时会把路径写回 `experiment_manifest.json`：

- `results.paper_submission_pack_json`
- `results.paper_submission_checklist_md`
- `paper_submission_pack`

## 检查内容

投稿归档包会检查：

- `Phase0_实验协议.md` 是否存在并记录 SHA-256；
- 正式实验核心产物是否齐全；
- `formal_experiment_gate.json` 是否通过；
- `paper_result_pack.json` 是否允许写正式论文结论；
- `paper_draft_pack.json` 和 `paper_draft.md` 是否存在；
- 独立案例数是否达到阈值，默认 100；
- 四种正式方法是否齐全；
- trace 文件是否存在并生成整体 hash；
- 是否记录了 mock LLM 或 silent fallback；
- 还有哪些工作必须人工完成，例如真实文献、期刊模板、图表编号。

## 使用命令

如果正式实验已经跑完，并且小任务四、五、六都已生成：

```powershell
python experiments/export_paper_submission_pack.py --run-dir experiments/results/formal_runs/<run_id> --min-cases 100 --strict
```

如果返回码不是 0，说明这次 run 还不能作为投稿级最终证据。

正式实验脚本和 finalize 脚本已经自动接入该步骤：

```powershell
python experiments/run_formal_experiment.py --expected-cases 100 --strict-paper-readiness
python experiments/finalize_formal_experiment.py --run-dir experiments/results/formal_runs/<run_id> --min-cases 100 --strict
```

## 论文使用边界

只有当 `paper_submission_pack.json` 中：

```json
{
  "readiness": {
    "status": "submission_ready",
    "paper_claims_allowed": true
  }
}
```

才可以把这次正式实验的数字作为论文实验结果使用。

如果状态是 `revision_needed`，只能根据 `failed_checks` 修复链路，不能写成“方法有效”的投稿结论。
