# Tourism Agent 智慧旅游规划系统

Tourism Agent 是一个基于多 Agent 协作的智慧旅游规划研究原型。系统面向论文实验和答辩展示，支持旅游意图识别、信息补全、景点推荐、行程生成、预算估算、天气查询、方案审查和多轮追问。

## 核心能力

- 多 Agent 协作：编排器根据用户意图选择 Planner、Attraction、Itinerary、Budget、Weather、Review 等 Agent。
- 多轮对话：支持新规划、追问、澄清回答和已有行程的 follow-up 调整。
- 流式输出：`/chat/stream` 通过 SSE 返回阶段更新、思考步骤和正文增量。
- 本地数据与兜底数据：景点、天气、餐饮、案例和缓存数据放在 `data/` 下。
- 实验观测：Trace 默认关闭，可按请求记录论文实验需要的链路指标。
- 前端展示：`frontend/` 提供 Next.js 单页聊天式展示界面。

## 系统架构

```text
用户 / 前端
    |
FastAPI 接口层
    |
AgentOrchestrator
    |
+----------------+----------------+----------------+----------------+
| Attraction     | Weather        | Itinerary      | Budget         |
| 景点推荐        | 天气查询        | 行程规划        | 预算估算        |
+----------------+----------------+----------------+----------------+
    |
Planner / Review
    |
最终旅游方案
```

## 目录结构

```text
Tourism_Agent/
├─ app/
│  ├─ agents/              # 业务 Agent
│  │  ├─ orchestrator.py   # 核心编排器
│  │  ├─ planner.py        # 总方案生成
│  │  ├─ attraction.py     # 景点推荐
│  │  ├─ itinerary.py      # 行程规划
│  │  ├─ budget.py         # 预算估算
│  │  ├─ weather.py        # 天气查询
│  │  └─ review.py         # 方案审查
│  ├─ api/                 # FastAPI 入口
│  ├─ core/                # 配置、上下文、LLM、Trace、工具执行等核心能力
│  ├─ services/            # 数据服务
│  ├─ storage/             # 数据库、缓存、向量存储封装
│  └─ tools/               # POI、天气、路线、预算等工具
├─ data/                   # 本地数据、案例、缓存和兜底数据
├─ docs/                   # 设计和实验文档
├─ frontend/               # Next.js 前端
├─ tests/                  # 自动化测试
├─ .env.example            # 环境变量示例
├─ requirements.txt        # Python 依赖
└─ README.md
```

## 主要模块

| 模块 | 说明 |
|------|------|
| `app/agents/orchestrator.py` | 请求主链路，负责模式判断、意图解析、路由、任务规划和 Agent 调度 |
| `app/agents/planner.py` | 整合景点、天气、行程和预算结果，生成最终方案 |
| `app/agents/attraction.py` | 使用 POI 数据和工具生成景点推荐 |
| `app/agents/itinerary.py` | 根据天数、景点和约束生成每日行程 |
| `app/agents/budget.py` | 估算交通、住宿、餐饮、门票和缓冲费用 |
| `app/agents/weather.py` | 查询天气并生成出行建议 |
| `app/core/llm/` | LLM 客户端、管理器、缓存和降级逻辑 |
| `app/core/context.py` | 会话上下文、执行上下文、思考步骤、工具调用和 API 调用结构 |
| `app/core/tracing.py` | 请求级全链路 Trace，默认关闭 |
| `app/tools/` | 工具基类和具体工具实现 |

## 环境要求

- Python 3.11+
- Node.js 和 npm，用于运行前端
- Redis、PostgreSQL、Qdrant/Milvus/Chroma 为可选能力，当前研究原型可使用本地兜底数据运行

## 安装依赖

```bash
pip install -r requirements.txt
```

前端依赖：

```bash
cd frontend
npm install
```

## 配置环境变量

复制示例文件：

```bash
cp .env.example .env
```

常用配置项：

```env
LLM_MODEL=qwen/qwen3-30b-a3b:free
LLM_API_KEY=your_openrouter_api_key_here
AMAP_API_KEY=your_amap_api_key_here
ENABLE_TRACING=false
TRACE_OUTPUT_DIR=experiments/results/traces
```

不要提交 `.env` 或任何真实密钥。

## 启动后端

```bash
python -m app.main --mode web --host 127.0.0.1 --port 8000
```

常用接口：

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/chat` | POST | 非流式聊天接口 |
| `/chat/stream` | POST | SSE 流式聊天接口 |
| `/session/reset` | POST | 重置会话 |
| `/feedback` | POST | 提交反馈 |

## 启动前端

```bash
cd frontend
npm run dev
```

默认访问：

```text
http://localhost:3000
```

## 运行模式

| 模式 | 启动方式 | 适用场景 |
|------|----------|----------|
| dev | `npm run dev` | 日常开发和调试 |
| demo | `NEXT_PUBLIC_APP_MODE=demo npm run dev` | 答辩、录屏、演示 |
| production | `npm run build && npm run start` | 最接近正式部署的验证 |

## 请求级 Trace

Trace 用于论文实验，默认关闭。开启后，每个请求会在 `experiments/results/traces/` 生成一个 JSONL 文件。

```env
ENABLE_TRACING=true
TRACE_OUTPUT_DIR=experiments/results/traces
```

Trace 记录内容包括 request/session 信息、模式、意图、路由、抽取槽位、缺失字段、实际 Agent、阶段耗时、Agent 耗时、LLM 调用、工具/API 调用、TTFT、总耗时和错误信息。字段说明见 [docs/TRACE_FIELDS.md](docs/TRACE_FIELDS.md)。

Trace 不记录完整 Prompt、API Key、授权头、密码、token 或内部思维链。

## 测试

编译检查：

```bash
python -m compileall app
```

运行测试：

```bash
pytest -q
```

## Unified Planner Baseline

默认对话入口 `/chat` 和 `/chat/stream` 仍使用多 Agent 主链路。

`app/agents/unified_planner.py` 保留为单 Agent / 单轮规划 baseline，用于论文实验对比、效果对照和独立测试。`/api/v1/plan/unified` 仅作为可选 baseline 接口保留，不是默认主流程。

## 许可证

MIT
