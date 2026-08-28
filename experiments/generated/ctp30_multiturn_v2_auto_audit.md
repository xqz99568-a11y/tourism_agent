# CTP30-v2 Draft Auto Audit

- status: `passed`
- dataset_id: `ctp30_multiturn_validation_v2_draft`
- dataset_sha256: `2ff17fb502690f8d592635b33ffb369be58584b2e43e670d7fe60be91822da89`
- case_count: `30`
- turn_count: `60`
- scenario_case_count: `30`
- target_turn_task_distribution: `{'attraction_recommendation': 1, 'budget_query': 4, 'clarification': 1, 'partial_replan': 15, 'weather_adjustment': 6, 'weather_query': 3}`
- turn_task_distribution: `{'attraction_recommendation': 1, 'budget_query': 4, 'clarification': 1, 'general_chat': 1, 'partial_replan': 15, 'trip_planning': 29, 'weather_adjustment': 6, 'weather_query': 3}`
- city_distribution: `{'beijing': 12, 'guilin': 11, 'hangzhou': 13, 'shenzhen': 11, 'xian': 11}`
- quality_status: `passed`
- quality_error_count: `0`
- quality_warning_count: `0`
- cross_split_duplicate_count: `0`
- cross_split_near_duplicate_count: `0`

## Quality Errors

- None

## Quality Warnings

- None

## Cross-Split Near Duplicates

- None

Paper disclosure: CTP30-v2 uses single-person case design and labeling followed by automatic schema, slot, weather, budget, city-coverage, and duplicate audits.
