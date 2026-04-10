"""
数据迁移脚本
将现有 JSON 数据迁移到 PostgreSQL 数据库
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import click
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import get_logger
from app.storage.database import AsyncSessionLocal, init_db, async_engine
from app.storage.models import (
    User, POI, Restaurant, Session as SessionModel, Message,
    Itinerary, Feedback, OperationLog, CacheEntry,
    MODELS, CREATE_ORDER,
)
from app.storage.repositories import (
    get_poi_repository, get_restaurant_repository,
    get_session_repository, get_message_repository,
)
from app.storage.vector_service import (
    VectorSearchService, POIEmbedding, get_vector_service, init_vector_service
)

logger = get_logger(__name__)


class DataMigration:
    """数据迁移器"""

    def __init__(self):
        self.data_dir = Path(__file__).parent.parent.parent / "data"
        self.migrated_count = {
            "pois": 0,
            "restaurants": 0,
            "sessions": 0,
            "messages": 0,
            "itineraries": 0,
        }
        self.failed_count = {
            "pois": 0,
            "restaurants": 0,
            "sessions": 0,
            "messages": 0,
            "itineraries": 0,
        }

    async def init_database(self) -> None:
        """初始化数据库"""
        logger.info("Initializing database...")
        await init_db()
        logger.info("Database initialized")

    async def migrate_pois(self, session: AsyncSession) -> Dict[str, int]:
        """迁移景点数据"""
        logger.info("Starting POI migration...")

        pois_dir = self.data_dir / "pois"
        if not pois_dir.exists():
            logger.warning(f"POIs directory not found: {pois_dir}")
            return {"success": 0, "failed": 0}

        poi_repo = get_poi_repository(session)
        success = 0
        failed = 0

        for poi_file in pois_dir.glob("*.json"):
            try:
                with open(poi_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                city = data.get("city", "Unknown")
                city_code = data.get("city_code", "unknown")
                pois = data.get("pois", [])

                for poi_data in pois:
                    poi_id = poi_data.get("id", f"poi_{uuid4().hex[:8]}")

                    # 标准化数据
                    normalized_poi = {
                        "poi_id": poi_id,
                        "name": poi_data.get("name", ""),
                        "city": city,
                        "city_code": city_code,
                        "latitude": poi_data.get("latitude", 0) or 0,
                        "longitude": poi_data.get("longitude", 0) or 0,
                        "category": self._normalize_category(poi_data.get("category", "")),
                        "tags": poi_data.get("tags", []),
                        "description": poi_data.get("description"),
                        "rating": poi_data.get("rating", 0) or 0,
                        "ticket_price": poi_data.get("ticket_price"),
                        "opening_hours": poi_data.get("opening_hours"),
                        "recommended_duration": int(poi_data.get("recommended_duration", 120) or 120),
                        "indoor_outdoor": poi_data.get("indoor_outdoor", "mixed"),
                        "intensity": poi_data.get("intensity", "medium"),
                        "walk_level": poi_data.get("walk_level", "medium"),
                        "suitable_for": poi_data.get("suitable_for", []),
                        "best_time_of_day": poi_data.get("best_time", []),
                        "accessibility_score": self._calculate_accessibility_score(poi_data),
                        "is_active": True,
                    }

                    # 添加可选字段
                    if "address" in poi_data:
                        normalized_poi["address"] = poi_data["address"]
                    if "province" in poi_data:
                        normalized_poi["province"] = poi_data["province"]
                    if "images" in poi_data:
                        normalized_poi["images"] = poi_data["images"]

                    # 检查是否已存在
                    existing = await poi_repo.get_by_poi_id(poi_id)
                    if existing:
                        await poi_repo.update(poi_id, **normalized_poi)
                    else:
                        await poi_repo.create(**normalized_poi)

                    success += 1

                logger.info(f"Migrated {len(pois)} POIs from {poi_file.name}")

            except Exception as e:
                logger.error(f"Failed to migrate {poi_file.name}: {e}")
                failed += len(poi_data.get("pois", [{}]))  # 估算

        await session.commit()
        self.migrated_count["pois"] = success
        self.failed_count["pois"] = failed

        logger.info(f"POI migration completed: {success} success, {failed} failed")
        return {"success": success, "failed": failed}

    async def migrate_restaurants(self, session: AsyncSession) -> Dict[str, int]:
        """迁移餐厅数据"""
        logger.info("Starting restaurant migration...")

        restaurants_dir = self.data_dir / "restaurants"
        if not restaurants_dir.exists():
            logger.warning(f"Restaurants directory not found: {restaurants_dir}")
            return {"success": 0, "failed": 0}

        restaurant_repo = get_restaurant_repository(session)
        success = 0
        failed = 0

        for restaurant_file in restaurants_dir.glob("*.json"):
            try:
                with open(restaurant_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                city = data.get("city", "Unknown")
                restaurants = data.get("restaurants", [])

                for rest_data in restaurants:
                    restaurant_id = rest_data.get("id", f"rest_{uuid4().hex[:8]}")

                    normalized_rest = {
                        "restaurant_id": restaurant_id,
                        "name": rest_data.get("name", ""),
                        "city": city,
                        "latitude": rest_data.get("latitude", 0) or 0,
                        "longitude": rest_data.get("longitude", 0) or 0,
                        "cuisine_type": rest_data.get("cuisine_type", "其他"),
                        "tags": rest_data.get("tags", []),
                        "rating": rest_data.get("rating", 0) or 0,
                        "average_price": rest_data.get("average_price"),
                        "opening_hours": rest_data.get("opening_hours"),
                        "features": rest_data.get("features", []),
                        "dietary_options": rest_data.get("dietary_options", []),
                        "is_active": True,
                    }

                    if "address" in rest_data:
                        normalized_rest["address"] = rest_data["address"]
                    if "district" in rest_data:
                        normalized_rest["district"] = rest_data["district"]
                    if "images" in rest_data:
                        normalized_rest["images"] = rest_data["images"]

                    await restaurant_repo.upsert(restaurant_id, **normalized_rest)
                    success += 1

                logger.info(f"Migrated {len(restaurants)} restaurants from {restaurant_file.name}")

            except Exception as e:
                logger.error(f"Failed to migrate {restaurant_file.name}: {e}")
                failed += len(rest_data.get("restaurants", [{}]))

        await session.commit()
        self.migrated_count["restaurants"] = success
        self.failed_count["restaurants"] = failed

        logger.info(f"Restaurant migration completed: {success} success, {failed} failed")
        return {"success": success, "failed": failed}

    async def migrate_cache_to_db(self, session: AsyncSession) -> Dict[str, int]:
        """将 JSON 缓存数据迁移到数据库"""
        logger.info("Starting cache migration...")

        cache_dir = self.data_dir / "cache"
        if not cache_dir.exists():
            logger.warning(f"Cache directory not found: {cache_dir}")
            return {"success": 0, "failed": 0}

        success = 0
        failed = 0

        # 迁移 POI 缓存
        poi_cache_dir = cache_dir / "poi"
        if poi_cache_dir.exists():
            for cache_file in poi_cache_dir.glob("*.json"):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cache_data = json.load(f)

                    # 提取查询参数作为缓存键
                    cache_key = cache_file.stem  # 文件名作为键

                    # 存储到数据库
                    entry = CacheEntry(
                        cache_key=f"migrated:poi:{cache_key}",
                        cache_category="poi",
                        cache_value=cache_data,
                        ttl_seconds=3600 * 24 * 7,  # 7 天
                        expires_at=datetime.utcnow() + timedelta(days=7),
                    )
                    session.add(entry)
                    success += 1

                except Exception as e:
                    logger.error(f"Failed to migrate cache {cache_file.name}: {e}")
                    failed += 1

        await session.commit()
        logger.info(f"Cache migration completed: {success} success, {failed} failed")
        return {"success": success, "failed": failed}

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

    def _calculate_accessibility_score(self, poi_data: Dict[str, Any]) -> float:
        """计算适老化评分"""
        score = 1.0  # 默认满分

        # 检查是否为老年友好
        suitable_for = poi_data.get("suitable_for", [])
        if "老人" in suitable_for:
            score = max(score, 0.9)
        elif "家庭" in suitable_for:
            score = max(score, 0.8)

        # 检查体力强度
        intensity = poi_data.get("intensity", "medium")
        if intensity == "high":
            score -= 0.3
        elif intensity == "low":
            score += 0.1

        # 检查是否室内
        if poi_data.get("indoor", False):
            score += 0.1

        return min(1.0, max(0.0, score))

    async def get_migration_report(self) -> Dict[str, Any]:
        """获取迁移报告"""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "migrated": self.migrated_count,
            "failed": self.failed_count,
            "total_migrated": sum(self.migrated_count.values()),
            "total_failed": sum(self.failed_count.values()),
        }


async def run_migration(migrate_pois: bool = True, migrate_restaurants: bool = True,
                       migrate_cache: bool = True) -> Dict[str, Any]:
    """运行迁移"""
    migration = DataMigration()

    # 初始化数据库
    await migration.init_database()

    async with AsyncSessionLocal() as session:
        results = {}

        if migrate_pois:
            results["pois"] = await migration.migrate_pois(session)

        if migrate_restaurants:
            results["restaurants"] = await migration.migrate_restaurants(session)

        if migrate_cache:
            results["cache"] = await migration.migrate_cache_to_db(session)

        return results


@click.group()
def cli():
    """数据迁移命令行工具"""
    pass


@cli.command()
@click.option("--pois/--no-pois", default=True, help="Migrate POI data")
@click.option("--restaurants/--no-restaurants", default=True, help="Migrate restaurant data")
@click.option("--cache/--no-cache", default=True, help="Migrate cache data")
def migrate(pois, restaurants, cache):
    """运行数据迁移"""
    asyncio.run(run_migration(
        migrate_pois=pois,
        migrate_restaurants=restaurants,
        migrate_cache=cache,
    ))


@cli.command()
def init():
    """初始化数据库"""
    asyncio.run(DataMigration().init_database())
    click.echo("Database initialized successfully!")


if __name__ == "__main__":
    cli()
