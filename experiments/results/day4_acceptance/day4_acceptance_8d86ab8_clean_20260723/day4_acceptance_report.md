# Day 4 Acceptance Report

- run_id: `day4_acceptance_8d86ab8_clean_20260723`
- passed: `True`
- created_at: `2026-07-23T07:59:58.711508+00:00`
- git_commit: `8d86ab846bee5178c77cc1c209ece87aa5caf465`
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
- same-plan attraction expansion must override identical-request reuse
- previous-state expired flags and tool-result expired flags must block reuse
- previous fingerprints with extra conditions must not match missing current slots
- different repeat_index values must use isolated experiment session ids
- different run_id values must use isolated experiment session ids
- M3 scheduler metrics must be recoverable from trace after output exceptions
- acceptance manifest must freeze git state, SHA-256 inputs, outputs, and representative trace

## Commands

- `compile_day4_modules`: returncode `0`
  - command: `E:\APP\python311\python.exe -m compileall -q app/core/goal_state_scheduler.py app/core/experiment_runner.py app/core/tracing.py app/schemas/experiment.py experiments/run_day4_acceptance.py tests/test_goal_state_scheduler.py tests/test_research_tools.py`
  - stdout: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_8d86ab8_clean_20260723\compile_day4_modules.stdout.txt`
  - stderr: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_8d86ab8_clean_20260723\compile_day4_modules.stderr.txt`
- `pytest_day4_scheduler_and_runner`: returncode `0`
  - command: `E:\APP\python311\python.exe -m pytest -q tests/test_goal_state_scheduler.py tests/test_research_tools.py`
  - stdout: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_8d86ab8_clean_20260723\pytest_day4_scheduler_and_runner.stdout.txt`
  - stderr: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_8d86ab8_clean_20260723\pytest_day4_scheduler_and_runner.stderr.txt`

## Representative trace

- result: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_8d86ab8_clean_20260723\representative_results.json`
- trace: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_8d86ab8_clean_20260723\traces\20260723T075958347314Z_day4_trace_turn1_adaptive_multi_agent_b20c41d2_1a90bdc4.jsonl`
  - sha256: `035440217dd81f8f27fab429c86c5d5ab17080a9341e48322e30c42d0ec96596`
- trace: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_8d86ab8_clean_20260723\traces\20260723T075958554508Z_day4_trace_turn2_adaptive_multi_agent_1df82d28_98a90e19.jsonl`
  - sha256: `f69e2826152a23a5687e9b83da414f32fca92e724fb15159d50e74563dda0857`
