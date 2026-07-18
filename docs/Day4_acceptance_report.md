# Day 4 验收报告说明

Day 4 的验收对象是“目标—状态驱动调度 + 真实复用统计”，不是简单关键词分流。

本轮修复后，正式验收重点如下：

- 旧结果不能只凭 `available_results` 标记复用，必须存在真实工具结果或真实 `daily_itinerary`，并且状态成功、输入指纹匹配。
- `status=expired` / `stale` 的历史结果不能复用。
- `preferences=[]`、`budget=None` 在有上一轮状态时表示“取消偏好/取消预算限制”，必须进入槽位变化。
- “same conditions, regenerate” 这类请求必须按重新生成处理，不能被“same”误判为完全相同请求。
- 同时修改多个条件时，必须先合并所有失效影响，再决定执行和复用。
- 上游工具失败后，依赖它的下游 Agent 必须停止执行；预算不能拿空景点列表伪成功。
- 单项天气/景点/澄清任务不能生成假的 itinerary 指纹。
- `metadata.result_agents` 只能记录真实产出的 Agent 结果，不能等同于 planned agents。
- M3 复用指标只能来自实际复用结果，不能在实际复用为空时回退到“调度声称复用”。
- LLM 整理答案超时或异常时，M3 调度指标必须能从持久化 trace 中恢复。
- 不同 `repeat_index` 必须使用隔离的实验 session_id；同一多轮链路则沿用上一轮 session_id。
- Scheduler 证据必须进入 JSONL trace，包括 ticket、decision、reuse_execution、result_fingerprints。
- Day4 manifest 必须记录 git commit、工作树状态、源代码/测试/案例 SHA-256、输出文件 SHA-256 和代表性持久化 trace。

独立验收命令：

```bash
python experiments/run_day4_acceptance.py
```

脚本会创建唯一目录：

```text
experiments/results/day4_acceptance/<run_id>/
```

目录内包含：

- `day4_acceptance_manifest.json`
- `day4_acceptance_report.md`
- `representative_results.json`
- `traces/*.jsonl`
- `compile_day4_modules.stdout.txt`
- `compile_day4_modules.stderr.txt`
- `pytest_day4_scheduler_and_runner.stdout.txt`
- `pytest_day4_scheduler_and_runner.stderr.txt`

正式证据以脚本生成的 manifest、report 和 JSONL trace 为准。
