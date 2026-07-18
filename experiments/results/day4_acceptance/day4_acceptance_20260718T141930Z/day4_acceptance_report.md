# Day 4 Acceptance Report

- run_id: `day4_acceptance_20260718T141930Z`
- passed: `True`
- created_at: `2026-07-18T14:19:45.231783+00:00`
- git_commit: `9f46950ffc503dbc1b705ab1258935e6e7dfd815`
- working_tree_clean: `True`

## Checked requirements

- wrong previous-result city fingerprint must not be reused
- failed previous tool result must not be counted as reused
- multiple changed slots must be combined before scheduling
- goal shift without slot change must not become identical reuse
- M2 and M3 follow-up runs must receive comparable previous slots
- M3 savings metrics must use task-aware M2 reference counts
- scheduler ticket, decision, reuse validation, and hit rate must persist in trace
- single-capability tasks must not create fake itinerary fingerprints
- reused, invalidated, and replanned agent sets must be mutually consistent
- budget estimation must schedule missing attraction evidence before budget
- reused itinerary must copy the previous itinerary artifact instead of rebuilding it
- clarification tasks must stop with clarification status and explicit missing fields
- fixed M2 must recover slots from its own previous turn output
- available result markers without concrete artifacts must not count as reuse
- upstream tool failure must stop downstream dependent agents
- expired previous results must not be reusable
- empty preferences and null budget must be preserved as cancellation deltas
- regenerate requests must override identical-request reuse
- different repeat_index values must use isolated experiment session ids
- M3 scheduler metrics must be recoverable from trace after output exceptions
- acceptance manifest must freeze git state, SHA-256 inputs, outputs, and representative trace

## Commands

- `compile_day4_modules`: returncode `0`
  - command: `E:\APP\python311\python.exe -m compileall -q app/core/goal_state_scheduler.py app/core/experiment_runner.py app/core/tracing.py app/schemas/experiment.py experiments/run_day4_acceptance.py tests/test_goal_state_scheduler.py tests/test_research_tools.py`
  - stdout: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_20260718T141930Z\compile_day4_modules.stdout.txt`
  - stderr: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_20260718T141930Z\compile_day4_modules.stderr.txt`
- `pytest_day4_scheduler_and_runner`: returncode `0`
  - command: `E:\APP\python311\python.exe -m pytest -q tests/test_goal_state_scheduler.py tests/test_research_tools.py`
  - stdout: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_20260718T141930Z\pytest_day4_scheduler_and_runner.stdout.txt`
  - stderr: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_20260718T141930Z\pytest_day4_scheduler_and_runner.stderr.txt`

## Representative trace

- result: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_20260718T141930Z\representative_results.json`
- trace: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_20260718T141930Z\traces\20260718T141945061813Z_day4_trace_turn1_adaptive_multi_agent_c54733d4_b9e53a0f.jsonl`
  - sha256: `9ef04a164405cd64fa3cb565466e126da98ca3ee5f01b59eec85337b2804824f`
- trace: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_20260718T141930Z\traces\20260718T141945154789Z_day4_trace_turn2_adaptive_multi_agent_e869b4c1_7524a875.jsonl`
  - sha256: `8d6913244ade96c238068b0284bb56715a735f526a9b5291e72b8e9a41cb101c`
