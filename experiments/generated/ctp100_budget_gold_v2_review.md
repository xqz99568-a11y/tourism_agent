# CTP-100 Budget Gold v2 经济型人工审阅材料

> 本文件用于复核正式预算金标中的 economy 范围。正式确认范围为 `economy`、`intercity_transport`、`budget_policy_v2`；`comfort` / `premium` 不属于本次正式主实验预算金标确认范围。

## 数据来源

- 正式题库：`experiments\ctp100_formal_v2.json`
- 预算金标文件：`experiments\generated\ctp100_budget_gold_v2.json`
- 经济型人工审核账本：`experiments/generated/economy_budget_manual_review_v1.json`
- 成本明细来自预算金标中的 `budget_policy_v2.cost_breakdown`，该字段由固定预算计算器生成。
- 新规则：预算金额只影响预算是否充足，不触发住宿或餐饮自动升级/降级。
- 正式主实验只评价 economy 预算基线；comfort/premium 可作为开发检查或可选升级说明，不作为本次主实验金标。

## 总览

| 项目 | 数量 |
| --- | --- |
| 预算适用评价单元 | 90 |
| 自动检查异常单元 | 0 |
| 无异常单元 | 90 |

## 自动异常报告

| 异常类型 | 数量 |
| --- | --- |
| 无 | 0 |

### 异常明细

| unit_id | issue_flags | issue_summary |
| --- | --- | --- |
| 无 |  |  |

## 重点案例逐条解释

#### ctp100_v2_001

- 用户输入：我和对象想去北京玩3天，时间还没定，我们总共最多花5000元，帮我们排个轻松点的行程。
- 预算范围：仅目的地当地费用。
- 城际交通：用户明确只问目的地当地费用，因此不纳入往返城际交通。
- 当地基础费用：景点门票470元 + 住宿660元 + 餐饮770元 + 市内交通40元 + 其他当地费用0元 = 1940元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=sufficient；scope_complete=是；最终推荐2134元，完整范围剩余2866元，已覆盖范围剩余2866元，缺口0元。
- 多轮变化：单轮题或多轮首轮，无上一轮变化。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_002

- 用户输入：我和朋友明天从上海出发去杭州玩2天，两个人，总共最多花3000元，帮我安排一下。
- 预算范围：目的地当地费用 + 往返城际高铁/动车二等座。
- 城际交通：题目提供了出发地和目的地，冻结铁路快照支持该路线，所以加入成人二等座往返费用332元。
- 当地基础费用：景点门票270元 + 住宿320元 + 餐饮450元 + 市内交通50元 + 其他当地费用0元 = 1090元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=sufficient；scope_complete=是；最终推荐1531元，完整范围剩余1469元，已覆盖范围剩余1469元，缺口0元。
- 多轮变化：单轮题或多轮首轮，无上一轮变化。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_005

- 用户输入：明天从广州坐高铁去桂林，玩3天，两个人，总预算上限5000元，帮我把路线和费用都安排好。
- 预算范围：目的地当地费用 + 往返城际高铁/动车二等座。
- 城际交通：题目提供了出发地和目的地，冻结铁路快照支持该路线，所以加入成人二等座往返费用800元。
- 当地基础费用：景点门票350元 + 住宿360元 + 餐饮420元 + 市内交通102元 + 其他当地费用0元 = 1232元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=sufficient；scope_complete=是；最终推荐2155.2元，完整范围剩余2844.8元，已覆盖范围剩余2844.8元，缺口0元。
- 多轮变化：单轮题或多轮首轮，无上一轮变化。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_046

- 用户输入：北京玩2天，4个人，总预算上限2500元够吗？我还没确定从哪里出发。
- 预算范围：仅目的地当地费用。
- 城际交通：用户明确只问目的地当地费用，因此不纳入往返城际交通。
- 当地基础费用：景点门票620元 + 住宿660元 + 餐饮990元 + 市内交通48元 + 其他当地费用0元 = 2318元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，仍按经济型基准计算；若超预算则如实报告缺口。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=insufficient；scope_complete=是；最终推荐2549.8元，完整范围剩余0元，已覆盖范围剩余0元，缺口49.8元。
- 多轮变化：单轮题或多轮首轮，无上一轮变化。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_048

- 用户输入：从拉萨去西安玩3天，两个人，总预算上限8000元够不够？
- 预算范围：仅目的地当地费用（城际路线未覆盖）。
- 城际交通：冻结铁路快照不支持该路线，不猜票价，只计算目的地当地费用并提示用户查询12306。
- 当地基础费用：景点门票560元 + 住宿520元 + 餐饮560元 + 市内交通94元 + 其他当地费用0元 = 1734元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：不能完整判断；sufficiency_status=indeterminate；scope_complete=否；最终推荐1907.4元，完整旅行剩余预算不表述，已覆盖范围剩余6092.6元，缺口0元。
- 多轮变化：单轮题或多轮首轮，无上一轮变化。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_055::t1

- 用户输入：明天从广州去桂林玩3天，两个人，总预算上限5000元。
- 预算范围：目的地当地费用 + 往返城际高铁/动车二等座。
- 城际交通：题目提供了出发地和目的地，冻结铁路快照支持该路线，所以加入成人二等座往返费用800元。
- 当地基础费用：景点门票350元 + 住宿360元 + 餐饮420元 + 市内交通102元 + 其他当地费用0元 = 1232元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=sufficient；scope_complete=是；最终推荐2155.2元，完整范围剩余2844.8元，已覆盖范围剩余2844.8元，缺口0元。
- 多轮变化：单轮题或多轮首轮，无上一轮变化。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_055::t2

- 用户输入：又有一个朋友加入，现在一共3个人，预算上限不变。
- 预算范围：目的地当地费用 + 往返城际高铁/动车二等座。
- 城际交通：题目提供了出发地和目的地，冻结铁路快照支持该路线，所以加入成人二等座往返费用1200元。
- 当地基础费用：景点门票525元 + 住宿720元 + 餐饮630元 + 市内交通153元 + 其他当地费用0元 = 2028元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=sufficient；scope_complete=是；最终推荐3430.8元，完整范围剩余1569.2元，已覆盖范围剩余1569.2元，缺口0元。
- 多轮变化：people_count: 2 → 3。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_056::t1

- 用户输入：我一个人从上海去北京玩2天，日期没定，总预算上限3500元。
- 预算范围：目的地当地费用 + 往返城际高铁/动车二等座。
- 城际交通：题目提供了出发地和目的地，冻结铁路快照支持该路线，所以加入成人二等座往返费用1322元。
- 当地基础费用：景点门票155元 + 住宿330元 + 餐饮247.5元 + 市内交通12元 + 其他当地费用0元 = 744.5元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=sufficient；scope_complete=是；最终推荐2140.95元，完整范围剩余1359.05元，已覆盖范围剩余1359.05元，缺口0元。
- 多轮变化：单轮题或多轮首轮，无上一轮变化。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_056::t2

- 用户输入：再加一个朋友，变成两个人，其他条件不变。
- 预算范围：目的地当地费用 + 往返城际高铁/动车二等座。
- 城际交通：题目提供了出发地和目的地，冻结铁路快照支持该路线，所以加入成人二等座往返费用2644元。
- 当地基础费用：景点门票310元 + 住宿330元 + 餐饮495元 + 市内交通24元 + 其他当地费用0元 = 1159元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，仍按经济型基准计算；若超预算则如实报告缺口。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=insufficient；scope_complete=是；最终推荐3918.9元，完整范围剩余0元，已覆盖范围剩余0元，缺口418.9元。
- 多轮变化：people_count: 1 → 2。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_067::t1

- 用户输入：杭州玩3天，两个人，日期没定，总预算上限5000元。
- 预算范围：仅目的地当地费用。
- 城际交通：用户明确只问目的地当地费用，因此不纳入往返城际交通。
- 当地基础费用：景点门票390元 + 住宿640元 + 餐饮700元 + 市内交通70元 + 其他当地费用0元 = 1800元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=sufficient；scope_complete=是；最终推荐1980元，完整范围剩余3020元，已覆盖范围剩余3020元，缺口0元。
- 多轮变化：单轮题或多轮首轮，无上一轮变化。
- 异常标记：未发现自动检查异常。
#### ctp100_v2_067::t2

- 用户输入：我们从南京出发，其他条件不变，不用重新排路线。
- 预算范围：目的地当地费用 + 往返城际高铁/动车二等座。
- 城际交通：题目提供了出发地和目的地，冻结铁路快照支持该路线，所以加入成人二等座往返费用412元。
- 当地基础费用：景点门票390元 + 住宿640元 + 餐饮700元 + 市内交通70元 + 其他当地费用0元 = 1800元。
- 酒店和餐饮档次：酒店 economy，餐饮 economy；用户未明确提出住宿或餐饮档次，按经济型基准计算；预算金额不触发升级。
- 是否触发自动升级：否。upgrade_applied=[]
- 预算充足性：可以判断；sufficiency_status=sufficient；scope_complete=是；最终推荐2392元，完整范围剩余2608元，已覆盖范围剩余2608元，缺口0元。
- 多轮变化：origin: None → nanjing。
- 异常标记：未发现自动检查异常。

## 全量预算适用评价单元审阅表

> 表中“本行程人均日均餐饮费” = 餐饮总额 ÷ people_count ÷ duration_days，只表示当前行程平均到每天的费用，不等同于固定的完整三餐日参考费用。

| unit_id | task_type | user_input | origin | destination | duration_days | nights | people_count | rooms | budget_amount | budget_scope | requested_budget_scope | computed_budget_scope | scope_complete | sufficiency_status | hotel_tier | food_tier | 景点门票 | 住宿 | 餐饮 | 本行程人均日均餐饮费 | 市内交通 | 其他当地费用 | 当地基础费用 | 10%机动 | 城际单程/人 | 城际往返 | 最终推荐 | 剩余 | 已覆盖范围剩余 | 缺口 | 超预算 | 可判断 | 升级规则 | POI | 异常 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ctp100_v2_001 | trip_planning | 我和对象想去北京玩3天，时间还没定，我们总共最多花5000元，帮我们排个轻松点的行程。 |  | beijing | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 2866 | 2866 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_002 | trip_planning | 我和朋友明天从上海出发去杭州玩2天，两个人，总共最多花3000元，帮我安排一下。 | shanghai | hangzhou | 2 | 1 | 2 | 1 | 3000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 270 | 320 | 450 | 112.5 | 50 | 0 | 1090 | 109 | 83 | 332 | 1531 | 1469 | 1469 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004"] | 无 |
| ctp100_v2_003 | trip_planning | 后天想去西安玩3天，我们3个人，整个行程总预算上限6000元，希望历史文化景点多一点。 |  | xian | 3 | 2 | 3 | 2 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 840 | 1040 | 840 | 93.33 | 141 | 0 | 2861 | 286.1 |  | 0 | 3147.1 | 2852.9 | 2852.9 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_004 | trip_planning | 我们从广州出发去深圳玩2天，两个人，时间还没定，总共最多花4000元，想走得轻松一点。 | guangzhou | shenzhen | 2 | 1 | 2 | 1 | 4000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 190 | 360 | 495 | 123.75 | 86 | 0 | 1131 | 113.1 | 74.5 | 298 | 1542.1 | 2457.9 | 2457.9 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004"] | 无 |
| ctp100_v2_005 | trip_planning | 明天从广州坐高铁去桂林，玩3天，两个人，总预算上限5000元，帮我把路线和费用都安排好。 | guangzhou | guilin | 3 | 2 | 2 | 1 | 5000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 | 200 | 800 | 2155.2 | 2844.8 | 2844.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_006 | trip_planning | 我准备一个人从上海去北京玩2天，时间还没决定，最多花3500元，想看看历史文化景点。 | shanghai | beijing | 2 | 1 | 1 | 1 | 3500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 155 | 330 | 247.5 | 123.75 | 12 | 0 | 744.5 | 74.45 | 661 | 1322 | 2140.95 | 1359.05 | 1359.05 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004"] | 无 |
| ctp100_v2_007 | trip_planning | 我们3个人想去杭州慢慢玩4天，日期还没有决定，总预算上限7000元。 |  | hangzhou | 4 | 3 | 3 | 2 | 7000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 705 | 1920 | 1425 | 118.75 | 159 | 0 | 4209 | 420.9 |  | 0 | 4629.9 | 2370.1 | 2370.1 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006","hz007","hz008"] | 无 |
| ctp100_v2_008 | trip_planning | 两个人准备从郑州去西安玩2天，时间还没定，总共最多花4000元，路线紧凑一点但别太累。 | zhengzhou | xian | 2 | 1 | 2 | 1 | 4000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 400 | 260 | 360 | 90 | 62 | 0 | 1082 | 108.2 | 221 | 884 | 2074.2 | 1925.8 | 1925.8 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004"] | 无 |
| ctp100_v2_009 | trip_planning | 我们4个人准备从武汉去深圳玩3天，日期没定，总预算上限10000元，想兼顾城市景观和室内场馆。 | wuhan | shenzhen | 3 | 2 | 4 | 2 | 10000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 540 | 1440 | 1540 | 128.33 | 260 | 0 | 3780 | 378 | 627.5 | 5020 | 9178 | 822 | 822 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_010 | trip_planning | 我们两个人想在桂林玩4天，时间暂时没定，总共最多花6000元，主要想看山水。 |  | guilin | 4 | 3 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 510 | 540 | 570 | 71.25 | 122 | 0 | 1742 | 174.2 |  | 0 | 1916.2 | 4083.8 | 4083.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006","gl007","gl008"] | 无 |
| ctp100_v2_011 | trip_planning | 9月4号去北京玩3天，两个人，总预算上限5500元，帮我安排一下。 |  | beijing | 3 | 2 | 2 | 1 | 5500 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 3366 | 3366 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_012 | trip_planning | 9月5号从南京去杭州玩2天，两个人，总预算上限4000元。 | nanjing | hangzhou | 2 | 1 | 2 | 1 | 4000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 270 | 320 | 450 | 112.5 | 50 | 0 | 1090 | 109 | 103 | 412 | 1611 | 2389 | 2389 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004"] | 无 |
| ctp100_v2_013 | trip_planning | 一个月后从成都去西安玩3天，两个人，总预算上限6000元，想安排得舒服一些。 | chengdu | xian | 3 | 2 | 2 | 1 | 6000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 | 285 | 1140 | 3047.4 | 2952.6 | 2952.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_014 | trip_planning | 国庆从长沙去深圳玩4天，我们3个人，总预算上限9000元，帮我做个行程。 | changsha | shenzhen | 4 | 3 | 3 | 2 | 9000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 1005 | 2160 | 1567.5 | 130.62 | 267 | 0 | 4999.5 | 499.95 | 394.5 | 2367 | 7866.45 | 1133.55 | 1133.55 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006","sz007","sz008"] | 无 |
| ctp100_v2_015 | trip_planning | 一个月后想去桂林玩3天，两个人，总共最多花5000元。 |  | guilin | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 |  | 0 | 1355.2 | 3644.8 | 3644.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_016 | trip_planning | 我准备从武汉带爸妈去北京玩4天，一共3个人，日期没定，总预算上限9000元，节奏别太赶。 | wuhan | beijing | 4 | 3 | 3 | 2 | 9000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 990 | 1980 | 1567.5 | 130.62 | 129 | 0 | 4666.5 | 466.65 | 623 | 3738 | 8871.15 | 128.85 | 128.85 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006","bj007","bj008"] | 无 |
| ctp100_v2_017 | trip_planning | 我们两个人准备从南京去杭州玩3天，时间还没定，总共最多花4500元，希望少走回头路。 | nanjing | hangzhou | 3 | 2 | 2 | 1 | 4500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 | 103 | 412 | 2392 | 2108 | 2108 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_018 | trip_planning | 两个人准备从成都去西安玩4天，日期没定，总预算上限6500元。 | chengdu | xian | 4 | 3 | 2 | 1 | 6500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 840 | 780 | 760 | 95 | 124 | 0 | 2504 | 250.4 | 285 | 1140 | 3894.4 | 2605.6 | 2605.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006","xa007","xa008"] | 无 |
| ctp100_v2_019 | trip_planning | 9月4号去深圳玩3天，两个人，总预算上限6000元，想安排一些室内项目。 |  | shenzhen | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 3921 | 3921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_020 | trip_planning | 一个月后从广州去桂林玩3天，我们4个人，总预算上限10000元，想轻松看看山水。 | guangzhou | guilin | 3 | 2 | 4 | 2 | 10000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 700 | 720 | 840 | 70 | 204 | 0 | 2464 | 246.4 | 200 | 1600 | 4310.4 | 5689.6 | 5689.6 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_041 | budget_query | 北京玩3天，两个人，总预算上限10000元，帮我看看大概需要多少钱，不用排路线。 |  | beijing | 3 | 2 | 2 | 1 | 10000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 7866 | 7866 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_042 | budget_query | 从上海坐高铁去杭州玩2天，两个人，总预算上限3000元够不够？只算费用。 | shanghai | hangzhou | 2 | 1 | 2 | 1 | 3000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 270 | 320 | 450 | 112.5 | 50 | 0 | 1090 | 109 | 83 | 332 | 1531 | 1469 | 1469 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004"] | 无 |
| ctp100_v2_043 | budget_query | 从成都出发去西安玩3天，两个人，总共最多花4500元，钱够吗？ | chengdu | xian | 3 | 2 | 2 | 1 | 4500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 | 285 | 1140 | 3047.4 | 1452.6 | 1452.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_044 | budget_query | 从广州去深圳玩2天，3个人，总预算上限3500元，帮我算算。 | guangzhou | shenzhen | 2 | 1 | 3 | 2 | 3500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 285 | 720 | 742.5 | 123.75 | 129 | 0 | 1876.5 | 187.65 | 74.5 | 447 | 2511.15 | 988.85 | 988.85 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004"] | 无 |
| ctp100_v2_045 | budget_query | 从长沙去桂林玩4天，两个人，总预算上限5000元能不能覆盖旅行费用？ | changsha | guilin | 4 | 3 | 2 | 1 | 5000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 510 | 540 | 570 | 71.25 | 122 | 0 | 1742 | 174.2 | 190 | 760 | 2676.2 | 2323.8 | 2323.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006","gl007","gl008"] | 无 |
| ctp100_v2_046 | budget_query | 北京玩2天，4个人，总预算上限2500元够吗？我还没确定从哪里出发。 |  | beijing | 2 | 1 | 4 | 2 | 2500 | destination_local_only | destination_local_only | destination_local_only | 是 | insufficient | economy | economy | 620 | 660 | 990 | 123.75 | 48 | 0 | 2318 | 231.8 |  | 0 | 2549.8 | 0 | 0 | 49.8 | 是 | 是 | economic_baseline_over_budget | ["bj001","bj002","bj003","bj004"] | 无 |
| ctp100_v2_047 | budget_query | 从南京去杭州玩3天，两个人，总共最多花8000元，大概会剩多少？ | nanjing | hangzhou | 3 | 2 | 2 | 1 | 8000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 | 103 | 412 | 2392 | 5608 | 5608 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_048 | budget_query | 从拉萨去西安玩3天，两个人，总预算上限8000元够不够？ | lhasa | xian | 3 | 2 | 2 | 1 | 8000 | local_only_route_uncovered | local_plus_round_trip_intercity | local_only_route_uncovered | 否 | indeterminate | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 |  | 0 | 1907.4 |  | 6092.6 | 0 | 否 | 否 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_049 | budget_query | 深圳玩3天，两个人，总预算上限6000元，只想知道当地吃住行大概要多少。 |  | shenzhen | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 3921 | 3921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_050 | budget_query | 桂林玩3天，两个人，总预算上限3000元，帮我看看当地旅行费用能不能控制住。 |  | guilin | 3 | 2 | 2 | 1 | 3000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 |  | 0 | 1355.2 | 1644.8 | 1644.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_051::t1 | trip_planning | 北京玩3天，两个人，日期没定，总预算上限5000元，先帮我安排一版。 |  | beijing | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 2866 | 2866 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_051::t2 | partial_replan | 路线不用改，总预算上限降到3500元，重新判断一下费用。 |  | beijing | 3 | 2 | 2 | 1 | 3500 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 1366 | 1366 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_052::t1 | trip_planning | 明天从上海去杭州玩3天，两个人，总预算上限4500元，帮我规划一下。 | shanghai | hangzhou | 3 | 2 | 2 | 1 | 4500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 | 83 | 332 | 2312 | 2188 | 2188 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_052::t2 | partial_replan | 路线和人数都不变，总预算上限提高到5500元，重新算一下。 | shanghai | hangzhou | 3 | 2 | 2 | 1 | 5500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 | 83 | 332 | 2312 | 3188 | 3188 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_053::t1 | trip_planning | 从成都去西安玩3天，两个人，日期没定，总预算上限5000元。 | chengdu | xian | 3 | 2 | 2 | 1 | 5000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 | 285 | 1140 | 3047.4 | 1952.6 | 1952.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_053::t2 | partial_replan | 总预算上限改成4000元，其他条件不要动。 | chengdu | xian | 3 | 2 | 2 | 1 | 4000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 | 285 | 1140 | 3047.4 | 952.6 | 952.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_054::t1 | trip_planning | 明天从广州去深圳玩2天，3个人，总预算上限4000元。 | guangzhou | shenzhen | 2 | 1 | 3 | 2 | 4000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 285 | 720 | 742.5 | 123.75 | 129 | 0 | 1876.5 | 187.65 | 74.5 | 447 | 2511.15 | 1488.85 | 1488.85 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004"] | 无 |
| ctp100_v2_054::t2 | partial_replan | 总预算上限提高到6000元，不用重新安排行程。 | guangzhou | shenzhen | 2 | 1 | 3 | 2 | 6000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 285 | 720 | 742.5 | 123.75 | 129 | 0 | 1876.5 | 187.65 | 74.5 | 447 | 2511.15 | 3488.85 | 3488.85 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004"] | 无 |
| ctp100_v2_055::t1 | trip_planning | 明天从广州去桂林玩3天，两个人，总预算上限5000元。 | guangzhou | guilin | 3 | 2 | 2 | 1 | 5000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 | 200 | 800 | 2155.2 | 2844.8 | 2844.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_055::t2 | partial_replan | 又有一个朋友加入，现在一共3个人，预算上限不变。 | guangzhou | guilin | 3 | 2 | 3 | 2 | 5000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 525 | 720 | 630 | 70 | 153 | 0 | 2028 | 202.8 | 200 | 1200 | 3430.8 | 1569.2 | 1569.2 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_056::t1 | trip_planning | 我一个人从上海去北京玩2天，日期没定，总预算上限3500元。 | shanghai | beijing | 2 | 1 | 1 | 1 | 3500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 155 | 330 | 247.5 | 123.75 | 12 | 0 | 744.5 | 74.45 | 661 | 1322 | 2140.95 | 1359.05 | 1359.05 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004"] | 无 |
| ctp100_v2_056::t2 | partial_replan | 再加一个朋友，变成两个人，其他条件不变。 | shanghai | beijing | 2 | 1 | 2 | 1 | 3500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | insufficient | economy | economy | 310 | 330 | 495 | 123.75 | 24 | 0 | 1159 | 115.9 | 661 | 2644 | 3918.9 | 0 | 0 | 418.9 | 是 | 是 | economic_baseline_over_budget | ["bj001","bj002","bj003","bj004"] | 无 |
| ctp100_v2_057::t1 | trip_planning | 后天去杭州玩3天，我们两个人，总预算上限5000元。 |  | hangzhou | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 |  | 0 | 1980 | 3020 | 3020 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_057::t2 | partial_replan | 再加一个人，现在一共3个人，其他都不变。 |  | hangzhou | 3 | 2 | 3 | 2 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 585 | 1280 | 1050 | 116.67 | 105 | 0 | 3020 | 302 |  | 0 | 3322 | 1678 | 1678 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_058::t1 | trip_planning | 明天从郑州去西安玩3天，3个人，总预算上限6000元。 | zhengzhou | xian | 3 | 2 | 3 | 2 | 6000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 840 | 1040 | 840 | 93.33 | 141 | 0 | 2861 | 286.1 | 221 | 1326 | 4473.1 | 1526.9 | 1526.9 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_058::t2 | partial_replan | 有一个人去不了了，改成两个人。 | zhengzhou | xian | 3 | 2 | 2 | 1 | 6000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 | 221 | 884 | 2791.4 | 3208.6 | 3208.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_059::t1 | trip_planning | 明天去深圳玩2天，两个人，总预算上限4000元。 |  | shenzhen | 2 | 1 | 2 | 1 | 4000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 190 | 360 | 495 | 123.75 | 86 | 0 | 1131 | 113.1 |  | 0 | 1244.1 | 2755.9 | 2755.9 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004"] | 无 |
| ctp100_v2_059::t2 | partial_replan | 多玩一天，改成3天，其他条件不变。 |  | shenzhen | 3 | 2 | 2 | 1 | 4000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 1921 | 1921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_060::t1 | trip_planning | 桂林玩4天，两个人，日期没定，总预算上限6000元。 |  | guilin | 4 | 3 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 510 | 540 | 570 | 71.25 | 122 | 0 | 1742 | 174.2 |  | 0 | 1916.2 | 4083.8 | 4083.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006","gl007","gl008"] | 无 |
| ctp100_v2_060::t2 | partial_replan | 时间不够了，缩短成3天。 |  | guilin | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 |  | 0 | 1355.2 | 4644.8 | 4644.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_061::t1 | trip_planning | 后天去北京玩3天，两个人，总预算上限5000元。 |  | beijing | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 2866 | 2866 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_061::t2 | partial_replan | 改成只玩2天，其他条件都不变。 |  | beijing | 2 | 1 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 310 | 330 | 495 | 123.75 | 24 | 0 | 1159 | 115.9 |  | 0 | 1274.9 | 3725.1 | 3725.1 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004"] | 无 |
| ctp100_v2_062::t1 | trip_planning | 9月4号去杭州玩3天，两个人，总预算上限5000元。 |  | hangzhou | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 |  | 0 | 1980 | 3020 | 3020 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_062::t2 | partial_replan | 改成只玩2天。 |  | hangzhou | 2 | 1 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 320 | 450 | 112.5 | 50 | 0 | 1090 | 109 |  | 0 | 1199 | 3801 | 3801 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004"] | 无 |
| ctp100_v2_063::t1 | trip_planning | 后天去西安玩3天，两个人，总预算上限5000元。 |  | xian | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 |  | 0 | 1907.4 | 3092.6 | 3092.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_063::t2 | partial_replan | 我妈妈膝盖不太好，把节奏放慢，少安排需要长时间步行的景点。 |  | xian | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 |  | 0 | 1907.4 | 3092.6 | 3092.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_064::t1 | trip_planning | 明天去深圳玩3天，两个人，总预算上限6000元。 |  | shenzhen | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 3921 | 3921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_064::t2 | partial_replan | 我比较怕晒，多安排室内场馆，别改日期和预算。 |  | shenzhen | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 3921 | 3921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_065::t1 | trip_planning | 桂林玩3天，两个人，日期没定，总预算上限5000元。 |  | guilin | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 |  | 0 | 1355.2 | 3644.8 | 3644.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_065::t2 | partial_replan | 我们不想坐船，请在其他条件不变的情况下重新安排。 |  | guilin | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 |  | 0 | 1355.2 | 3644.8 | 3644.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_066::t1 | trip_planning | 明天去北京玩3天，3个人，总预算上限7000元。 |  | beijing | 3 | 2 | 3 | 2 | 7000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 705 | 1320 | 1155 | 128.33 | 60 | 0 | 3240 | 324 |  | 0 | 3564 | 3436 | 3436 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_066::t2 | partial_replan | 我们更想看博物馆和历史文化场馆，少安排长时间户外项目。 |  | beijing | 3 | 2 | 3 | 2 | 7000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 705 | 1320 | 1155 | 128.33 | 60 | 0 | 3240 | 324 |  | 0 | 3564 | 3436 | 3436 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_067::t1 | trip_planning | 杭州玩3天，两个人，日期没定，总预算上限5000元。 |  | hangzhou | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 |  | 0 | 1980 | 3020 | 3020 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_067::t2 | partial_replan | 我们从南京出发，其他条件不变，不用重新排路线。 | nanjing | hangzhou | 3 | 2 | 2 | 1 | 5000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 | 103 | 412 | 2392 | 2608 | 2608 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_068::t1 | trip_planning | 明天去西安玩3天，两个人，总预算上限5500元。 |  | xian | 3 | 2 | 2 | 1 | 5500 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 |  | 0 | 1907.4 | 3592.6 | 3592.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_068::t2 | partial_replan | 我们从成都出发，只把往返高铁算进去，行程不要改。 | chengdu | xian | 3 | 2 | 2 | 1 | 5500 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 | 285 | 1140 | 3047.4 | 2452.6 | 2452.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_069::t1 | trip_planning | 深圳玩2天，两个人，日期没定，总预算上限4000元。 |  | shenzhen | 2 | 1 | 2 | 1 | 4000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 190 | 360 | 495 | 123.75 | 86 | 0 | 1131 | 113.1 |  | 0 | 1244.1 | 2755.9 | 2755.9 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004"] | 无 |
| ctp100_v2_069::t2 | partial_replan | 我们从武汉出发，其他条件不变。 | wuhan | shenzhen | 2 | 1 | 2 | 1 | 4000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 190 | 360 | 495 | 123.75 | 86 | 0 | 1131 | 113.1 | 627.5 | 2510 | 3754.1 | 245.9 | 245.9 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004"] | 无 |
| ctp100_v2_070::t1 | trip_planning | 后天去北京玩3天，两个人，总预算上限5000元，帮我做个行程。 |  | beijing | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 2866 | 2866 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_070::t2 | weather_adjustment | 把你已经推荐的室内景点放到有降雨风险的时段，其他景点不变。 |  | beijing | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 2866 | 2866 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_071::t1 | trip_planning | 明天去杭州玩3天，两个人，总预算上限5000元。 |  | hangzhou | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 |  | 0 | 1980 | 3020 | 3020 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_071::t2 | weather_adjustment | 根据刚才查到的降雨情况重新调整顺序，使用已经推荐的室内景点，不要新增景点。 |  | hangzhou | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 390 | 640 | 700 | 116.67 | 70 | 0 | 1800 | 180 |  | 0 | 1980 | 3020 | 3020 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004","hz005","hz006"] | 无 |
| ctp100_v2_072::t1 | trip_planning | 后天去西安玩3天，两个人，总预算上限5000元，先给我一版常规行程。 |  | xian | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 |  | 0 | 1907.4 | 3092.6 | 3092.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_072::t2 | weather_adjustment | 根据刚才查到的天气，把不适合户外的时段调整一下，只换顺序，不换景点。 |  | xian | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 |  | 0 | 1907.4 | 3092.6 | 3092.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_073::t1 | trip_planning | 明天去深圳玩3天，两个人，总预算上限6000元，先安排一版包含户外项目的行程。 |  | shenzhen | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 3921 | 3921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_073::t2 | weather_adjustment | 我比较怕晒，按照刚才查到的高温情况减少中午户外活动，其他条件不变。 |  | shenzhen | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 3921 | 3921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_074::t1 | trip_planning | 明天去桂林玩3天，带爸妈一起，一共3个人，总预算上限7000元。 |  | guilin | 3 | 2 | 3 | 2 | 7000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 525 | 720 | 630 | 70 | 153 | 0 | 2028 | 202.8 |  | 0 | 2230.8 | 4769.2 | 4769.2 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_074::t2 | weather_adjustment | 老人怕热，把高温时段改成室内活动或休息，景点总数不要增加。 |  | guilin | 3 | 2 | 3 | 2 | 7000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 525 | 720 | 630 | 70 | 153 | 0 | 2028 | 202.8 |  | 0 | 2230.8 | 4769.2 | 4769.2 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_075::t1 | trip_planning | 后天去北京玩3天，两个人，总预算上限5000元，先按完整行程安排一版。 |  | beijing | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 2866 | 2866 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_075::t2 | partial_replan | 出发时间改成9月4号，天数和其他条件不变。 |  | beijing | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 470 | 660 | 770 | 128.33 | 40 | 0 | 1940 | 194 |  | 0 | 2134 | 2866 | 2866 | 0 | 否 | 是 | economic_baseline | ["bj001","bj002","bj003","bj004","bj005","bj006"] | 无 |
| ctp100_v2_076::t1 | trip_planning | 9月5号去杭州玩2天，两个人，总预算上限4000元。 |  | hangzhou | 2 | 1 | 2 | 1 | 4000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 320 | 450 | 112.5 | 50 | 0 | 1090 | 109 |  | 0 | 1199 | 2801 | 2801 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004"] | 无 |
| ctp100_v2_076::t2 | partial_replan | 改成明天出发，其他条件不变。 |  | hangzhou | 2 | 1 | 2 | 1 | 4000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 320 | 450 | 112.5 | 50 | 0 | 1090 | 109 |  | 0 | 1199 | 2801 | 2801 | 0 | 否 | 是 | economic_baseline | ["hz001","hz002","hz003","hz004"] | 无 |
| ctp100_v2_077::t1 | trip_planning | 明天去西安玩3天，两个人，总预算上限5000元。 |  | xian | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 |  | 0 | 1907.4 | 3092.6 | 3092.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_077::t2 | partial_replan | 时间改成一个月后，其他条件不变。 |  | xian | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 560 | 520 | 560 | 93.33 | 94 | 0 | 1734 | 173.4 |  | 0 | 1907.4 | 3092.6 | 3092.6 | 0 | 否 | 是 | economic_baseline | ["xa001","xa002","xa003","xa004","xa005","xa006"] | 无 |
| ctp100_v2_078::t1 | trip_planning | 一个月后去深圳玩3天，两个人，总预算上限6000元。 |  | shenzhen | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 3921 | 3921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_078::t2 | partial_replan | 还是提前到后天出发吧，其他条件不变。 |  | shenzhen | 3 | 2 | 2 | 1 | 6000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 270 | 720 | 770 | 128.33 | 130 | 0 | 1890 | 189 |  | 0 | 2079 | 3921 | 3921 | 0 | 否 | 是 | economic_baseline | ["sz001","sz002","sz003","sz004","sz005","sz006"] | 无 |
| ctp100_v2_079::t1 | trip_planning | 9月4号去桂林玩3天，两个人，总预算上限5000元。 |  | guilin | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 |  | 0 | 1355.2 | 3644.8 | 3644.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_079::t2 | partial_replan | 改成后天出发，天数和其他条件不变。 |  | guilin | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 |  | 0 | 1355.2 | 3644.8 | 3644.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_087::t1 | trip_planning | 桂林玩3天，两个人，日期没定，总预算上限5000元，先帮我安排一版轻松点的行程。 |  | guilin | 3 | 2 | 2 | 1 | 5000 | destination_local_only | destination_local_only | destination_local_only | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 |  | 0 | 1355.2 | 3644.8 | 3644.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
| ctp100_v2_087::t2 | partial_replan | 我们从广州出发，想重新安排行程。 | guangzhou | guilin | 3 | 2 | 2 | 1 | 5000 | local_plus_round_trip_intercity | local_plus_round_trip_intercity | local_plus_round_trip_intercity | 是 | sufficient | economy | economy | 350 | 360 | 420 | 70 | 102 | 0 | 1232 | 123.2 | 200 | 800 | 2155.2 | 2844.8 | 2844.8 | 0 | 否 | 是 | economic_baseline | ["gl001","gl002","gl003","gl004","gl005","gl006"] | 无 |
