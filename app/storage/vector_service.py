"""
Vector Store Service - 向量数据库服务
支持 Qdrant, Milvus, ChromaDB 和语义搜索
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from uuid import uuid4
import hashlib

import httpx

from app.core.config import settings
from app.core.logger import get_logger
from app.storage.vector_store import (
    BaseVectorStore,
    SearchResult as BaseSearchResult,
    QdrantStore,
    InMemoryVectorStore,
    get_vector_store,
)

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    score: float
    payload: Dict[str, Any]
    poi_id: Optional[str] = None
    name: Optional[str] = None
    city: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class EmbeddingRequest:
    """嵌入请求"""
    text: str
    model: str = "text-embedding-ada-002"
    user: Optional[str] = None


@dataclass
class POIEmbedding:
    """POI 嵌入数据"""
    poi_id: str
    name: str
    name_pinyin: Optional[str] = None
    description: Optional[str] = None
    category: str = ""
    tags: List[str] = field(default_factory=list)
    city: str = ""
    province: Optional[str] = None
    address: Optional[str] = None
    latitude: float = 0
    longitude: float = 0
    rating: float = 0
    ticket_price: Optional[float] = None
    opening_hours: Optional[str] = None
    recommended_duration: int = 120
    suitable_for: List[str] = field(default_factory=list)
    indoor_outdoor: str = "mixed"
    intensity: str = "medium"
    accessibility_score: float = 1.0
    popularity_score: float = 0
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class VectorSearchService:
    """
    向量搜索服务
    提供语义搜索能力
    """

    def __init__(self, vector_store: Optional[BaseVectorStore] = None):
        self._store = vector_store or get_vector_store()
        self._dimension = settings.vector_db.dimension

    async def initialize(self) -> None:
        """初始化向量存储"""
        await self._store.init_collection(self._dimension)
        logger.info(f"Vector store initialized with dimension {self._dimension}")

    async def upsert_poi_embedding(self, poi: POIEmbedding) -> bool:
        """
        插入或更新 POI 嵌入

        Args:
            poi: POI 嵌入数据

        Returns:
            是否成功
        """
        try:
            if poi.embedding is None:
                logger.warning(f"POI {poi.poi_id} has no embedding, skipping")
                return False

            payload = {
                "poi_id": poi.poi_id,
                "name": poi.name,
                "name_pinyin": poi.name_pinyin,
                "description": poi.description,
                "category": poi.category,
                "tags": poi.tags,
                "city": poi.city,
                "province": poi.province,
                "address": poi.address,
                "latitude": poi.latitude,
                "longitude": poi.longitude,
                "rating": poi.rating,
                "ticket_price": poi.ticket_price,
                "opening_hours": poi.opening_hours,
                "recommended_duration": poi.recommended_duration,
                "suitable_for": poi.suitable_for,
                "indoor_outdoor": poi.indoor_outdoor,
                "intensity": poi.intensity,
                "accessibility_score": poi.accessibility_score,
                "popularity_score": poi.popularity_score,
                "metadata": poi.metadata,
                "created_at": datetime.utcnow().isoformat(),
            }

            await self._store.upsert(poi.poi_id, poi.embedding, payload)
            logger.debug(f"Upserted POI embedding: {poi.poi_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to upsert POI embedding {poi.poi_id}: {e}")
            return False

    async def batch_upsert(self, pois: List[POIEmbedding]) -> Dict[str, int]:
        """
        批量插入 POI 嵌入

        Returns:
            {"success": count, "failed": count}
        """
        success = 0
        failed = 0

        for poi in pois:
            if await self.upsert_poi_embedding(poi):
                success += 1
            else:
                failed += 1

        return {"success": success, "failed": failed}

    async def semantic_search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        city: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_rating: Optional[float] = None,
        intensity: Optional[str] = None,
        indoor_outdoor: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        语义搜索

        Args:
            query_vector: 查询向量
            top_k: 返回数量
            city: 城市过滤
            category: 类别过滤
            tags: 标签过滤
            min_rating: 最低评分
            intensity: 强度过滤
            indoor_outdoor: 室内/室外过滤

        Returns:
            搜索结果列表
        """
        # 构建过滤条件
        filter_conditions = {}

        if city:
            filter_conditions["city"] = city
        if category:
            filter_conditions["category"] = category
        if min_rating is not None:
            filter_conditions["rating"] = {"$gte": min_rating}
        if intensity:
            filter_conditions["intensity"] = intensity
        if indoor_outdoor:
            filter_conditions["indoor_outdoor"] = indoor_outdoor

        # 执行搜索
        results = await self._store.search(
            query_vector,
            top_k=top_k,
            filter_conditions=filter_conditions if filter_conditions else None,
        )

        # 转换为 SearchResult
        search_results = []
        for result in results:
            # 标签过滤
            if tags:
                result_tags = result.payload.get("tags", [])
                if not any(tag in result_tags for tag in tags):
                    continue

            search_results.append(SearchResult(
                id=result.id,
                score=result.score,
                payload=result.payload,
                poi_id=result.payload.get("poi_id"),
                name=result.payload.get("name"),
                city=result.payload.get("city"),
                category=result.payload.get("category"),
                tags=result.payload.get("tags", []),
            ))

        return search_results

    async def search_by_text(
        self,
        query_text: str,
        embedding_func: Callable[[str], List[float]],
        top_k: int = 10,
        **search_kwargs
    ) -> List[SearchResult]:
        """
        通过文本搜索 (需要提供嵌入函数)

        Args:
            query_text: 查询文本
            embedding_func: 嵌入函数
            top_k: 返回数量
            **search_kwargs: 其他搜索参数

        Returns:
            搜索结果列表
        """
        # 生成查询向量
        query_vector = embedding_func(query_text)

        # 执行语义搜索
        return await self.semantic_search(query_vector, top_k=top_k, **search_kwargs)

    async def delete_poi(self, poi_id: str) -> bool:
        """删除 POI 嵌入"""
        try:
            await self._store.delete(poi_id)
            logger.debug(f"Deleted POI embedding: {poi_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete POI embedding {poi_id}: {e}")
            return False

    async def get_poi_embedding(self, poi_id: str) -> Optional[SearchResult]:
        """获取 POI 嵌入详情"""
        # 使用 search 功能获取单个结果
        # 注意: 这需要向量存储支持 ID 查询
        # 这里简化处理，返回 None
        # 实际实现中可以使用 store 的特定方法
        return None

    async def get_collection_stats(self) -> Dict[str, Any]:
        """获取集合统计"""
        # 这个功能需要向量存储支持
        # 目前返回基本信息
        return {
            "dimension": self._dimension,
            "collection_name": settings.vector_db.collection_name,
            "provider": settings.vector_db.provider,
        }

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            stats = await self.get_collection_stats()
            return {
                "status": "healthy",
                "provider": settings.vector_db.provider,
                "stats": stats,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }


class EmbeddingGenerator:
    """
    嵌入生成器
    支持多种嵌入模型
    """

    def __init__(self):
        self._embedding_cache: Dict[str, List[float]] = {}

    def generate_poi_text(self, poi: POIEmbedding) -> str:
        """
        生成 POI 的文本表示用于嵌入

        Format:
        "名称: xxx | 城市: xxx | 类别: xxx | 标签: xxx | 描述: xxx | 适合: xxx"
        """
        parts = [
            f"景点名称: {poi.name}",
            f"城市: {poi.city}",
            f"类别: {poi.category}",
        ]

        if poi.tags:
            parts.append(f"特点: {', '.join(poi.tags)}")

        if poi.description:
            parts.append(f"描述: {poi.description}")

        if poi.suitable_for:
            parts.append(f"适合人群: {', '.join(poi.suitable_for)}")

        if poi.indoor_outdoor:
            indoor_map = {"indoor": "室内", "outdoor": "室外", "mixed": "室内外兼有"}
            parts.append(f"环境: {indoor_map.get(poi.indoor_outdoor, poi.indoor_outdoor)}")

        if poi.intensity:
            intensity_map = {"low": "轻松", "medium": "中等", "high": "强度大"}
            parts.append(f"体力强度: {intensity_map.get(poi.intensity, poi.intensity)}")

        return " | ".join(parts)

    def generate_search_text(
        self,
        query: str,
        city: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        budget: Optional[str] = None,
        group_type: Optional[str] = None,
    ) -> str:
        """生成搜索查询文本"""
        parts = [query]

        if city:
            parts.append(f"位于{city}")

        if category:
            parts.append(f"类别: {category}")

        if tags:
            parts.append(f"特点: {', '.join(tags)}")

        if budget:
            parts.append(f"预算: {budget}")

        if group_type:
            group_map = {
                "solo": "独自旅行",
                "couple": "情侣",
                "family": "家庭",
                "friends": "朋友",
                "senior": "老年人",
            }
            parts.append(f"人群: {group_map.get(group_type, group_type)}")

        return " ".join(parts)

    def cache_key(self, text: str) -> str:
        """生成缓存键"""
        return hashlib.md5(text.encode()).hexdigest()

    async def get_embedding(
        self,
        text: str,
        embedding_api: Optional[Callable[[str], List[float]]] = None
    ) -> List[float]:
        """
        获取文本嵌入

        Args:
            text: 文本
            embedding_api: 嵌入 API 函数

        Returns:
            嵌入向量
        """
        # 检查缓存
        cache_key = self.cache_key(text)
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        # 使用 API 生成
        if embedding_api:
            embedding = embedding_api(text)
        else:
            # 返回零向量 (placeholder)
            # 实际使用中应该接入真实的嵌入 API
            embedding = [0.0] * self._dimension

        # 缓存
        self._embedding_cache[cache_key] = embedding
        return embedding

    async def batch_get_embeddings(
        self,
        texts: List[str],
        embedding_api: Optional[Callable[[List[str]], List[List[float]]]] = None
    ) -> List[List[float]]:
        """批量获取嵌入"""
        # 检查缓存
        embeddings = []
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            cache_key = self.cache_key(text)
            if cache_key in self._embedding_cache:
                embeddings.append((i, self._embedding_cache[cache_key]))
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)

        # 批量获取未缓存的
        if uncached_texts and embedding_api:
            new_embeddings = embedding_api(uncached_texts)
            for idx, emb in zip(uncached_indices, new_embeddings):
                cache_key = self.cache_key(texts[idx])
                self._embedding_cache[cache_key] = emb
                embeddings.append((idx, emb))

        # 按原始顺序返回
        embeddings.sort(key=lambda x: x[0])
        return [emb for _, emb in embeddings]

    def clear_cache(self) -> None:
        """清空缓存"""
        self._embedding_cache.clear()


# ==================== 全局实例 ====================

_vector_service: Optional[VectorSearchService] = None
_embedding_generator: Optional[EmbeddingGenerator] = None


def get_vector_service() -> VectorSearchService:
    """获取向量搜索服务"""
    global _vector_service
    if _vector_service is None:
        store = get_vector_store()
        _vector_service = VectorSearchService(vector_store=store)
    return _vector_service


def get_embedding_generator() -> EmbeddingGenerator:
    """获取嵌入生成器"""
    global _embedding_generator
    if _embedding_generator is None:
        _embedding_generator = EmbeddingGenerator()
    return _embedding_generator


async def init_vector_service() -> VectorSearchService:
    """初始化向量搜索服务"""
    service = get_vector_service()
    await service.initialize()
    return service
