# CTP-100 Formal v2 Dataset Audit

> 本文件审计正式题库、正式预算金标与经济型人工审核账本的一致性，不运行正式100题。

- status: `passed`
- dataset_version: `2026-08-18-day8-formal-v2-weather-gold-fix`
- dataset_sha256: `b20f55fbb8695905a7f4424b1ce6a4ec0a91b75e4412828b24f1852d435f664d`
- case_count: `100`
- turn_count: `130`
- quality_report_status: `passed`

## Targeted checks

| check_id | status | actual |
| --- | --- | --- |
| ctp100_v2_016_origin_slot | passed | "wuhan" |
| ctp100_v2_016_origin_expected | passed | "wuhan" |
| ctp100_v2_016_origin_hard_constraint | passed | "wuhan" |
| ctp100_v2_016_intercity_scope | passed | {"budget_scope": "local_plus_round_trip_intercity", "intercity_transport_included": true} |
| ctp100_v2_057_t2_current_people | passed | 3 |
| ctp100_v2_057_t2_slots_people | passed | 3 |
| ctp100_v2_057_t2_expected_people | passed | 3 |
| ctp100_v2_057_t2_hard_people | passed | 3 |
| day8_explicit_date_trip_planning_requires_weather | passed | {"count": 32, "violations": []} |
| day8_no_date_trip_planning_requires_weather_reminder | passed | {"count": 18, "violations": []} |
| day8_weather_query_count_and_ctp100_v2_039_fix | passed | {"weather_query_count": 8, "ctp100_v2_039_task_type": "weather_query", "violations": []} |
| day8_weather_sensitive_partial_replan_requires_weather | passed | {"count": 8, "violations": []} |
| day8_weather_adjustment_reuses_first_turn_weather | passed | {"count": 5, "violations": []} |

## Budget gold audit

- path: `experiments\generated\ctp100_budget_gold_v2.json`
- source_dataset_sha256: `b20f55fbb8695905a7f4424b1ce6a4ec0a91b75e4412828b24f1852d435f664d`
- expected_source_dataset_sha256: `b20f55fbb8695905a7f4424b1ce6a4ec0a91b75e4412828b24f1852d435f664d`
- source_dataset_sha256_matches: `True`
- manual_review_scope: `['economy', 'intercity_transport', 'budget_policy_v2']`
- manual_review_scope_matches: `True`
- manual_review_formal_tiers: `['economy']`
- manual_review_excluded_scope: `['comfort', 'premium']`
- manual_review_excludes_comfort_premium: `True`
- source_slot_repair_count: `0`
- source_slot_repair_units: `[]`

## Issue counts

```json
{}
```
