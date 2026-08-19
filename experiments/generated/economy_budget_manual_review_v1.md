# Economy Budget Manual Review v1

> 本文件是正式主实验的经济型预算人工审核说明。它只确认 `economy`、城际交通和 Budget Policy v2，不确认 `comfort` / `premium` 作为正式主实验预算金标。

## 审核结论

- review_status: `confirmed`
- reviewer: `dataset_owner`
- review_date: `2026-08-19`
- confirmed_scope: `economy`, `intercity_transport`, `budget_policy_v2`
- excluded_scope: `comfort`, `premium`
- formal_main_experiment_tiers: `economy`

## 公式确认

住宿费用：

```text
rooms = ceil(people_count / 2)
nights = max(duration_days - 1, 0)
accommodation_cost = citywide_median_economy_accommodation_price * rooms * nights
```

餐饮费用：

```text
meal_count_equivalent = 2 * duration_days + 0.5 * nights
food_cost = citywide_median_economy_food_price * people_count * meal_count_equivalent
```

## 五城 economy 参考价确认表

| 城市 | 经济型住宿参考价 | 经济型餐饮参考价 | 住宿来源 | 餐饮来源 | 审核结论 |
| --- | ---: | ---: | --- | --- | --- |
| 北京 | 330.0 | 55.0 | `data/accommodation/beijing.json` | `data/restaurants/beijing.json` | confirmed_for_formal_economy_budget_baseline |
| 杭州 | 320.0 | 50.0 | `data/accommodation/hangzhou.json` | `data/restaurants/hangzhou.json` | confirmed_for_formal_economy_budget_baseline |
| 西安 | 260.0 | 40.0 | `data/accommodation/xian.json` | `data/restaurants/xian.json` | confirmed_for_formal_economy_budget_baseline |
| 深圳 | 360.0 | 55.0 | `data/accommodation/shenzhen.json` | `data/restaurants/shenzhen.json` | confirmed_for_formal_economy_budget_baseline |
| 桂林 | 180.0 | 30.0 | `data/accommodation/guilin.json` | `data/restaurants/guilin.json` | confirmed_for_formal_economy_budget_baseline |

## comfort / premium 边界

`comfort` 和 `premium` 可以继续作为开发集中的档次识别测试、CLI 可选升级说明或后续扩展研究材料，但本轮正式主实验不把它们作为人工确认过的预算金标，也不在论文中声称验证了舒适型或高端型预算精度。
