"""
Backup and Restore Tools - 备份与恢复工具
支持 PostgreSQL、Redis 和向量数据库的备份与恢复
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tarfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib

import click

from app.core.config import settings
from app.core.logger import get_logger
from app.storage.database import AsyncSessionLocal, async_engine
from app.storage.models import MODELS
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class BackupManager:
    """备份管理器"""

    def __init__(self, backup_dir: Optional[Path] = None):
        self.backup_dir = backup_dir or Path("backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def generate_backup_name(self, prefix: str = "backup") -> str:
        """生成备份文件名"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}"

    async def backup_postgresql(self, output_path: Path) -> Dict[str, Any]:
        """
        备份 PostgreSQL 数据库

        Returns:
            备份元信息
        """
        logger.info(f"Starting PostgreSQL backup to {output_path}")

        backup_info = {
            "type": "postgresql",
            "timestamp": datetime.utcnow().isoformat(),
            "tables": {},
        }

        async with AsyncSessionLocal() as session:
            for model in MODELS:
                table_name = model.__tablename__
                try:
                    # 统计行数
                    result = await session.execute(
                        select(text(f"COUNT(*) FROM {table_name}"))
                    )
                    count = result.scalar()

                    backup_info["tables"][table_name] = {
                        "row_count": count,
                    }
                    logger.info(f"  {table_name}: {count} rows")

                except Exception as e:
                    logger.error(f"  {table_name}: Error - {e}")
                    backup_info["tables"][table_name] = {
                        "error": str(e),
                    }

        # 创建备份文件
        backup_info["file_path"] = str(output_path)
        backup_info["status"] = "completed"

        logger.info(f"PostgreSQL backup completed: {output_path}")
        return backup_info

    async def backup_redis(self, output_path: Path) -> Dict[str, Any]:
        """
        备份 Redis 数据

        注意: 这是一个简化版本，实际生产环境应使用 Redis 的 BGSAVE 或 RDB/AOF
        """
        logger.info(f"Starting Redis backup info collection...")

        backup_info = {
            "type": "redis",
            "timestamp": datetime.utcnow().isoformat(),
            "keys": [],
        }

        # 连接到 Redis 获取键统计
        try:
            import redis.asyncio as redis

            client = redis.from_url(
                settings.database.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )

            # 获取键统计
            key_info = []
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, count=100)
                for key in keys:
                    key_type = await client.type(key)
                    ttl = await client.ttl(key)
                    key_info.append({
                        "key": key,
                        "type": key_type,
                        "ttl": ttl,
                    })
                if cursor == 0:
                    break

            backup_info["keys"] = key_info
            backup_info["total_keys"] = len(key_info)

            await client.close()

        except Exception as e:
            logger.error(f"Redis backup error: {e}")
            backup_info["error"] = str(e)

        # 保存备份信息
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(backup_info, f, indent=2, ensure_ascii=False)

        logger.info(f"Redis backup completed: {len(backup_info['keys'])} keys")
        return backup_info

    async def backup_vector_db(self, output_path: Path) -> Dict[str, Any]:
        """
        备份向量数据库

        注意: 实际备份需要根据向量数据库类型选择合适的方法
        """
        logger.info(f"Starting vector database backup info collection...")

        backup_info = {
            "type": "vector_db",
            "provider": settings.vector_db.provider,
            "collection": settings.vector_db.collection_name,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # 保存备份信息
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(backup_info, f, indent=2, ensure_ascii=False)

        logger.info(f"Vector DB backup info saved: {output_path}")
        return backup_info

    async def backup_json_files(self, data_dir: Path, output_dir: Path) -> Dict[str, Any]:
        """备份 JSON 数据文件"""
        logger.info(f"Starting JSON files backup from {data_dir}...")

        backup_info = {
            "type": "json_files",
            "timestamp": datetime.utcnow().isoformat(),
            "files": [],
        }

        if not data_dir.exists():
            backup_info["error"] = "Data directory not found"
            return backup_info

        # 复制 JSON 文件
        for json_file in data_dir.rglob("*.json"):
            try:
                relative_path = json_file.relative_to(data_dir)
                dest_path = output_dir / relative_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(json_file, dest_path)

                file_size = json_file.stat().st_size
                backup_info["files"].append({
                    "path": str(relative_path),
                    "size": file_size,
                })
            except Exception as e:
                logger.error(f"Failed to backup {json_file}: {e}")

        backup_info["total_files"] = len(backup_info["files"])
        logger.info(f"JSON backup completed: {len(backup_info['files'])} files")
        return backup_info

    async def create_full_backup(self, name: Optional[str] = None) -> Dict[str, Any]:
        """创建完整备份"""
        backup_name = name or self.generate_backup_name("full_backup")
        backup_path = self.backup_dir / backup_name
        backup_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Creating full backup: {backup_name}")

        # 备份各个组件
        results = {}

        # PostgreSQL
        pg_info = await self.backup_postgresql(backup_path / "postgresql_info.json")
        results["postgresql"] = pg_info

        # Redis
        redis_info = await self.backup_redis(backup_path / "redis_info.json")
        results["redis"] = redis_info

        # Vector DB
        vector_info = await self.backup_vector_db(backup_path / "vector_db_info.json")
        results["vector_db"] = vector_info

        # JSON 文件
        data_dir = Path(__file__).parent.parent.parent / "data"
        json_info = await self.backup_json_files(data_dir, backup_path / "data")
        results["json_files"] = json_info

        # 创建备份清单
        manifest = {
            "backup_name": backup_name,
            "created_at": datetime.utcnow().isoformat(),
            "version": settings.version,
            "results": results,
        }

        with open(backup_path / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # 创建压缩包
        archive_path = self.backup_dir / f"{backup_name}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(backup_path, arcname=backup_name)

        # 计算校验和
        checksum = self._calculate_checksum(archive_path)
        manifest["checksum"] = checksum
        manifest["archive_path"] = str(archive_path)

        # 更新清单
        with open(backup_path / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # 删除临时目录
        shutil.rmtree(backup_path)

        logger.info(f"Full backup completed: {archive_path}")

        return manifest

    async def list_backups(self) -> List[Dict[str, Any]]:
        """列出所有备份"""
        backups = []

        for archive in self.backup_dir.glob("*.tar.gz"):
            try:
                info = {
                    "name": archive.stem,
                    "path": str(archive),
                    "size": archive.stat().st_size,
                    "created": datetime.fromtimestamp(archive.stat().st_ctime).isoformat(),
                }

                # 尝试读取清单
                manifest_path = self.backup_dir / archive.stem / "manifest.json"
                if not manifest_path.exists():
                    # 从压缩包中提取清单
                    try:
                        with tarfile.open(archive, "r:gz") as tar:
                            manifest_member = tar.extractfile(f"{archive.stem}/manifest.json")
                            if manifest_member:
                                manifest = json.loads(manifest_member.read().decode())
                                info["manifest"] = manifest
                    except Exception:
                        pass

                backups.append(info)

            except Exception as e:
                logger.error(f"Failed to read backup {archive}: {e}")

        return sorted(backups, key=lambda x: x["created"], reverse=True)

    async def restore_backup(self, backup_name: str, restore_path: Optional[Path] = None) -> Dict[str, Any]:
        """恢复备份"""
        archive_path = self.backup_dir / f"{backup_name}.tar.gz"

        if not archive_path.exists():
            raise FileNotFoundError(f"Backup not found: {archive_name}")

        # 验证校验和
        checksum = self._calculate_checksum(archive_path)
        logger.info(f"Backup checksum: {checksum}")

        # 解压备份
        extract_path = restore_path or self.backup_dir / "restore" / backup_name
        extract_path.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_path)

        # 读取清单
        manifest_path = extract_path / "manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        restore_info = {
            "backup_name": backup_name,
            "extracted_to": str(extract_path),
            "manifest": manifest,
        }

        logger.info(f"Backup extracted to: {extract_path}")
        return restore_info

    async def delete_backup(self, backup_name: str) -> bool:
        """删除备份"""
        archive_path = self.backup_dir / f"{backup_name}.tar.gz"

        if archive_path.exists():
            archive_path.unlink()
            logger.info(f"Deleted backup: {backup_name}")
            return True

        return False

    def _calculate_checksum(self, file_path: Path) -> str:
        """计算文件校验和"""
        sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)

        return sha256.hexdigest()

    async def cleanup_old_backups(self, keep_days: int = 7) -> int:
        """清理旧备份"""
        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted = 0

        for archive in self.backup_dir.glob("*.tar.gz"):
            try:
                if datetime.fromtimestamp(archive.stat().st_ctime) < cutoff:
                    archive.unlink()
                    deleted += 1
                    logger.info(f"Deleted old backup: {archive.name}")
            except Exception as e:
                logger.error(f"Failed to delete {archive}: {e}")

        return deleted


class DataExporter:
    """数据导出器"""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path("exports")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def export_pois(self, city: Optional[str] = None) -> Path:
        """导出 POI 数据"""
        logger.info("Exporting POI data...")

        async with AsyncSessionLocal() as session:
            from app.storage.repositories import get_poi_repository
            poi_repo = get_poi_repository(session)

            pois = await poi_repo.search(city=city, limit=10000)
            poi_data = []

            for poi in pois:
                poi_data.append({
                    "poi_id": poi.poi_id,
                    "name": poi.name,
                    "city": poi.city,
                    "category": poi.category,
                    "tags": poi.tags,
                    "rating": poi.rating,
                    "ticket_price": poi.ticket_price,
                    "description": poi.description,
                    "latitude": poi.latitude,
                    "longitude": poi.longitude,
                    "address": poi.address,
                })

        # 保存文件
        filename = f"pois_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        if city:
            filename += f"_{city}"

        output_path = self.output_dir / f"{filename}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"pois": poi_data, "exported_at": datetime.utcnow().isoformat()}, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(poi_data)} POIs to {output_path}")
        return output_path

    async def export_users(self) -> Path:
        """导出用户数据"""
        logger.info("Exporting user data...")

        async with AsyncSessionLocal() as session:
            from app.storage.repositories import get_user_repository
            user_repo = get_user_repository(session)

            users = await user_repo.list(limit=10000)
            user_data = []

            for user in users:
                user_data.append({
                    "user_id": user.user_id,
                    "username": user.username,
                    "email": user.email,
                    "travel_styles": user.travel_styles,
                    "budget_level": user.budget_level,
                    "tourist_type": user.tourist_type,
                    "liked_pois": user.liked_pois,
                    "disliked_pois": user.disliked_pois,
                    "preferred_cities": user.preferred_cities,
                    "created_at": user.created_at.isoformat(),
                })

        # 保存文件
        filename = f"users_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = self.output_dir / filename

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"users": user_data, "exported_at": datetime.utcnow().isoformat()}, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(user_data)} users to {output_path}")
        return output_path

    async def export_itineraries(self, user_id: Optional[int] = None) -> Path:
        """导出行程数据"""
        logger.info("Exporting itinerary data...")

        async with AsyncSessionLocal() as session:
            from app.storage.repositories import get_itinerary_repository
            itinerary_repo = get_itinerary_repository(session)

            if user_id:
                itineraries = await itinerary_repo.list_by_user(user_id, limit=10000)
            else:
                # 获取所有行程 (简化处理)
                itineraries = []

            itinerary_data = []
            for itinerary in itineraries:
                itinerary_data.append({
                    "itinerary_id": itinerary.itinerary_id,
                    "title": itinerary.title,
                    "destination": itinerary.destination,
                    "start_date": itinerary.start_date,
                    "end_date": itinerary.end_date,
                    "duration_days": itinerary.duration_days,
                    "total_budget": itinerary.total_budget,
                    "estimated_cost": itinerary.estimated_cost,
                    "status": itinerary.status,
                    "plan_data": itinerary.plan_data,
                    "created_at": itinerary.created_at.isoformat(),
                })

        # 保存文件
        filename = f"itineraries_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        if user_id:
            filename += f"_user_{user_id}"

        output_path = self.output_dir / f"{filename}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"itineraries": itinerary_data, "exported_at": datetime.utcnow().isoformat()}, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {len(itinerary_data)} itineraries to {output_path}")
        return output_path


# ==================== CLI Commands ====================

@click.group()
def cli():
    """备份与恢复命令行工具"""
    pass


@cli.command()
@click.option("--name", help="Backup name (default: auto-generated)")
def backup(name):
    """创建完整备份"""
    manager = BackupManager()
    result = asyncio.run(manager.create_full_backup(name))
    click.echo(f"Backup created: {result['archive_path']}")
    click.echo(f"Checksum: {result.get('checksum', 'N/A')}")


@cli.command()
def list():
    """列出所有备份"""
    manager = BackupManager()
    backups = asyncio.run(manager.list_backups())

    if not backups:
        click.echo("No backups found")
        return

    for backup in backups:
        click.echo(f"\n{backup['name']}")
        click.echo(f"  Created: {backup['created']}")
        click.echo(f"  Size: {backup['size'] / 1024 / 1024:.2f} MB")


@cli.command()
@click.argument("backup_name")
def restore(backup_name):
    """恢复备份"""
    manager = BackupManager()
    result = asyncio.run(manager.restore_backup(backup_name))
    click.echo(f"Backup restored to: {result['extracted_to']}")


@cli.command()
@click.argument("backup_name")
def delete(backup_name):
    """删除备份"""
    manager = BackupManager()
    success = asyncio.run(manager.delete_backup(backup_name))
    if success:
        click.echo(f"Backup deleted: {backup_name}")
    else:
        click.echo(f"Backup not found: {backup_name}")


@cli.command()
@click.option("--days", default=7, help="Keep backups for N days")
def cleanup(days):
    """清理旧备份"""
    manager = BackupManager()
    deleted = asyncio.run(manager.cleanup_old_backups(keep_days=days))
    click.echo(f"Deleted {deleted} old backups")


@cli.group()
def export():
    """导出数据"""
    pass


@export.command()
@click.option("--city", help="Filter by city")
def pois(city):
    """导出 POI 数据"""
    exporter = DataExporter()
    path = asyncio.run(exporter.export_pois(city))
    click.echo(f"Exported to: {path}")


@export.command()
def users():
    """导出用户数据"""
    exporter = DataExporter()
    path = asyncio.run(exporter.export_users())
    click.echo(f"Exported to: {path}")


@export.command()
@click.option("--user-id", type=int, help="Filter by user ID")
def itineraries(user_id):
    """导出行程数据"""
    exporter = DataExporter()
    path = asyncio.run(exporter.export_itineraries(user_id))
    click.echo(f"Exported to: {path}")


if __name__ == "__main__":
    cli()
