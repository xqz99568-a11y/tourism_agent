# Day 4 Acceptance Report

- run_id: `day4_acceptance_1e5bfe7_20260725`
- passed: `True`
- created_at: `2026-07-25T05:26:43.776829+00:00`
- git_commit: `1e5bfe7a59c2936c5af876154304fd3e9c6b3972`
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
  - stdout: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_1e5bfe7_20260725\compile_day4_modules.stdout.txt`
  - stderr: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_1e5bfe7_20260725\compile_day4_modules.stderr.txt`
- `pytest_day4_scheduler_and_runner`: returncode `0`
  - command: `E:\APP\python311\python.exe -m pytest -q tests/test_goal_state_scheduler.py tests/test_research_tools.py`
  - stdout: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_1e5bfe7_20260725\pytest_day4_scheduler_and_runner.stdout.txt`
  - stderr: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_1e5bfe7_20260725\pytest_day4_scheduler_and_runner.stderr.txt`

## Representative trace

- result: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_1e5bfe7_20260725\representative_results.json`
- trace: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_1e5bfe7_20260725\traces\20260725T052643450374Z_day4_trace_turn1_adaptive_multi_agent_a67a3b4e_400be2fb.jsonl`
  - sha256: `3e71c561b536e4017ff0ff5a39c5d67506a85984c73741edb2316b5db4d3b3dc`
- trace: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_1e5bfe7_20260725\traces\20260725T052643644669Z_day4_trace_turn2_adaptive_multi_agent_319fdcc0_89ac130f.jsonl`
  - sha256: `503e40c2c68b9526bd6c347b0a26b29ba00a8581377180fb65849f5daba8c72e`
