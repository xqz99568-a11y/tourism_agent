# CTP30-v2 多轮封闭验证集草案人工审阅表

> 本文件由 `experiments/generate_ctp30_multiturn_v2_draft.py` 生成。当前只是草案，不是正式冻结集。

## 审阅规则

- 每个案例必须是两轮：第一轮建立上下文，第二轮是正式考察目标。
- 第二轮的 `changed_slots` 必须能从第二轮用户话语直接读出来。
- 第二轮的 `preserved_slots` 必须能从第一轮用户话语读出来。
- 有明确日期时只能使用冻结 QWeather 快照；超出 2026-09-05 必须标为未覆盖。
- 有出发地且路线支持时，预算必须包含冻结二等座往返城际交通；无出发地时必须说明不含城际交通。
- 你逐题只需要判断：题目是否真实、金标是否符合你的论文设定、是否需要改写表达。

## 自动审计摘要

- audit_status: `passed`
- case_count / turn_count: `30` / `60`
- target_turn_task_distribution: `{'attraction_recommendation': 1, 'budget_query': 4, 'clarification': 1, 'partial_replan': 15, 'weather_adjustment': 6, 'weather_query': 3}`
- quality_errors: `0`
- cross_split_near_duplicate_pairs: `0`

## 逐题审阅

| # | case_id | 第二轮任务 | 标题 | 第一轮用户话语 | 第二轮用户话语 | changed_slots | preserved_slots | 期望Agent | 期望工具 | 天气覆盖 | 城际预算 | 人工结论 | 修改意见 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `ctp30_mt_v2_001` | `partial_replan` | 预算变化｜杭州｜仅重算预算 | 我和朋友想去杭州玩3天，日期还没定，两个人总预算最多5500元，想轻松一点，先帮我安排一版。 | 预算上限调整为4200元，目的地、行程天数和出行人数均保持不变，只需要重新判断费用是否够用。 | `budget_amount` | `destination, duration_days, people_count` | `[['budget']]` | `[['budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `destination_local_only` | 待确认 |  |
| 2 | `ctp30_mt_v2_002` | `partial_replan` | 预算变化｜北京｜含城际交通 | 我从上海出发去北京玩2天，一个人，日期还没定，总预算最多6500元，想多看看历史文化景点。 | 总预算调整为5000元，出发地、目的地、行程天数和出行人数均保持不变，只重新计算预算。 | `budget_amount` | `origin, destination, duration_days, people_count` | `[['budget']]` | `[['budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `local_plus_round_trip_intercity` | 待确认 |  |
| 3 | `ctp30_mt_v2_003` | `partial_replan` | 预算变化｜深圳｜保留天气证据 | 明天从广州去深圳玩2天，亲子两个人出行，总预算最多6200元，帮我安排得轻松一点。 | 预算上限调整为5200元，出发时间、出发地、目的地、行程天数和出行人数均保持不变，只更新预算判断。 | `budget_amount` | `origin, destination, start_date, duration_days, people_count` | `[['budget']]` | `[['budget_calculator']]` | `不适用` | `local_plus_round_trip_intercity` | 待确认 |  |
| 4 | `ctp30_mt_v2_004` | `partial_replan` | 人数变化｜桂林｜重排行程预算 | 我想和朋友去桂林玩3天，日期还没定，两个人，总预算最多5000元，希望山水风景多一点。 | 出行人数调整为3个人，目的地、行程天数和预算上限均保持不变，请重新安排路线和费用。 | `people_count` | `destination, duration_days, budget_amount` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `destination_local_only` | 待确认 |  |
| 5 | `ctp30_mt_v2_005` | `partial_replan` | 人数变化｜西安｜保留日期天气 | 后天我想带长辈去西安玩3天，一共3个人，总预算最多7600元，历史文化景点多一些，尽量少走路。 | 出行人数调整为4个人，仍然是带长辈并且希望少走路，出发时间、目的地、行程天数和预算上限均保持不变，请重新安排路线和预算。 | `people_count` | `destination, start_date, duration_days, budget_amount` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 6 | `ctp30_mt_v2_006` | `partial_replan` | 补充出发地｜杭州｜仅重算城际预算 | 我想去杭州玩2天，日期还没定，两个人，总预算最多3600元，先按没有出发地的情况做当地行程。 | 我们从南京出发，目的地、行程天数、出行人数和预算上限均保持不变，路线不用重排，只把高铁大交通算进预算。 | `origin` | `destination, duration_days, people_count, budget_amount` | `[['budget']]` | `[['budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `local_plus_round_trip_intercity` | 待确认 |  |
| 7 | `ctp30_mt_v2_007` | `partial_replan` | 补充出发地｜桂林｜重新安排行程 | 我想去桂林看山水，日期还没定，两个人玩3天，总预算最多5000元，请先按轻松少走路的节奏安排。 | 我们从广州出发，目的地、行程天数、出行人数和预算上限均保持不变，想重新安排行程。 | `origin` | `destination, duration_days, people_count, budget_amount` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `local_plus_round_trip_intercity` | 待确认 |  |
| 8 | `ctp30_mt_v2_008` | `partial_replan` | 目的地变化｜深圳改桂林｜无日期 | 我想去深圳玩2天，日期还没定，两个人，总预算最多4800元，想安排得轻松一点。 | 目的地调整为桂林，行程天数、出行人数和预算上限均保持不变，请重新推荐景点并安排完整路线。 | `destination` | `duration_days, people_count, budget_amount` | `[['attraction', 'itinerary', 'budget']]` | `[['poi_search', 'budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `destination_local_only` | 待确认 |  |
| 9 | `ctp30_mt_v2_009` | `partial_replan` | 目的地变化｜杭州改西安｜保留明天 | 我明天想去杭州玩2天，两个人，总预算最多4600元，帮我把景点、天气和预算都安排一下。 | 目的地调整为西安，出发时间、行程天数、出行人数和预算上限均保持不变，请重新做完整安排。 | `destination` | `start_date, duration_days, people_count, budget_amount` | `[['attraction', 'weather', 'itinerary', 'budget']]` | `[['poi_search', 'weather_query', 'budget_calculator']]` | `full` | `destination_local_only` | 待确认 |  |
| 10 | `ctp30_mt_v2_010` | `partial_replan` | 天数变化｜北京｜无日期 | 我想去北京玩2天，日期还没定，两个人，总预算最多5200元，经典景点为主，节奏轻松少走路。 | 行程天数调整为3天，目的地、出行人数和预算上限均保持不变，请重新安排每天路线和费用。 | `duration_days` | `destination, people_count, budget_amount` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `destination_local_only` | 待确认 |  |
| 11 | `ctp30_mt_v2_011` | `partial_replan` | 天数变化｜深圳｜保留明天 | 明天想去深圳玩2天，两个人，总预算最多5600元，希望亲子友好一点。 | 行程天数调整为3天，出发时间、目的地、出行人数和预算上限均保持不变，请重新安排路线，并更新天气和预算。 | `duration_days` | `destination, start_date, people_count, budget_amount` | `[['weather', 'itinerary', 'budget']]` | `[['weather_query', 'budget_calculator']]` | `full` | `destination_local_only` | 待确认 |  |
| 12 | `ctp30_mt_v2_012` | `partial_replan` | 日期变化｜西安｜新增天气 | 我想去西安玩3天，日期还没定，两个人，总预算最多5200元，希望历史文化景点多一点。 | 出发时间调整为后天，目的地、行程天数、出行人数和预算上限均保持不变，请加入天气后重新安排。 | `start_date` | `destination, duration_days, people_count, budget_amount` | `[['weather', 'itinerary', 'budget']]` | `[['weather_query', 'budget_calculator']]` | `full` | `destination_local_only` | 待确认 |  |
| 13 | `ctp30_mt_v2_013` | `partial_replan` | 偏好变化｜杭州｜改历史文化 | 我想去杭州玩3天，日期还没定，两个人，总预算最多5200元，先按自然风景和轻松节奏安排。 | 游玩偏好调整为历史文化和博物馆，目的地、行程天数、出行人数和预算上限均保持不变，请重新推荐景点并安排路线。 | `preferences` | `destination, duration_days, people_count, budget_amount` | `[['attraction', 'itinerary', 'budget']]` | `[['poi_search', 'budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `destination_local_only` | 待确认 |  |
| 14 | `ctp30_mt_v2_014` | `partial_replan` | 人群变化｜北京｜改带父母 | 我想去北京玩3天，日期还没定，两个人，总预算最多6000元，经典景点为主。 | 出行人数调整为3个人，并且改为带老人出行，希望少走路；目的地、行程天数和预算上限均保持不变。 | `people_count, traveler_group, special_requirements` | `destination, duration_days, budget_amount` | `[['attraction', 'itinerary', 'budget']]` | `[['poi_search', 'budget_calculator']]` | `no_date_no_specific_weather_for_trip_plan` | `destination_local_only` | 待确认 |  |
| 15 | `ctp30_mt_v2_015` | `partial_replan` | 无变化复用｜桂林｜重复上一轮 | 我想去桂林玩2天，日期还没定，两个人，总预算最多4200元，想看山水，但节奏希望轻松一点。 | 就按上一轮方案，目的地、行程天数、出行人数和预算上限均保持不变，请再帮我整理一遍。 | `` | `destination, duration_days, people_count, budget_amount` | `[[]]` | `[[]]` | `no_date_no_specific_weather_for_trip_plan` | `destination_local_only` | 待确认 |  |
| 16 | `ctp30_mt_v2_016` | `weather_adjustment` | 天气调整｜深圳｜第一天下雨 | 明天想去深圳玩2天，亲子两个人出行，总预算最多5800元，想安排一个室内外结合的轻松行程。 | 如果明天下午下雨，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请把第一天户外项目往后挪，并顺便更新预算。 | `` | `` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 17 | `ctp30_mt_v2_017` | `weather_adjustment` | 天气调整｜桂林｜第二天下雨 | 后天想去桂林玩3天，两个人，总预算最多5200元，想多看看山水风景。 | 如果第2天下雨，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请把坐船和户外山水安排调整得保守一点，并重新计算费用。 | `` | `` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 18 | `ctp30_mt_v2_018` | `weather_adjustment` | 天气调整｜杭州｜第二天高温 | 明天想去杭州玩2天，两个人，总预算最多5000元，想轻松看看自然风景和博物馆。 | 如果第二天高温，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请尽量减少室外暴晒项目，并重新计算预算。 | `` | `` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 19 | `ctp30_mt_v2_019` | `weather_adjustment` | 天气调整｜北京｜第一天降温 | 后天想去北京玩2天，两个人，总预算最多5400元，经典文化景点为主。 | 如果第一天降温比较明显，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请把露天排队时间压缩一下，并更新预算。 | `` | `` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 20 | `ctp30_mt_v2_020` | `weather_adjustment` | 天气调整｜西安｜旅途中有雨 | 明天想去西安玩3天，两个人，总预算最多5600元，历史文化和博物馆多一些。 | 如果旅途中有雨，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请减少第2天和第3天的室外安排，并重新核算预算。 | `` | `` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 21 | `ctp30_mt_v2_021` | `weather_adjustment` | 天气调整｜深圳｜第二天高温 | 明天从广州去深圳玩3天，两个人，总预算最多6800元，想要轻松一点的亲子路线。 | 如果第二天高温暴晒，出发时间、出发地、目的地、行程天数、出行人数和预算上限均保持不变，请把室外活动调整到早晚。 | `` | `` | `[['itinerary', 'budget']]` | `[['budget_calculator']]` | `不适用` | `local_plus_round_trip_intercity` | 待确认 |  |
| 22 | `ctp30_mt_v2_022` | `budget_query` | 预算追问｜桂林｜只问够不够 | 我想去桂林玩3天，两个人，日期还没定，总预算最多4600元，先给我安排一条轻松的山水路线。 | 行程先不改，目的地、行程天数、出行人数和预算上限均保持不变，只帮我重新说明预算够不够。 | `` | `` | `[['budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 23 | `ctp30_mt_v2_023` | `budget_query` | 预算追问｜北京｜含广州出发 | 我从广州出发去北京玩4天，两个人，日期还没定，总预算最多12000元，经典景点为主。 | 路线先不改，出发地、目的地、行程天数、出行人数和预算上限均保持不变，只重新列出总费用和人均费用。 | `` | `` | `[['budget']]` | `[['budget_calculator']]` | `不适用` | `local_plus_round_trip_intercity` | 待确认 |  |
| 24 | `ctp30_mt_v2_024` | `budget_query` | 预算追问｜杭州｜只算当地 | 我想去杭州玩3天，两个人，日期还没定，总预算最多4800元，先安排一版当地行程。 | 如果只算目的地当地吃住行和门票，不含大交通，目的地、行程天数和出行人数均保持不变，大概需要多少钱？ | `` | `` | `[['budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 25 | `ctp30_mt_v2_025` | `budget_query` | 预算追问｜西安｜分项费用 | 我想带老人去西安玩2天，一共3个人，日期还没定，总预算最多6000元，节奏希望轻松一点。 | 行程不用重排，目的地、行程天数、出行人数和预算上限均保持不变，只把住宿、餐饮、门票和市内交通费用分项列清楚。 | `` | `` | `[['budget']]` | `[['budget_calculator']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 26 | `ctp30_mt_v2_026` | `weather_query` | 天气追问｜杭州｜明后天 | 我想去杭州玩3天，两个人，日期还没定，总预算最多5200元，先安排一版轻松路线。 | 那只帮我查一下杭州明天和后天的天气，路线先不用改。 | `` | `` | `[['weather']]` | `[['weather_query']]` | `full` | `destination_local_only` | 待确认 |  |
| 27 | `ctp30_mt_v2_027` | `weather_query` | 天气追问｜深圳｜后天起三天 | 我想去深圳玩3天，两个人，日期还没定，总预算最多6200元，亲子路线为主。 | 只帮我查一下深圳后天开始未来3天的天气，看看适不适合安排户外活动。 | `` | `` | `[['weather']]` | `[['weather_query']]` | `full` | `destination_local_only` | 待确认 |  |
| 28 | `ctp30_mt_v2_028` | `weather_query` | 天气追问｜北京｜一个月后超范围 | 我想去北京玩3天，两个人，日期还没确定，总预算最多6200元，历史文化景点为主。 | 如果一个月后去北京玩3天，现在能查到那几天的天气预报吗？这次只查天气。 | `` | `` | `[['weather']]` | `[['weather_query']]` | `out_of_range` | `destination_local_only` | 待确认 |  |
| 29 | `ctp30_mt_v2_029` | `attraction_recommendation` | 景点追问｜西安｜只要室内景点 | 我想去西安玩3天，两个人，日期还没定，总预算最多5600元，历史文化景点多一些。 | 行程先不用重排，只给我再推荐4个西安室内或博物馆类景点。 | `` | `` | `[['attraction']]` | `[['poi_search']]` | `不适用` | `destination_local_only` | 待确认 |  |
| 30 | `ctp30_mt_v2_030` | `clarification` | 闲聊到澄清｜缺核心信息 | 你好，我先随便看看，想了解一下你能不能帮我做旅游计划。 | 那我想做一份完整行程，但还没想好去哪，也没定玩几天、几个人去，你先问我需要补充什么。 | `` | `` | `[[]]` | `[[]]` | `不适用` | `不适用` | 待确认 |  |

## 冻结前必须完成

- 将全部“待确认”改为“确认”或写明修改意见。
- 如果修改题目，需要重新运行生成/审计流程，保证 JSON 与审阅表一致。
- 正式运行前再生成最终 `ctp30_multiturn_validation_v2.json`，并记录 dataset sha256。
