# 数据层重构文档

## 1. 概述

本文档说明智慧旅游系统的数据层设计。目标是从简单的本地 JSON 数据逐步演进到多层数据架构，支持会话管理、POI 查询、天气缓存、向量检索和实验数据分析。

## 2. 重构目标

| 层级 | 组件 | 用途 |
|------|------|------|
| 应用层 | Repository Pattern / Service Layer | 封装业务逻辑，降低调用方对存储细节的依赖 |
| 缓存层 | Redis | 缓存会话、查询结果、天气结果和热点数据 |
| 数据库层 | PostgreSQL | 存储结构化业务数据 |
| 向量层 | Qdrant / Milvus / Chroma | 支持 POI 语义检索 |
| 文件层 | `data/` | 保存研究原型所需的本地样例、兜底数据和缓存 |

## 3. 数据库设计

### 3.1 用户表 `users`

- 基本信息：`user_id`、`username`、`email`、`phone`
- 偏好设置：旅行风格、预算等级、游客类型
- 学习偏好：喜欢的 POI、不喜欢的 POI、偏好的目的地

### 3.2 会话表 `sessions`

- 会话 ID 和生命周期状态
- 当前旅行上下文
- 对话轮次统计
- 情绪与模式历史

### 3.3 消息表 `messages`

- 完整对话历史
- 用户消息和系统回复
- Agent 执行元数据

### 3.4 景点表 `pois`

- POI 基本信息
- 城市、区域、分类、评分和标签
- 门票、开放时间、推荐游玩时长
- 向量嵌入信息

### 3.5 行程表 `itineraries`

- 行程规划结果
- 每日安排
- 预算和版本信息

## 4. Redis 数据结构

```text
tourism:session:{session_id}      # 会话上下文
tourism:cache:poi:{cache_key}     # POI 查询缓存
tourism:cache:weather:{key}       # 天气缓存
tourism:lock:{resource}           # 分布式锁
tourism:ratelimit:{key}           # 限流计数器
tourism:hot:items                 # 热点数据 ZSET
```

## 5. 向量数据库

- Collection：`poi_embeddings`
- Dimension：`1536`
- Distance：`Cosine`
- 支持按城市、分类、评分等条件过滤
- 用于“适合亲子”“文化类景点”“雨天室内备选”等语义搜索场景

## 6. 目录结构

```text
app/
├─ storage/                    # 数据存储层
│  ├─ models.py                # SQLAlchemy 模型
│  ├─ database.py              # 数据库连接
│  ├─ repositories.py          # Repository 实现
│  ├─ cache_manager.py         # Redis 缓存管理
│  ├─ cache_strategy.py        # 缓存策略
│  ├─ vector_store.py          # 向量存储
│  ├─ vector_service.py        # 向量检索服务
│  └─ __init__.py
├─ services/                   # 业务服务层
│  ├─ data_services.py
│  └─ __init__.py
├─ scripts/                    # 数据工具脚本
│  ├─ migrate_data.py          # 数据迁移
│  ├─ vectorize_pois.py        # POI 向量化
│  └─ backup_restore.py        # 备份与恢复
└─ core/
   └─ config.py                # 配置管理
```

## 7. Repository 模式

### 7.1 基础接口

```python
class BaseRepository:
    async def get_by_id(self, id: int) -> Optional[T]
    async def create(self, data: Dict) -> T
    async def update(self, id: int, data: Dict) -> Optional[T]
    async def delete(self, id: int) -> bool
    async def list(self, skip: int, limit: int) -> List[T]
```

### 7.2 具体实现

- `UserRepository`：用户 CRUD
- `SessionRepository`：会话管理
- `MessageRepository`：消息存储
- `POIRepository`：景点查询
- `ItineraryRepository`：行程管理
- `FeedbackRepository`：反馈收集

## 8. Service 层

| 服务 | 职责 |
|------|------|
| `SessionService` | 会话生命周期管理 |
| `UserService` | 用户画像和偏好学习 |
| `POIService` | 景点搜索和推荐 |
| `ItineraryService` | 行程规划和版本管理 |
| `FeedbackService` | 用户反馈处理 |
| `AnalyticsService` | 数据分析和统计 |

## 9. 缓存策略

### 9.1 策略类型

| 策略 | 适用场景 |
|------|----------|
| Cache-Aside | 读多写少的数据 |
| Write-Through | 需要强一致性的数据 |
| Write-Behind | 高写入量场景 |
| Memory + Redis | 热点数据加速 |

### 9.2 TTL 建议

| 数据类型 | TTL | 说明 |
|----------|-----|------|
| 会话 | 7 天 | 长时间会话 |
| POI 详情 | 1 小时 | 相对稳定的数据 |
| 搜索结果 | 5 分钟 | 快速过期 |
| 天气 | 30 分钟 | 实时性要求较高 |
| LLM 响应 | 1 小时 | 降低重复调用成本 |

## 10. 向量检索流程

1. 接收用户查询。
2. 生成查询向量。
3. 在向量数据库中执行相似度搜索。
4. 按城市、分类、评分等条件过滤。
5. 返回排序后的候选结果。

示例 POI 文本：

```text
景点名称: 故宫博物院
城市: 北京
类别: historical
特点: 博物馆、世界遗产、经典景点
描述: 北京核心历史地标
适合人群: 家庭、学生、历史爱好者
```

## 11. 数据迁移

初始化数据库：

```bash
python -m app.scripts.migrate_data init
```

迁移全部数据：

```bash
python -m app.scripts.migrate_data migrate
```

只迁移 POI：

```bash
python -m app.scripts.migrate_data migrate --no-restaurants --no-cache
```

## 12. 向量化

从数据库向量化：

```bash
python -m app.scripts.vectorize_pois vectorize --source database
```

从 JSON 文件向量化：

```bash
python -m app.scripts.vectorize_pois vectorize --source json
```

重新索引：

```bash
python -m app.scripts.vectorize_pois vectorize --reindex
```

## 13. 备份与恢复

创建备份：

```bash
python -m app.scripts.backup_restore backup
```

列出备份：

```bash
python -m app.scripts.backup_restore list
```

恢复备份：

```bash
python -m app.scripts.backup_restore restore backup_name
```

清理旧备份：

```bash
python -m app.scripts.backup_restore cleanup --days 7
```

## 14. 使用示例

### 14.1 初始化

```python
from app.storage import init_db, init_redis, init_vector_service

await init_db()
await init_redis()
await init_vector_service()
```

### 14.2 使用 Repository

```python
from app.storage import AsyncSessionLocal, get_poi_repository

async with AsyncSessionLocal() as session:
    poi_repo = get_poi_repository(session)
    pois = await poi_repo.search(
        city="北京",
        category="historical",
        min_rating=4.0,
    )
```

### 14.3 使用 Service

```python
from app.services import create_poi_service
from app.storage import get_cache_manager, init_vector_service

cache = await get_cache_manager()
vector_service = await init_vector_service()
poi_service = await create_poi_service(session, vector_service, cache)

results = await poi_service.semantic_search_pois(
    query_text="适合家庭的文化景点",
    embedding_func=embedding_model.encode,
    city="北京",
)
```

## 15. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL 连接 |
| `REDIS_HOST` | `localhost` | Redis 主机 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `VECTOR_DB_PROVIDER` | `qdrant` | 向量数据库类型 |
| `VECTOR_DB_DIMENSION` | `1536` | 嵌入向量维度 |

## 16. 注意事项

1. 首次使用数据库能力前，需要执行 `migrate_data init`。
2. 使用向量检索前，确保 Qdrant、Milvus 或 Chroma 服务已启动。
3. 使用 Redis 缓存前，确保 Redis 服务已启动。
4. 生产环境应使用真实的嵌入模型或嵌入 API。
5. 不要把真实数据库连接串、API Key 或私有数据提交到仓库。

## 17. 故障排查

| 问题 | 解决方案 |
|------|----------|
| 数据库连接失败 | 检查 `DATABASE_URL` 配置 |
| Redis 连接失败 | 检查 `REDIS_HOST` 和 `REDIS_PORT` |
| 向量检索没有结果 | 确认已运行向量化脚本 |
| 缓存没有生效 | 检查 TTL、key 前缀和 Redis 服务状态 |
