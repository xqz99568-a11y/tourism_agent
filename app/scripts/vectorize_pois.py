"""
景点数据向量化脚本
将 POI 数据转换为嵌入向量并存储到向量数据库
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import hashlib

import click

from app.core.config import settings
from app.core.logger import get_logger
from app.storage.database import AsyncSessionLocal
from app.storage.repositories import get_poi_repository
from app.storage.vector_service import (
    VectorSearchService,
    POIEmbedding,
    EmbeddingGenerator,
    get_vector_service,
    init_vector_service,
)

logger = get_logger(__name__)


class POIVectorizer:
    """景点向量化器"""

    def __init__(
        self,
        embedding_func: Optional[Callable[[str], List[float]]] = None,
        batch_size: int = 32,
    ):
        self.embedding_func = embedding_func or self._default_embedding_func
        self.batch_size = batch_size
        self.vector_service: Optional[VectorSearchService] = None
        self.embedding_generator = EmbeddingGenerator()
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
        }

    def _default_embedding_func(self, text: str) -> List[float]:
        """
        默认嵌入函数 (Placeholder)
        实际使用中应该接入真实的嵌入 API

        返回: 1536 维零向量 (与配置中的 dimension 匹配)
        """
        # 使用文本哈希生成伪随机但确定的向量
        # 这只是一个占位符，实际部署时请使用真实的嵌入服务
        import numpy as np

        text_hash = hashlib.md5(text.encode()).digest()
        # 生成伪随机数
        np.random.seed(int.from_bytes(text_hash[:4], 'big') % (2**32))
        vector = np.random.randn(settings.vector_db.dimension).astype(np.float32)

        # L2 归一化
        vector = vector / (np.linalg.norm(vector) + 1e-10)

        return vector.tolist()

    async def initialize(self) -> None:
        """初始化"""
        self.vector_service = await init_vector_service()
        logger.info("Vector service initialized")

    async def vectorize_poi(
        self,
        poi_id: str,
        name: str,
        city: str,
        category: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        **kwargs
    ) -> Optional[POIEmbedding]:
        """向量化单个 POI"""
        try:
            # 生成文本表示
            poi = POIEmbedding(
                poi_id=poi_id,
                name=name,
                city=city,
                category=category,
                description=description,
                tags=tags or [],
                **kwargs
            )

            text = self.embedding_generator.generate_poi_text(poi)

            # 生成嵌入向量
            embedding = await self.embedding_generator.get_embedding(
                text,
                self.embedding_func
            )
            poi.embedding = embedding

            return poi

        except Exception as e:
            logger.error(f"Failed to vectorize POI {poi_id}: {e}")
            return None

    async def vectorize_from_database(self) -> Dict[str, int]:
        """从数据库向量化所有 POI"""
        logger.info("Starting vectorization from database...")

        async with AsyncSessionLocal() as session:
            poi_repo = get_poi_repository(session)

            # 获取所有活跃 POI
            total_count = await poi_repo.count()
            logger.info(f"Total POIs to vectorize: {total_count}")

            batch = []
            success = 0
            failed = 0
            skipped = 0

            for offset in range(0, total_count, self.batch_size):
                # 分批获取 POI
                pois = await poi_repo.search(skip=offset, limit=self.batch_size)

                for poi in pois:
                    self.stats["total"] += 1

                    # 检查是否已有嵌入
                    if poi.embedding and len(poi.embedding) > 0:
                        logger.debug(f"POI {poi.poi_id} already has embedding, skipping")
                        skipped += 1
                        continue

                    # 向量化
                    embedding = await self.vectorize_poi(
                        poi_id=poi.poi_id,
                        name=poi.name,
                        city=poi.city,
                        category=poi.category,
                        description=poi.description,
                        tags=poi.tags,
                        latitude=poi.latitude,
                        longitude=poi.longitude,
                        rating=poi.rating,
                        ticket_price=poi.ticket_price,
                        opening_hours=poi.opening_hours,
                        recommended_duration=poi.recommended_duration,
                        suitable_for=poi.suitable_for,
                        indoor_outdoor=poi.indoor_outdoor,
                        intensity=poi.intensity,
                        accessibility_score=poi.accessibility_score,
                        popularity_score=poi.popularity_score,
                    )

                    if embedding and self.vector_service:
                        # 存储到向量数据库
                        await self.vector_service.upsert_poi_embedding(embedding)
                        success += 1
                    else:
                        failed += 1

                # 每批后提交
                await session.commit()

                logger.info(f"Progress: {offset + len(pois)}/{total_count}")

        self.stats["success"] = success
        self.stats["failed"] = failed
        self.stats["skipped"] = skipped

        logger.info(f"Vectorization completed: {success} success, {failed} failed, {skipped} skipped")
        return self.stats

    async def vectorize_from_json(self, data_dir: Path) -> Dict[str, int]:
        """从 JSON 文件向量化 POI"""
        logger.info("Starting vectorization from JSON files...")

        pois_dir = data_dir / "pois"
        if not pois_dir.exists():
            logger.error(f"POIs directory not found: {pois_dir}")
            return {"success": 0, "failed": 0, "skipped": 0}

        success = 0
        failed = 0
        skipped = 0

        for poi_file in pois_dir.glob("*.json"):
            try:
                with open(poi_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                city = data.get("city", "Unknown")
                pois = data.get("pois", [])

                for poi_data in pois:
                    self.stats["total"] += 1
                    poi_id = poi_data.get("id")

                    if not poi_id:
                        skipped += 1
                        continue

                    # 向量化
                    embedding = await self.vectorize_poi(
                        poi_id=poi_id,
                        name=poi_data.get("name", ""),
                        city=city,
                        category=self._normalize_category(poi_data.get("category", "")),
                        description=poi_data.get("description"),
                        tags=poi_data.get("tags", []),
                        latitude=poi_data.get("latitude", 0) or 0,
                        longitude=poi_data.get("longitude", 0) or 0,
                        rating=poi_data.get("rating", 0) or 0,
                        ticket_price=poi_data.get("ticket_price"),
                        opening_hours=poi_data.get("opening_hours"),
                        recommended_duration=int(poi_data.get("recommended_duration", 120) or 120),
                        suitable_for=poi_data.get("suitable_for", []),
                        indoor_outdoor=poi_data.get("indoor_outdoor", "mixed"),
                        intensity=poi_data.get("intensity", "medium"),
                    )

                    if embedding and self.vector_service:
                        await self.vector_service.upsert_poi_embedding(embedding)
                        success += 1
                    else:
                        failed += 1

                logger.info(f"Vectorized {len(pois)} POIs from {poi_file.name}")

            except Exception as e:
                logger.error(f"Failed to process {poi_file.name}: {e}")
                failed += 1

        self.stats["success"] = success
        self.stats["failed"] = failed
        self.stats["skipped"] = skipped

        logger.info(f"Vectorization completed: {success} success, {failed} failed, {skipped} skipped")
        return self.stats

    async def reindex_all(self, data_dir: Path) -> Dict[str, int]:
        """重新索引所有 POI"""
        logger.info("Starting reindexing...")

        # 清空现有集合
        if self.vector_service:
            await self.vector_service.initialize()

        # 重新向量化
        return await self.vectorize_from_json(data_dir)

    def _normalize_category(self, category: str) -> str:
        """标准化类别"""
        category_map = {
            "历史文化": "historical",
            "自然风光": "nature",
            "博物馆": "museum",
            "美食": "food",
            "夜景": "nightlife",
            "亲子娱乐": "entertainment",
            "景区": "scenic",
            "购物": "shopping",
            "娱乐": "entertainment",
        }
        return category_map.get(category, category.lower())

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            "timestamp": datetime.utcnow().isoformat(),
        }


async def run_vectorization(
    source: str = "database",
    reindex: bool = False,
    embedding_func: Optional[Callable[[str], List[float]]] = None,
) -> Dict[str, Any]:
    """运行向量化"""
    vectorizer = POIVectorizer(embedding_func=embedding_func)
    await vectorizer.initialize()

    data_dir = Path(__file__).parent.parent.parent / "data"

    if reindex:
        results = await vectorizer.reindex_all(data_dir)
    elif source == "database":
        results = await vectorizer.vectorize_from_database()
    else:
        results = await vectorizer.vectorize_from_json(data_dir)

    return {
        "results": results,
        "stats": vectorizer.get_stats(),
    }


@click.group()
def cli():
    """景点向量化命令行工具"""
    pass


@cli.command()
@click.option("--source", type=click.Choice(["database", "json"]), default="database",
              help="Data source")
@click.option("--reindex", is_flag=True, help="Reindex all POIs (delete existing)")
def vectorize(source, reindex):
    """向量化景点数据"""
    results = asyncio.run(run_vectorization(source=source, reindex=reindex))
    click.echo(f"Vectorization completed: {results}")


@cli.command()
def stats():
    """查看向量化统计"""
    vectorizer = POIVectorizer()
    asyncio.run(vectorizer.initialize())

    # 获取集合状态
    import asyncio
    async def get_stats():
        if vectorizer.vector_service:
            return await vectorizer.vector_service.get_collection_stats()
        return {}

    stats = asyncio.run(get_stats())
    click.echo(f"Vector store stats: {stats}")


if __name__ == "__main__":
    cli()
