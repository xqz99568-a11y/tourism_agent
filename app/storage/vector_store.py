"""
Vector Store (向量数据库) 封装
支持 Qdrant, Milvus, ChromaDB
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    score: float
    payload: Dict[str, Any]


class BaseVectorStore(ABC):
    """向量存储基类"""

    @abstractmethod
    async def init_collection(self, dimension: int) -> None:
        """初始化集合"""
        pass

    @abstractmethod
    async def upsert(self, id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        """插入或更新向量"""
        pass

    @abstractmethod
    async def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """向量搜索"""
        pass

    @abstractmethod
    async def delete(self, id: str) -> None:
        """删除向量"""
        pass


class QdrantStore(BaseVectorStore):
    """
    Qdrant 向量数据库客户端
    """

    def __init__(self):
        self.host = settings.vector_db.host
        self.port = settings.vector_db.port
        self.collection_name = settings.vector_db.collection_name
        self.api_key = settings.vector_db.api_key
        self.base_url = f"http://{self.host}:{self.port}"
        self.dimension = settings.vector_db.dimension

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    async def init_collection(self, dimension: Optional[int] = None) -> None:
        """初始化集合"""
        dim = dimension or self.dimension

        async with httpx.AsyncClient() as client:
            # 检查集合是否存在
            try:
                response = await client.get(
                    f"{self.base_url}/collections/{self.collection_name}",
                    headers=self._get_headers(),
                )

                if response.status_code == 200:
                    logger.info(f"Collection {self.collection_name} already exists")
                    return

            except Exception:
                pass

            # 创建集合
            payload = {
                "vectors": {
                    "size": dim,
                    "distance": "Cosine",
                },
                "optimizers_config": {
                    "default_segment_number": 2,
                },
            }

            response = await client.put(
                f"{self.base_url}/collections/{self.collection_name}",
                headers=self._get_headers(),
                json=payload,
            )

            if response.status_code in [200, 201]:
                logger.info(f"Created collection {self.collection_name}")
            else:
                logger.error(f"Failed to create collection: {response.text}")
                raise Exception(f"Failed to create collection: {response.text}")

    async def upsert(
        self,
        id: str,
        vector: List[float],
        payload: Dict[str, Any],
    ) -> None:
        """插入或更新向量"""
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.base_url}/collections/{self.collection_name}/points",
                headers=self._get_headers(),
                json={
                    "points": [
                        {
                            "id": id,
                            "vector": vector,
                            "payload": payload,
                        }
                    ]
                },
            )

            if response.status_code not in [200, 201]:
                logger.error(f"Failed to upsert point: {response.text}")
                raise Exception(f"Failed to upsert point: {response.text}")

    async def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """向量搜索"""
        search_payload: Dict[str, Any] = {
            "vector": query_vector,
            "limit": top_k,
            "with_payload": True,
            "score_threshold": 0.5,
        }

        if filter_conditions:
            search_payload["filter"] = filter_conditions

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/collections/{self.collection_name}/points/search",
                headers=self._get_headers(),
                json=search_payload,
            )

            if response.status_code != 200:
                logger.error(f"Search failed: {response.text}")
                return []

            data = response.json()
            results = []

            for item in data.get("result", []):
                results.append(
                    SearchResult(
                        id=str(item["id"]),
                        score=item["score"],
                        payload=item.get("payload", {}),
                    )
                )

            return results

    async def delete(self, id: str) -> None:
        """删除向量"""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.base_url}/collections/{self.collection_name}/points/{id}",
                headers=self._get_headers(),
            )

            if response.status_code not in [200, 204]:
                logger.error(f"Failed to delete point: {response.text}")


class InMemoryVectorStore(BaseVectorStore):
    """
    内存向量存储 (用于开发/测试)
    基于简单的余弦相似度计算
    """

    def __init__(self, dimension: int = 1536):
        self.dimension = dimension
        self.vectors: Dict[str, tuple[List[float], Dict[str, Any]]] = {}

    async def init_collection(self, dimension: Optional[int] = None) -> None:
        """初始化集合"""
        if dimension:
            self.dimension = dimension
        self.vectors.clear()
        logger.info("In-memory vector store initialized")

    async def upsert(
        self,
        id: str,
        vector: List[float],
        payload: Dict[str, Any],
    ) -> None:
        """插入或更新向量"""
        self.vectors[id] = (vector, payload)

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """计算余弦相似度"""
        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0

        return dot_product / (norm1 * norm2)

    async def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """向量搜索"""
        results = []

        for id, (vector, payload) in self.vectors.items():
            # 应用过滤条件
            if filter_conditions:
                matches = True
                for key, value in filter_conditions.items():
                    if payload.get(key) != value:
                        matches = False
                        break
                if not matches:
                    continue

            score = self._cosine_similarity(query_vector, vector)

            if score >= 0.5:  # 相似度阈值
                results.append(
                    SearchResult(
                        id=id,
                        score=score,
                        payload=payload,
                    )
                )

        # 排序并返回 top_k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    async def delete(self, id: str) -> None:
        """删除向量"""
        if id in self.vectors:
            del self.vectors[id]


# 根据配置选择向量存储
def get_vector_store() -> BaseVectorStore:
    """获取向量存储实例"""
    if settings.vector_db.provider == "qdrant":
        return QdrantStore()
    else:
        # 默认使用内存存储
        return InMemoryVectorStore(dimension=settings.vector_db.dimension)


# 全局实例
vector_store: Optional[BaseVectorStore] = None


def init_vector_store() -> BaseVectorStore:
    """初始化向量存储"""
    global vector_store
    vector_store = get_vector_store()
    return vector_store


def get_store() -> BaseVectorStore:
    """获取向量存储"""
    global vector_store
    if vector_store is None:
        vector_store = get_vector_store()
    return vector_store
