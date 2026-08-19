# Budget Policy v2.0：冻结参考预算与三态充足性规则

本规则用于 Tourism_Agent 的正式实验与 CLI 演示。目标是把预算估算改成可复现、可审计、可评价的冻结参考成本模型，而不是让大模型自由心算。

## 核心原则

预算金额只用于判断“够不够、缺多少、在已覆盖范围内剩多少”，不得自动改变住宿或餐饮档次。

用户未明确提出消费档次时，主预算方案固定为：

```text
hotel_tier = economy
food_tier = economy
```

只有用户明确提出“舒适、中档、品质、高端、豪华、住好一点、吃好一点、特色美食”等消费档次要求时，系统演示或开发检查才允许在主预算方案中使用 `comfort` 或 `premium`。如果明确偏好的方案超预算，也不得自动降档，应保持该档次并报告预算缺口。

需要注意：本次正式主实验只确认和评价 `economy` 预算基线。`comfort` / `premium` 可用于开发集档次识别测试、CLI 可选升级说明或后续扩展研究，但不属于本次论文主实验的人工确认预算金标范围。

## 费用组成

```text
住宿晚数 N = max(旅行天数 D - 1, 0)
房间数 R = ceil(人数 P / 2)
餐饮折算次数 = 2 * D + 0.5 * N

当地基础费用 =
住宿 + 餐饮 + 景点门票 + 市内交通 + 其他当地费用

建议备用金 = 当地基础费用 * 10%

最终建议准备金额 =
当地基础费用 + 建议备用金 + 城际交通费用
```

城际高铁/动车费用不增加 10% 备用金。购物、纪念品等个人消费不纳入基础预算。

## 餐饮计算

正式主实验先保留当前经济档公式：

```text
food_cost =
城市 economy 中位单餐参考价
* people_count
* (2 * duration_days + 0.5 * nights)
```

含义：

- 每个游玩日按午餐和晚餐 2 次普通正餐计算；
- 每个住宿晚按普通正餐价格的 50% 计入早餐；
- 这是冻结实验参考规则，不是实时消费承诺；
- 五个正式城市的 `economy` 餐饮参考值已在 `experiments/generated/economy_budget_manual_review_v1.json` 中确认。
- `comfort` / `premium` 不进入本次正式主实验预算金标确认范围，餐饮审阅表只保留为开发检查或后续扩展研究材料。

## 预算范围字段

预算结果同时记录：

- `requested_budget_scope`：用户请求的预算范围；
- `computed_budget_scope`：系统实际完成计算的预算范围；
- `scope_complete`：实际计算范围是否覆盖用户请求；
- `sufficiency_status`：三态预算结论；
- `covered_scope_remaining_budget`：已覆盖范围内的剩余预算。

`budget_scope` 作为兼容字段保留，含义等同 `computed_budget_scope`。

## 三态预算结论

`sufficiency_status` 只允许：

- `sufficient`
- `insufficient`
- `indeterminate`

规则：

1. 用户明确只问当地费用时，`requested_budget_scope=destination_local_only`。只要当地费用计算完整，就可以判断 `sufficient` 或 `insufficient`，不因缺少出发地变成 `indeterminate`。
2. 用户问完整旅行但缺少城际费用时：
   - 已知费用已经超过预算：`insufficient`；
   - 已知费用没有超过预算：`indeterminate`。
3. `scope_complete=false` 且结论为 `indeterminate` 时，`remaining_budget` 不得表达为完整旅行剩余预算；只能使用 `covered_scope_remaining_budget` 表示已覆盖范围内的剩余。

## 城际交通

有出发地且冻结铁路表支持路线时：

```text
城际交通费用 = 成人二等座单程票价 * 2 * 人数
```

无出发地或铁路路线未覆盖时，不猜票价、不联网补数据、不自动改飞机，只计算已覆盖范围并给出明确说明。

## 多轮预算规则

- 只修改 `budget_amount`：保留原行程、POI、`hotel_tier`、`food_tier` 和各项原始费用，只重新计算剩余、缺口、是否超预算和三态结论。
- 只补充 `origin`：当地住宿、餐饮、门票、市内交通和当地基础费用必须与上一轮一致，只新增城际交通费用。
- 只修改 `people_count` 或 `duration_days`：保留原 `hotel_tier` 和 `food_tier`，按新人数、天数、晚数和房间数重新计算。
- 出现“其他条件不变”“只把高铁算进去”“不用重新排路线”等表达时，必须进入 preserved-slot 检查。

## BPCR 评价口径

- 没有显式档次约束的案例，档次选择子项可记为 `NA`；不能让“永远输出 economy”自动获得区分性分数。
- 有显式住宿或餐饮档次要求时，系统必须尊重要求。
- `comfort` / `premium` 可以作为明确标注的可选升级方案，但不得替换无显式档次要求时的主经济方案；本次正式主实验不报告它们的预算准确性结论。
- 正式结果门禁必须确认每条方法结果存在 `bpcr` 字段，并且 CTP100 主基准的 BPCR 可进入方法均值、M3-vs-M2 配对统计和论文结果包。

## 论文实验公平性

- M1、M2、M3 调用同一个预算计算器。
- 所有金额由预算工具执行，大模型不得自由心算。
- 每个方法按自己的最终行程景点和顺序计算预算。
- 正式预算金标金额由程序根据冻结数据生成，不人工填写金额；但 `review_status=confirmed` 必须来自已校验的经济型人工审核账本。
- 论文中应称为“冻结参考成本模型”，不能声称是实时市场报价。
