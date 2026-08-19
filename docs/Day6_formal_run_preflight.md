# Day6 小任务六：正式实验运行闸门与多轮状态链路

本任务解决“离线验收能跑”到“正式实验可以安全跑”的最后一段距离。

## 实现目标

- 正式 benchmark 运行前必须先通过 preflight 检查，避免数据、环境或输出目录错误浪费 API。
- 支持多轮场景 `turns`：上一轮状态只能来自同一方法上一轮真实输出，不能从金标或手写 `previous_state` 注入。
- CSV、JSON 和 manifest 记录 `scenario_id`、`turn_id`、`turn_index`，便于论文复现实验规模。
- 旧入口 `experiments/run_pilot.py` 转为正式四方法入口，避免继续只跑旧的三方法配置。

## 代码落点

- `app/core/experiment_runner.py`
  - 支持 benchmark case 内包含 `turns`；
  - 多轮场景按方法独立顺序执行；
  - 第二轮及以后只接收该方法上一轮输出构造出的 `ctp-method-previous-state-v1`；
  - 每完成一条结果都会写入 checkpoint；
  - 支持 `resume=True` 断点续跑，并以 `case_id + turn_id + method + repeat_index` 跳过已完成结果；
  - manifest 新增 `benchmark_structure` 和 `resume`。
- `app/core/formal_experiment_preflight.py`
  - 检查方法公平契约、数据集结构、输出目录、正式环境变量、固定离线数据和生成输入金标隔离；
  - 默认拒绝非空输出目录；仅当显式 `--resume` 且续跑契约完全匹配时允许非空目录。
- `experiments/run_formal_experiment.py`
  - 正式运行入口；
  - 默认先 preflight，检查通过后才调用 `ExperimentRunner.run_benchmark()`；
  - 支持 `--resume` 从 `benchmark_results.checkpoint.json` 和 `benchmark_resume_state.json` 恢复中断实验。
- `experiments/run_pilot.py`
  - 兼容旧入口，转发到正式运行入口。
- `tests/test_day6_formal_run_preflight.py`
  - 覆盖 preflight、输出目录保护、多轮状态隔离和 CSV/manifest 场景字段。

## 使用方式

只检查，不消耗 LLM API：

```bash
python experiments/run_formal_experiment.py --benchmark experiments/benchmark_test.json --preflight-only --skip-llm-config-check
```

正式运行前建议使用：

```bash
python experiments/run_formal_experiment.py --benchmark experiments/benchmark.json --expected-cases 100
```

如果正式实验中途因为 API 或程序中断而停止，并且代码、题库、模型参数和冻结数据都没有变化，可以使用同一个 `run_id` 续跑：

```bash
python experiments/run_formal_experiment.py --benchmark experiments/benchmark.json --expected-cases 100 --run-id <原run_id> --resume
```

正式运行要求：

- `EXPERIMENT_STRICT_MODE=true`
- `EXPERIMENT_DISABLE_CACHE=true`
- `TRACE_SAVE_USER_MESSAGE=false`
- `LLM_TEMPERATURE=0`
- 已配置真实 LLM 或本地 Ollama，不允许隐式 Mock。

## 验收标准

1. preflight 不调用 LLM、不访问真实旅游 API；
2. 非空输出目录默认会被拒绝；只有显式 `--resume` 且 run ID、Git commit、题库哈希、方法契约、模型参数、随机种子、天气/铁路/预算金标哈希均一致时才允许续跑；
3. `oracle_slots` 和手写 `previous_state` 在正式数据中会被拒绝；
4. 生成输入不包含 `expected`、`gold`、`accepted_agent_sets` 等评价专用字段；
5. 多轮场景第二轮只能看到同一方法第一轮输出形成的 previous state；
6. CSV 包含 `scenario_id`、`turn_id`、`turn_index`；
7. manifest 包含 benchmark 结构摘要、checkpoint 路径和 resume 状态；
8. 中断后续跑不会重复调用已完成结果，已保存的失败结果不会被静默删除；
9. 旧 `run_pilot.py` 不再使用三方法旧配置。
