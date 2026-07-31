# Day6 Git 冻结记录

本文件记录 Day6 学术实验基础设施的本地冻结入口。复现实验时以 Git tag 为准：

- 冻结 tag：`day6-freeze-20260731`
- 冻结分支：`freeze/day6-20260731`
- 冻结前基线：`d38958c`（Day5 末尾版本）
- 冻结范围：Day6 代码、20 条开发集、Day6 FakeLLM 验收结果、真实 API 烟雾测试证据、测试与审计文档

## 已纳入版本控制的核心证据

- `experiments/ctp120_dev.json`
- `experiments/day6_acceptance_cases.json`
- `experiments/results/day6_acceptance/day6_acceptance_official_20260731T042300Z/`
- `experiments/results/real_api_smoke/real_api_smoke_official_20260731T054000Z/`
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

## 密钥与隐私边界

提交前对待提交文件进行了密钥模式扫描，未发现真实 API Key 或 Bearer token。仅存在：

- 文档中的占位示例：`你的中转API Key`
- 测试中的假 token：`Bearer token-value`

真实 API 烟雾测试证据只记录 `api_key_configured: true`，不保存密钥内容。
