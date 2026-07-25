# Day 4 Acceptance Report

- run_id: `day4_acceptance_git_blob_hash_20260725`
- passed: `True`
- created_at: `2026-07-25T06:37:43.355561+00:00`
- git_commit: `c1fd3aaa61aa75e02e4cb7b7997efa3cd460f68e`
- working_tree_clean: `True`
- input_hash_strategy: `git_blob_sha256_v1`

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
- acceptance input SHA-256 values must use git blob content and rebuild from the recorded commit

## Commands

- `compile_day4_modules`: returncode `0`
  - command: `E:\APP\python311\python.exe -m compileall -q app/core/goal_state_scheduler.py app/core/experiment_runner.py app/core/tracing.py app/schemas/experiment.py experiments/run_day4_acceptance.py tests/test_goal_state_scheduler.py tests/test_research_tools.py`
  - stdout: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_git_blob_hash_20260725\compile_day4_modules.stdout.txt`
  - stderr: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_git_blob_hash_20260725\compile_day4_modules.stderr.txt`
- `pytest_day4_scheduler_and_runner`: returncode `0`
  - command: `E:\APP\python311\python.exe -m pytest -q tests/test_goal_state_scheduler.py tests/test_research_tools.py`
  - stdout: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_git_blob_hash_20260725\pytest_day4_scheduler_and_runner.stdout.txt`
  - stderr: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_git_blob_hash_20260725\pytest_day4_scheduler_and_runner.stderr.txt`

## Representative trace

- result: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_git_blob_hash_20260725\representative_results.json`
- trace: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_git_blob_hash_20260725\traces\20260725T063741962790Z_day4_trace_turn1_adaptive_multi_agent_5f68b528_a1c2db3e.jsonl`
  - sha256: `89acdd75f1d8ce5a49382023dcc344ece1867a5587c756e363773007e7465cb5`
- trace: `D:\Code\Tourism_Agent\experiments\results\day4_acceptance\day4_acceptance_git_blob_hash_20260725\traces\20260725T063742139341Z_day4_trace_turn2_adaptive_multi_agent_a63182fb_77aeeaa7.jsonl`
  - sha256: `cbcf74a49b5167bf3fd6198817727fdc70ece487eacd528d13d31eff154da1d1`
