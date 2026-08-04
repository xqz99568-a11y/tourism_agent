# Day7 小任务六：论文初稿包

## 目的

小任务六解决的是“实验材料已经整理好以后，论文初稿怎么开始写”的问题。

它不会重新跑实验，不会调用大模型，也不会修改实验数字。它只读取已有实验产物，把小任务五的 `paper_result_pack` 继续整理成：

- `paper_draft_pack.json`：机器可读的论文初稿清单；
- `paper_draft.md`：面向《电信科学》投稿方向的中文论文初稿骨架。

它的重点不是替你伪造一篇完整论文，而是把“哪些内容可以直接写、哪些必须人工补、哪些不能夸大”固定下来。

## 新增产物

正式实验 run 目录下会新增：

- `paper_draft_pack.json`
- `paper_draft.md`

同时会把路径写回 `experiment_manifest.json`：

- `results.paper_draft_pack_json`
- `results.paper_draft_md`
- `paper_draft_pack`

## 初稿包含哪些部分

生成的 `paper_draft.md` 包含：

1. 写作状态与证据门禁；
2. 论文定位、研究问题和贡献点；
3. 摘要、关键词、引言、相关工作占位；
4. 方法部分初稿；
5. 实验设计初稿；
6. RQ1/RQ2/RQ3 结果表格；
7. 讨论、局限性、结论模板；
8. 待办清单和禁止夸大的写作边界。

其中“相关工作”和“参考文献”必须由作者人工补真实文献，程序不会自动编造引用。

## 使用命令

如果正式实验已经跑完，并且小任务四、五都已生成：

```powershell
python experiments/export_paper_draft_pack.py --run-dir experiments/results/formal_runs/<run_id> --profile formal --min-cases 100 --strict
```

如果只是调试初稿结构，可以不加 `--strict`：

```powershell
python experiments/export_paper_draft_pack.py --run-dir experiments/results/formal_runs/<run_id> --profile formal --min-cases 100
```

也可以覆盖论文标题：

```powershell
python experiments/export_paper_draft_pack.py --run-dir experiments/results/formal_runs/<run_id> --title "你的论文标题"
```

正式实验脚本和 finalize 脚本已经自动接入该步骤：

```powershell
python experiments/run_formal_experiment.py --expected-cases 100
python experiments/finalize_formal_experiment.py --run-dir experiments/results/formal_runs/<run_id> --min-cases 100 --strict
```

## 论文写作边界

只有当 `paper_draft_pack.json` 中：

```json
{
  "readiness": {
    "paper_claims_allowed": true
  }
}
```

才可以把 `paper_draft.md` 中的结果部分写成正式论文结论。

如果该字段为 `false`，这份文件只能当作论文结构草稿，不能宣称方法优于基线。

