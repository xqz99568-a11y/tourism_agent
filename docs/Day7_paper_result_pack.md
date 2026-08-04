# Day7 小任务五：论文实验材料包

## 目的

小任务五解决的是“实验已经跑完、门禁也检查完以后，论文该怎么安全地写结果”的问题。

它不会重新调用大模型，也不会重新评分，只读取已有实验产物，把结果整理成两个文件：

- `paper_result_pack.json`：机器可读的论文材料包；
- `paper_result_pack.md`：可以直接给人看的论文写作材料。

这个材料包的核心作用是把结果按 RQ1/RQ2/RQ3 整理好，并明确告诉你哪些结论能写、哪些不能写。

## 新增产物

正式实验 run 目录下会新增：

- `paper_result_pack.json`
- `paper_result_pack.md`

同时会把路径写回 `experiment_manifest.json`：

- `results.paper_result_pack_json`
- `results.paper_result_pack_md`
- `paper_result_pack`

## 它整理哪些内容

材料包按三类研究问题组织：

| 研究问题 | 对应含义 | 主要证据 |
|---|---|---|
| RQ1 | M3 是否正确选择 Agent 与工具 | Agent F1、Tool F1、M3/M2 配对统计 |
| RQ2 | M3 是否保持任务正确性 | STSR、HCSR、失败规则 |
| RQ3 | M3 是否降低执行开销 | LLM 调用、Agent 调用、工具调用、Token、成本、时延 |

材料包还会生成：

- 可复制到论文初稿的结果描述段落；
- M3 与 M2 的方法比较段落；
- 局限性段落；
- 允许写入论文的结论边界；
- 禁止夸大的结论边界；
- artifact 路径、trace 数量和哈希摘要。

## 使用命令

如果正式实验已经跑完，并且小任务四的 formal gate 已经生成：

```powershell
python experiments/export_paper_result_pack.py --run-dir experiments/results/formal_runs/<run_id> --profile formal --min-cases 100 --strict
```

如果只是本地调试，可以不加 `--strict`：

```powershell
python experiments/export_paper_result_pack.py --run-dir experiments/results/formal_runs/<run_id> --profile formal --min-cases 100
```

正式实验脚本和 finalize 脚本已经自动接入该步骤：

```powershell
python experiments/run_formal_experiment.py --expected-cases 100
python experiments/finalize_formal_experiment.py --run-dir experiments/results/formal_runs/<run_id> --min-cases 100 --strict
```

## 论文写作边界

只有当 `paper_result_pack.json` 中：

```json
{
  "readiness": {
    "paper_claims_allowed": true
  }
}
```

才可以把其中的结果写成正式论文结论。

如果该字段为 `false`，材料包只能用于调试和准备写作框架，不能写成“本文方法优于基线”的正式结论。

