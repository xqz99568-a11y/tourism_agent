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
  - manifest 新增 `benchmark_structure`。
- `app/core/formal_experiment_preflight.py`
  - 检查方法公平契约、数据集结构、输出目录、正式环境变量、固定离线数据和生成输入金标隔离。
- `experiments/run_formal_experiment.py`
  - 正式运行入口；
  - 默认先 preflight，检查通过后才调用 `ExperimentRunner.run_benchmark()`。
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

正式运行要求：

- `EXPERIMENT_STRICT_MODE=true`
- `EXPERIMENT_DISABLE_CACHE=true`
- `TRACE_SAVE_USER_MESSAGE=false`
- `LLM_TEMPERATURE=0`
- 已配置真实 LLM 或本地 Ollama，不允许隐式 Mock。

## 验收标准

1. preflight 不调用 LLM、不访问真实旅游 API；
2. 非空输出目录会被拒绝；
3. `oracle_slots` 和手写 `previous_state` 在正式数据中会被拒绝；
4. 生成输入不包含 `expected`、`gold`、`accepted_agent_sets` 等评价专用字段；
5. 多轮场景第二轮只能看到同一方法第一轮输出形成的 previous state；
6. CSV 包含 `scenario_id`、`turn_id`、`turn_index`；
7. manifest 包含 benchmark 结构摘要；
8. 旧 `run_pilot.py` 不再使用三方法旧配置。
