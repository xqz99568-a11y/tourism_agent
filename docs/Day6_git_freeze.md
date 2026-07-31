# Day6 Git 冻结记录

本文件记录 Day6 学术实验基础设施的本地冻结入口。复现实验时以 Git tag 为准：

- 代码冻结 tag：`day6-freeze-20260731`
- 最终证据冻结 tag：`day6-final-freeze-20260731`
- 冻结分支：`freeze/day6-20260731`
- 冻结前基线：`d38958c`（Day5 末尾版本）
- 冻结范围：Day6 代码、20 条开发集、Day6 FakeLLM 验收结果、真实 API 烟雾测试证据、测试与审计文档

## 严格绑定说明

Day6 早期 official 产物是在代码提交前生成的，因此其 manifest 中记录的是：

- `git_commit=d38958c`
- `working_tree_clean=false`

这些旧产物保留为过程证据，但论文复现应优先引用本轮重新运行的严格绑定产物。本轮重新运行时，先在 `.git/info/exclude` 中临时忽略新结果目录，保证实验脚本读取 Git 状态时工作区仍为干净状态；运行完成后再移除临时忽略规则并把结果目录纳入版本控制。

严格绑定产物的 manifest 均记录：

- `git_commit=0bc91d5f7af5e4a2fd65e6912eb256b1821f2996`
- `working_tree_clean=true`

## 已纳入版本控制的核心证据

- `experiments/ctp120_dev.json`
- `experiments/day6_acceptance_cases.json`
- 严格绑定离线验收：`experiments/results/day6_acceptance/day6_acceptance_freeze_20260731T062000Z/`
- 严格绑定真实 API 烟雾测试：`experiments/results/real_api_smoke/real_api_smoke_freeze_20260731T062000Z/`
- 过程保留离线验收：`experiments/results/day6_acceptance/day6_acceptance_official_20260731T042300Z/`
- 过程保留真实 API 烟雾测试：`experiments/results/real_api_smoke/real_api_smoke_official_20260731T054000Z/`
- `docs/Day6_acceptance_report.md`
- `docs/Day6_real_api_smoke_report.md`

## 冻结前验证

已执行并通过：

```powershell
python -m compileall app experiments tests
python experiments\validate_benchmark_dataset.py --benchmark experiments\ctp120_dev.json --expected-cases 20
python experiments\run_formal_experiment.py --benchmark experiments\ctp120_dev.json --expected-cases 20 --preflight-only --skip-llm-config-check
$files = Get-ChildItem tests -Filter 'test_day6_*.py' | ForEach-Object { $_.FullName }; pytest @files -q
pytest -q
git diff --cached --check
```

其中：

- Day6 测试：`32 passed`
- 全仓测试：`202 passed`
- 20 条开发集门禁：`passed`
- 正式实验 preflight：`passed`，预计四方法原始运行数 `104`
- pytest `asyncio_mode` 警告已消除

## 严格绑定产物验证

已在干净的代码冻结提交 `0bc91d5f7af5e4a2fd65e6912eb256b1821f2996` 上重新执行：

```powershell
python experiments\run_day6_acceptance.py --run-id day6_acceptance_freeze_20260731T062000Z
$env:LLM_PRICE_INPUT_PER_1K='0.00025'; $env:LLM_PRICE_OUTPUT_PER_1K='0.002'; $env:LLM_PRICE_CURRENCY='USD'; $env:LLM_PRICE_SNAPSHOT_DATE='2026-07-31'; $env:LLM_PRICE_SOURCE_URL='https://developers.openai.com/api/docs/models/gpt-5-mini'; python experiments\run_real_api_smoke.py --run-id real_api_smoke_freeze_20260731T062000Z --timeout 60 --max-tokens 256
```

结果：

- 新离线验收：`passed`，`44` 条运行结果，`44` 个 trace
- 新真实 API 烟雾测试：`passed`，`1` 次真实 LLM 调用，`1` 个 trace
- 两个新 manifest 均记录 `git_commit=0bc91d5f7af5e4a2fd65e6912eb256b1821f2996`
- 两个新 manifest 均记录 `working_tree_clean=true`

## 密钥与隐私边界

提交前对待提交文件进行了密钥模式扫描，未发现真实 API Key 或 Bearer token。仅存在：

- 文档中的占位示例：`你的中转API Key`
- 测试中的假 token：`Bearer token-value`

真实 API 烟雾测试证据只记录 `api_key_configured: true`，不保存密钥内容。
