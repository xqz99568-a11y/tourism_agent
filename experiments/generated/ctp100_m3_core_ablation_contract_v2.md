# CTP100 M3 两项核心消融实验冻结协议 v2（结果前哈希纠错）

- 协议编号：`ctp100_m3_core_ablation_20260907_v2`
- 基础协议：`experiments/generated/ctp100_m3_core_ablation_contract_v1.json`
- 状态：在任何核心消融 LLM 调用及结果查看之前冻结。

v1 的方法、案例、比较对象、指标和运行规模全部保持不变。v2 只纠正一个
无法复现的记录字段：v1 将“选中案例集合 SHA-256”写为 `33ba8cbc...`，但该值
无法从冻结题库和声明的选择规则复算。

v2 明确哈希对象为“按冻结题库原顺序排列的30个完整案例对象组成的 JSON
列表”，采用 `canonical_json_utf8_sort_keys_v1` 计算，正确值为：

`f6082726bd82f11ca8f8c330bdfc67c040ed2f5ab56a2915ac95b3a8f179274f`

没有更换任何题目，没有按模型成败选择案例，也没有更改以下两个新增方法：

- `adaptive_multi_agent_no_state`
- `adaptive_multi_agent_no_propagation`

运行规模仍为30个双轮案例、两个新增方法、3次重复，共 `360` 条原始结果；
主要评价仍只使用第二轮。M3-full 与 M3-no-reuse 的既有比较文件及其冻结哈希
全部沿用v1。模型仍为 `gpt-5-mini`，温度0，最大输出4096 tokens，推理强度
`minimal`。

运行器必须同时核验v1原始文件哈希和v2修订文件哈希，再形成有效协议视图。
论文中应如实说明：实现门禁时在结果产生前发现并修正了一个不可复现的集合
哈希记录；此修订没有改变研究设计或实验范围。
