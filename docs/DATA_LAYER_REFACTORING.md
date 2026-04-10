# 数据层重构文档 (Data Layer Refactoring)

## 1. 概述

本文档描述了智慧文旅系统的数据层重构，从简单的本地 JSON 存储迁移到完整的多层数据架构。

### 重构目标

| 层级 | 组件 | 用途 |
|------|------|------|
| 应用层 | Repository Pattern / Service Layer | 业务逻辑封装 |
| 缓存层 | Redis | 会话、查询、热点数据 |
| 数据库层 | PostgreSQL | 结构化数据 |
| 向量层 | Qdrant/Milvus | 语义搜索 |

## 2. 数据库架构

### 2.1 PostgreSQL 表结构

#### 用户表 (users)
- 基本信息: user_id, username, email, phone
- 偏好设置: travel_styles, budget_level, tourist_type
- 学习到的偏好: liked_pois, disliked_pois, preferred_destinations

#### 会话表 (sessions)
- 会话状态管理
- 对话统计
- 情感追踪

#### 消息表 (messages)
- 完整对话历史
- Agent 执行元数据

#### 景点表 (pois)
- 完整的 POI 信息
- 适老化评分
- 嵌入向量

#### 行程表 (itineraries)
- 行程计划
- 预算追踪

### 2.2 Redis 数据结构

```
tourism:session:{session_id}     # 会话上下文
tourism:cache:poi:{cache_key}   # POI 缓存
tourism:cache:weather:{key}      # 天气缓存
tourism:lock:{resource}          # 分布式锁
tourism:ratelimit:{key}          # 限流计数器
tourism:hot:items                # 热点数据 ZSET
```

### 2.3 向量数据库

- Collection: `poi_embeddings`
- Dimension: 1536
- Distance: Cosine
- 支持按城市、类别、评分等过滤

## 3. 目录结构

```
app/
├── storage/                     # 数据存储层
│   ├── models.py               # SQLAlchemy 模型
│   ├── database.py             # 数据库连接
│   ├── repositories.py         # Repository 模式
│   ├── cache_manager.py        # Redis 缓存管理
│   ├── cache_strategy.py       # 缓存策略
│   ├── vector_store.py        # 向量存储
│   ├── vector_service.py       # 向量搜索服务
│   └── __init__.py
├── services/                    # 业务服务层
│   ├── data_services.py        # 数据服务
│   └── __init__.py
├── scripts/                     # 工具脚本
│   ├── migrate_data.py         # 数据迁移
│   ├── vectorize_pois.py       # POI 向量化
│   └── backup_restore.py       # 备份恢复
└── core/
    └── config.py               # 配置管理
```

## 4. Repository 模式

### 4.1 核心接口

```python
class BaseRepository:
    async def get_by_id(self, id: int) -> Optional[T]
    async def create(self, data: Dict) -> T
    async def update(self, id: int, data: Dict) -> Optional[T]
    async def delete(self, id: int) -> bool
    async def list(self, skip, limit) -> List[T]
```

### 4.2 具体实现

- `UserRepository`: 用户 CRUD
- `SessionRepository`: 会话管理
- `MessageRepository`: 消息存储
- `POIRepository`: 景点查询
- `ItineraryRepository`: 行程管理
- `FeedbackRepository`: 反馈收集

## 5. Service 层

### 5.1 服务列表

| 服务 | 职责 |
|------|------|
| SessionService | 会话生命周期管理 |
| UserService | 用户画像和偏好学习 |
| POIService | 景点搜索和推荐 |
| ItineraryService | 行程规划和版本管理 |
| FeedbackService | 用户反馈处理 |
| AnalyticsService | 数据分析和统计 |

## 6. 缓存策略

### 6.1 缓存类型

| 策略 | 适用场景 |
|------|----------|
| Cache-Aside | 读多写少的数据 |
| Write-Through | 需要强一致性的数据 |
| Write-Behind | 高写入量的场景 |
| Memory + Redis | 热数据加速 |

### 6.2 TTL 配置

| 数据类型 | TTL | 说明 |
|----------|-----|------|
| 会话 | 7天 | 长时间会话 |
| POI 详情 | 1小时 | 相对稳定的数据 |
| 搜索结果 | 5分钟 | 快速过期 |
| 天气 | 30分钟 | 实时性要求 |
| LLM 响应 | 1小时 | 减少 API 调用 |

## 7. 向量搜索

### 7.1 POI 嵌入生成

```python
poi_text = """
景点名称: 故宫博物院 |
城市: 北京 |
类别: historical |
特点: 博物馆, 世界遗产, 经典景点 |
描述: 北京核心历史地标... |
适合人群: 家庭, 学生, 历史爱好者
"""
```

### 7.2 搜索流程

1. 用户输入查询
2. 生成查询向量
3. 向量数据库相似度搜索
4. 应用过滤条件
5. 返回排序结果

## 8. 数据迁移

### 8.1 迁移命令

```bash
# 初始化数据库
python -m app.scripts.migrate_data init

# 迁移所有数据
python -m app.scripts.migrate_data migrate

# 只迁移 POI
python -m app.scripts.migrate_data migrate --no-restaurants --no-cache
```

### 8.2 向量化

```bash
# 从数据库向量化
python -m app.scripts.vectorize_pois vectorize --source database

# 从 JSON 文件向量化
python -m app.scripts.vectorize_pois vectorize --source json

# 重新索引
python -m app.scripts.vectorize_pois vectorize --reindex
```

## 9. 备份与恢复

### 9.1 命令

```bash
# 创建备份
python -m app.scripts.backup_restore backup

# 列出备份
python -m app.scripts.backup_restore list

# 恢复备份
python -m app.scripts.backup_restore restore backup_name

# 清理旧备份
python -m app.scripts.backup_restore cleanup --days 7
```

### 9.2 导出数据

```bash
# 导出 POI
python -m app.scripts.backup_restore export pois

# 导出用户
python -m app.scripts.backup_restore export users

# 导出行程
python -m app.scripts.backup_restore export itineraries
```

## 10. 使用示例

### 10.1 初始化

```python
from app.storage import init_db, init_redis, init_vector_service

# 初始化数据库
await init_db()

# 初始化 Redis
await init_redis()

# 初始化向量服务
await init_vector_service()
```

### 10.2 使用 Repository

```python
from app.storage import AsyncSessionLocal, get_poi_repository

async with AsyncSessionLocal() as session:
    poi_repo = get_poi_repository(session)

    # 搜索 POI
    pois = await poi_repo.search(
        city="北京",
        category="historical",
        min_rating=4.0
    )
```

### 10.3 使用 Service

```python
from app.services import create_poi_service
from app.storage import get_cache_manager, init_vector_service

cache = await get_cache_manager()
vector_service = await init_vector_service()
poi_service = await create_poi_service(session, vector_service, cache)

# 语义搜索
results = await poi_service.semantic_search_pois(
    query_text="适合家庭的文化景点",
    embedding_func=embedding_model.encode,
    city="北京"
)
```

### 10.4 使用缓存

```python
from app.storage import get_cache_manager

cache = await get_cache_manager()

# 设置缓存
await cache.set_cache("poi", "bj001", poi_data, ttl=3600)

# 获取缓存
data = await cache.get_cache("poi", "bj001")

# 失效缓存
await cache.delete_cache("poi", "bj001")
```

## 11. 配置说明

### 11.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| DATABASE_URL | postgresql+asyncpg://... | PostgreSQL 连接 |
| REDIS_HOST | localhost | Redis 主机 |
| REDIS_PORT | 6379 | Redis 端口 |
| VECTOR_DB_PROVIDER | qdrant | 向量数据库类型 |
| VECTOR_DB_DIMENSION | 1536 | 嵌入向量维度 |

### 11.2 .env 配置

```bash
# 复制示例配置
cp .env.example .env

# 编辑配置
# 填写您的实际数据库连接信息
```

## 12. 注意事项

1. **数据库迁移**: 首次运行需要执行 `migrate_data init`
2. **向量数据库**: 确保 Qdrant/Milvus 服务运行
3. **Redis**: 确保 Redis 服务运行
4. **嵌入模型**: 生产环境应使用真实的嵌入 API

## 13. 扩展指南

### 13.1 添加新的数据模型

1. 在 `models.py` 中定义模型
2. 在 `repositories.py` 中实现 Repository
3. 在 `data_services.py` 中实现 Service
4. 更新 `__init__.py` 导出

### 13.2 添加新的缓存策略

1. 继承 `CacheStrategy` 基类
2. 实现 `get`, `set`, `invalidate` 方法
3. 在 `cache_strategy.py` 中注册

## 14. 监控和维护

### 14.1 缓存统计

```python
from app.storage import get_cache_manager

cache = await get_cache_manager()
stats = await cache.get_stats()
print(stats)
```

### 14.2 健康检查

```python
from app.storage import get_vector_service

vector_service = get_vector_service()
health = await vector_service.health_check()
print(health)
```

## 15. 故障排除

| 问题 | 解决方案 |
|------|----------|
| 数据库连接失败 | 检查 DATABASE_URL 配置 |
| Redis 连接失败 | 检查 REDIS_HOST/PORT |
| 向量搜索无结果 | 确保已运行向量化脚本 |
| 缓存未生效 | 检查 TTL 设置和 key 前缀 |
