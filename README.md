# Tourism_Agent - 智慧文旅多Agent系统

基于大语言模型的多Agent协作的智慧文旅系统，支持智能旅游规划、景点推荐、行程安排等功能。

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                      客户端层 (Frontend)                   │
│           Web App / 小程序 / 浏览器插件 / API Gateway      │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    API Gateway                           │
│            (限流 / 鉴权 / 路由 / 监控)                      │
└────────────────────────┬────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Chat Service │  │ Planning Svc │  │ Search Svc   │
│  (对话服务)    │  │  (规划服务)   │  │  (搜索服务)   │
└───────────────┘  └──────────────┘  └──────────────┘
        │                │                │
        └────────────────┼────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│                    Agent Orchestrator                     │
│              (Agent 编排器 / 任务调度中心)                  │
└────────────────────────┬─────────────────────────────────┘
                         │
     ┌───────────┬───────┼───────┬───────────┐
     ▼           ▼       ▼       ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────┐ ┌─────────┐ ┌─────────┐
│ Planner │ │Searcher│ │Route│ │ Budget  │ │Weather  │
│  Agent  │ │  Agent  │ │Agent│ │  Agent  │ │  Agent  │
└─────────┘ └─────────┘ └─────┘ └─────────┘ └─────────┘
     │           │       │       │           │
     └───────────┴───────┼───────┴───────────┘
                         ▼
┌──────────────────────────────────────────────────────────┐
│                       Memory Layer                        │
│    (短期记忆: Redis)  │  (长期记忆: Vector DB)             │
└──────────────────────────────────────────────────────────┘
                         │
┌──────────────────────────────────────────────────────────┐
│                      Tool Layer                           │
│   POI搜索  │ 路线规划  │ 天气查询  │ 预算计算  │ 网页搜索  │
└──────────────────────────────────────────────────────────┘
```

## 核心模块

### 1. Agent 层 (`app/core/agent/`)

| 模块 | 文件 | 说明 |
|------|------|------|
| **Protocol** | `protocol.py` | Agent 接口协议定义，包含 `AgentProtocol` 抽象基类、任务状态、结果类型 |
| **BaseAgent** | `base.py` | 基于 Protocol 的 Agent 基类，支持事件驱动、生命周期管理 |
| **MessageBus** | `message_bus.py` | 事件驱动的消息总线，支持 Pub/Sub、请求-响应、广播模式 |
| **Registry** | `registry.py` | Agent 注册中心，管理 Agent 生命周期和依赖注入 |

### 2. LLM 层 (`app/core/llm/`)

| 模块 | 文件 | 说明 |
|------|------|------|
| **Client** | `client.py` | LLM 客户端封装，支持 OpenRouter、OpenAI、SiliconFlow、智谱 GLM 等 |
| **Manager** | `manager.py` | LLM 管理器，整合路由、语义缓存、故障降级 |
| **Router** | `router.py` | 模型路由器，基于任务类型选择最优模型 |

### 3. 业务 Agent 层 (`app/agents/`)

| Agent | 文件 | 职责 |
|-------|------|------|
| **Orchestrator** | `orchestrator.py` | 核心编排器，协调多 Agent 协作 |
| **Planner** | `planner.py` | 主规划 Agent |
| **Attraction** | `attraction.py` | 景点推荐 |
| **Itinerary** | `itinerary.py` | 行程规划 |
| **Budget** | `budget.py` | 预算分析 |
| **Weather** | `weather.py` | 天气查询与行程调整 |

### 4. 工具层 (`app/tools/`)

| 工具 | 文件 | 说明 |
|------|------|------|
| **BaseTool** | `base.py` | 工具基类和注册中心 |
| **POISearch** | `poi_search.py` | 高德地图 POI 搜索 |
| **Weather** | `weather.py` | 天气查询 |
| **RoutePlan** | `route_plan.py` | 路线规划 |
| **BudgetCalc** | `budget_calc.py` | 预算计算 |

### 5. 存储层 (`app/storage/`)

| 模块 | 文件 | 说明 |
|------|------|------|
| **SessionStore** | `session_store.py` | Redis 会话存储 |
| **VectorStore** | `vector_store.py` | 向量数据库 (Qdrant/Milvus/Chroma) |

## 新增架构组件

### 6. 核心架构 (`app/core/`)

| 模块 | 文件 | 说明 |
|------|------|------|
| **Dependency Injection** | `di.py` | 依赖注入容器，支持单例/工厂模式、异步初始化、生命周期管理 |
| **Middleware** | `middleware.py` | 中间件层：追踪、缓存、限流 |
| **Tool Strategy** | `tool_strategy.py` | 工具策略模式，支持重试、超时、降级、熔断等 |
| **Tool Executor** | `tool_executor.py` | 工具执行器，支持并发执行、错误重试、循环调用 |
| **Orchestration** | `orchestration.py` | 任务分解器(DAG)与 DAG 调度器 |
| **RAG** | `rag.py` | 检索增强生成，景点知识库 |
| **Config** | `config.py` | Pydantic 配置管理 |

### 7. 增强 Agent (`app/core/agent/`)

| Agent | 文件 | 说明 |
|-------|------|------|
| **Memory Agent** | `memory_agent.py` | 记忆管理 Agent，支持情景/语义/程序记忆 |
| **Reflection Agent** | `reflection_agent.py` | 自我反思 Agent，检查结果质量 |
| **Quality Agent** | `quality_agent.py` | 质量评估 Agent，多维度质量审查 |
| **Personalization Agent** | `personalization_agent.py` | 个性化 Agent，用户画像学习 |

### 8. API 网关 (`app/api/`)

| 模块 | 文件 | 说明 |
|------|------|------|
| **Gateway** | `gateway.py` | API 网关，包含认证、限流、监控 |
| **Main** | `main.py` | FastAPI 主入口 |

### 9. 服务层 (`app/services/`)

| 模块 | 文件 | 说明 |
|------|------|------|
| **Preference Service** | `preference_service.py` | 用户偏好持久化与学习 |

## 架构特性

### LLM 层 (`app/core/llm/`)

项目已经实现了完整的 LLM 调用架构：

| 模块 | 文件 | 说明 |
|------|------|------|
| **Client** | `client.py` | LLM 客户端，支持 OpenRouter、OpenAI、SiliconFlow、智谱 GLM |
| **Manager** | `manager.py` | 增强版 LLM 管理器，整合路由、语义缓存、故障降级 |
| **Router** | `router.py` | 模型路由器，基于任务类型选择最优模型 |
| **Cache** | `cache.py` | 语义缓存，支持精确匹配和语义相似度匹配 |
| **Fallback** | `fallback.py` | 降级链，支持熔断、重试、超时控制 |

**LLM 调用示例**：

```python
from app.core.llm.manager import EnhancedLLMManager

llm = EnhancedLLMManager()
response = await llm.chat(
    messages=[LLMMessage(role="user", content="Hello")],
    task_type=TaskType.SIMPLE_CHAT,
    agent_name="planner",
)
```

### 依赖注入 (DI)

使用 `app/core/di.py` 中的 `Container` 类实现：

```python
from app.core.di import get_container, injectable

# 注册依赖
container = get_container()
container.register("llm_manager", LLMManager, singleton=True)

# 获取依赖
llm = await container.get("llm_manager")
```

### 策略模式 (Tool Strategy)

使用 `app/core/tool_strategy.py` 统一工具调用：

```python
from app.core.tool_strategy import (
    ToolStrategyType, RetryToolStrategy, TimeoutToolStrategy
)

# 使用重试策略
strategy = RetryToolStrategy(max_retries=3)
result = await strategy.execute(tool, params)
```

### 中间件层

使用 `app/core/middleware.py`：

```python
from app.core.middleware import traced, cached, get_cache

# 追踪装饰器
@traced("my_function")
async def my_function():
    pass

# 缓存装饰器
@cached(ttl=300)
async def my_cached_function():
    pass
```

### 消息总线

使用 `app/core/agent/message_bus.py`：

```python
# 发布消息
await message_bus.publish(topic="agent:update", sender="orchestrator", payload=data)

# 订阅消息
message_bus.subscribe(agent_name="planner", topic="task:planner", callback=handler)

# 请求-响应
response = await message_bus.request(recipient="planner", topic="query", payload=data)
```

### RAG 检索

使用 `app/core/rag.py`：

```python
from app.core.rag import get_rag_engine

rag = get_rag_engine()
result = await rag.query(question="北京有哪些景点值得去？", top_k=5)
```

### 任务编排

使用 `app/core/orchestration.py` 中的任务分解器和 DAG 调度器：

```python
from app.core.orchestration import get_task_decomposer, get_dag_scheduler

# 分解任务
decomposer = get_task_decomposer(llm)
graph = await decomposer.decompose_with_llm(user_message, context)

# 执行 DAG
scheduler = get_dag_scheduler(registry)
results = await scheduler.execute(graph)
```

### 工具执行

使用 `app/core/tool_executor.py`：

```python
from app.core.tool_executor import ToolExecutor, ToolSelector

# 注册并执行工具
executor = ToolExecutor()
call = await executor.execute("poi_search", {"keywords": "西湖"})
results = await executor.execute_batch([...])
```

## 运行项目

### 前置条件

- Python 3.11+
- Redis
- PostgreSQL (可选)
- Qdrant/Milvus/Chroma (可选，向量数据库)

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

创建 `.env` 文件：

```env
# LLM 配置
OPENROUTER_API_KEY=your_key
LLM_PROVIDER=openrouter
LLM_MODEL=qwen/qwen3-30b-a3b:free

# 高德地图
AMAP_API_KEY=your_key

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# 向量数据库
VECTOR_DB_PROVIDER=qdrant
VECTOR_DB_HOST=localhost
VECTOR_DB_PORT=6333
```

### 启动后端

```bash
python -m app.main --mode web --host 127.0.0.1 --port 8000
```

### 启动前端

```bash
cd frontend
npm run dev
```

## 运行模式说明

本项目支持 **开发（dev）**、**展示（demo）**、**生产（production）** 三种运行模式，适用于不同场景。

### 模式对比

| 模式 | 启动方式 | 调试体验 | 页面整洁度 | 推荐场景 |
|------|---------|---------|-----------|---------|
| **dev** | `npm run dev` | 完整报错提示 | 左下角可能显示 Issues | 日常开发、调试功能 |
| **demo** | `APP_MODE=demo npm run dev` | 仍可查看控制台 | 隐藏开发浮层 | 答辩、录屏、现场演示 |
| **production** | `npm run build && npm run start` | 无开发报错 | 最干净 | 正式部署、最终交付验证 |

### 1. 开发模式（dev）

默认模式，用于日常编码和功能调试。

```bash
cd frontend
# 确保 .env.local 中有 NEXT_PUBLIC_APP_MODE=dev
npm run dev
```

**特点**：
- 保留所有 Next.js 错误浮层和 Issues 提示
- 支持 Hot Module Replacement，代码修改实时生效
- 适合修 bug、查控制台日志

### 2. 展示模式（demo）

基于开发环境的干净展示模式，隐藏左下角 Issues 和 Next.js 开发浮层，适合答辩或录屏。

```bash
cd frontend
# 临时切换到展示模式
NEXT_PUBLIC_APP_MODE=demo npm run dev
```

或在 `frontend/.env.local` 中修改（永久生效）：

```env
NEXT_PUBLIC_APP_MODE=demo
```

然后重启 `npm run dev`。

**特点**：
- 隐藏 Next.js 开发错误浮层和 Issues badge
- 仍保留浏览器控制台日志（可按 F12 查看）
- 页面主功能完全正常

> **注意**：demo 模式本质仍是开发环境下的展示增强，不是真正的生产部署。如需最稳定体验，推荐使用 production 模式。

### 3. 生产模式（production）

最接近真实交付环境的运行方式。

```bash
cd frontend
npm run build && npm run start
```

**特点**：
- 编译产物，无开发提示和 HMR
- Next.js 默认不显示错误浮层，页面最干净
- 后端需单独启动后再运行此命令

### 答辩推荐

| 场景 | 推荐模式 | 原因 |
|------|---------|------|
| **答辩现场** | `demo` 或 `production` | 画面干净，无 Issues 干扰 |
| **录屏** | `production` | 最稳定，无任何开发痕迹 |
| **临时边改边讲** | `demo` | 保留 HMR 能力，切换后立即生效 |

最推荐：**切换到 `demo` 后直接 `npm run dev`**，兼顾快速启动和页面整洁。如仍担心浮层出现，可改用 `npm run build && npm run start`（production）。

### 常见问题

**Q：为什么 dev 模式左下角显示 Issues？**
A：Next.js 开发模式默认显示构建/运行时 Issues 提示，这是正常的开发体验。如需隐藏，切换到 demo 或 production 模式。

**Q：demo 模式还能正常调试吗？**
A：可以，浏览器控制台（F12 → Console）仍然可用，HMR 也正常工作，只是隐藏了页面上的浮层 UI。

**Q：后端需要一起运行吗？**
A：需要。前后端都启动后才能完整使用：
```bash
# 终端 1：后端
python -m app.main --mode web --host 127.0.0.1 --port 8000

# 终端 2：前端（dev / demo / production）
cd frontend
npm run dev  # 或切换到 demo/production
```

## 项目结构

```
Tourism_Agent/
├── app/
│   ├── agents/              # 业务 Agent
│   │   ├── orchestrator.py  # 核心编排器
│   │   ├── planner.py
│   │   ├── attraction.py
│   │   ├── itinerary.py
│   │   ├── budget.py
│   │   └── weather.py
│   ├── api/                 # API 层
│   │   ├── main.py
│   │   └── gateway.py
│   ├── core/                # 核心架构
│   │   ├── agent/           # Agent 框架
│   │   │   ├── base.py
│   │   │   ├── protocol.py
│   │   │   ├── message_bus.py
│   │   │   ├── registry.py
│   │   │   ├── memory_agent.py
│   │   │   ├── reflection_agent.py
│   │   │   ├── quality_agent.py
│   │   │   └── personalization_agent.py
│   │   ├── llm/             # LLM 封装
│   │   │   ├── client.py
│   │   │   ├── manager.py
│   │   │   ├── router.py
│   │   │   ├── cache.py
│   │   │   └── fallback.py
│   │   ├── di.py            # 依赖注入
│   │   ├── middleware.py     # 中间件
│   │   ├── tool_strategy.py  # 工具策略
│   │   ├── tool_executor.py  # 工具执行器
│   │   ├── orchestration.py   # DAG 编排
│   │   ├── rag.py           # RAG
│   │   ├── config.py
│   │   └── context.py
│   ├── schemas/             # Pydantic Schema
│   ├── services/            # 服务层
│   │   └── preference_service.py
│   ├── storage/             # 存储层
│   │   ├── session_store.py
│   │   └── vector_store.py
│   └── tools/               # 工具层
│       ├── base.py
│       ├── poi_search.py
│       ├── weather.py
│       ├── route_plan.py
│       └── budget_calc.py
├── frontend/                # 前端
│   ├── components/
│   ├── lib/
│   └── app/
├── tests/                  # 测试
├── .env
├── requirements.txt
└── README.md
```

## Agent 能力体系

| Agent | 名称 | 核心能力 | 职责描述 |
|-------|------|----------|----------|
| **Orchestrator** | 编排器 | 任务调度 | 协调多Agent协作，任务分发与结果聚合 |
| **Planner** | 主规划师 | 规划推理 | 理解用户需求，协调子Agent，生成最终方案 |
| **Attraction** | 景点推荐 | 搜索推理 | 搜索推荐景点，匹配用户偏好，提供详细信息 |
| **Itinerary** | 行程规划 | 规划计算 | 制定每日行程，优化路线，分配时间 |
| **Budget** | 预算分析 | 计算推理 | 估算预算，分解费用，提供省钱技巧 |
| **Weather** | 天气预报 | 搜索推理 | 查询天气，提供穿搭和物品建议 |
| **Review** | 结果审查 | 审查优化 | 检查完整性、一致性、可行性，提供优化建议 |
| **Memory** | 记忆管理 | 存储检索 | 管理情景记忆、语义记忆、程序记忆 |
| **Reflection** | 自我反思 | 推理评估 | 评估结果质量，发现潜在问题 |
| **Quality** | 质量评估 | 审查评估 | 多维度质量审查，保证输出质量 |
| **Personalization** | 个性化 | 学习推理 | 用户画像学习，偏好推断，个性化推荐 |

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /chat` | POST | 发送聊天消息 |
| `POST /chat/stream` | POST | 流式聊天 |
| `GET /health` | GET | 健康检查 |
| `POST /session/reset` | POST | 重置会话 |
| `POST /feedback` | POST | 提交反馈 |

## Unified Planner Baseline

默认执行链路仍为多 Agent 主流程，由 `orchestrator`、`planner`、`attraction`、`itinerary`、`budget`、`weather` 等模块协同完成。

`app/agents/unified_planner.py` 保留为单 Agent / 单轮规划 baseline，用于实验对比、论文基线比较、效果对照和独立测试入口，不作为默认主链路。
默认用户对话入口 `/chat` 与 `/chat/stream` 仍走多 Agent 主流程；`/api/v1/plan/unified` 仅作为可选 baseline 接口保留。

## License

MIT
