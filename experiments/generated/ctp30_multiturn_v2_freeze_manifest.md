# CTP30-v2 Freeze Manifest

- status: `passed`
- freeze_date: `2026-08-28`
- frozen_dataset: `experiments/ctp30_multiturn_validation_v2.json`
- frozen_dataset_sha256: `d32adf32e820913ec46821e9312a77722c9d5ba03e5dbcee6b0659f719f5e6dc`
- source_draft: `experiments/generated/ctp30_multiturn_v2_draft.json`
- source_draft_sha256: `2ff17fb502690f8d592635b33ffb369be58584b2e43e670d7fe60be91822da89`
- case_count / turn_count: `30` / `60`
- target_turn_task_distribution: `{'attraction_recommendation': 1, 'budget_query': 4, 'clarification': 1, 'partial_replan': 15, 'weather_adjustment': 6, 'weather_query': 3}`
- quality_status: `passed`
- quality_error_count: `0`
- quality_warning_count: `0`
- cross_split_duplicate_count: `0`
- cross_split_near_duplicate_count: `0`
- paper_allowed: `True`

## Errors

- None

## Required paper wording

- CTP30-v2 is a supplementary sealed multi-turn validation set after CTP100 v6.
- CTP30-v2 uses single-annotator labels plus automatic rule audit.
- Do not claim multi-annotator agreement for CTP30-v2.
- CTP30-v1 is retained and discussed as a limitation/design-boundary result.
