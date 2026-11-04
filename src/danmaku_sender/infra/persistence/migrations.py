"""历史账本迁移：建表、表结构版本升级与数据回填。

各步幂等、可重复执行；结构版本记在 SQLite 的 user_version。
表结构变更用 playhouse.migrate，存在性检查用 peewee 的 get_columns。
"""
import logging
from collections.abc import Iterable

from peewee import CharField, SqliteDatabase
from playhouse.migrate import SqliteMigrator, migrate

from danmaku_sender.types.models.queue import TaskStatus

from .orm_models import SentDanmaku, TaskRecord

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1  # 数据库结构版本；0 表示 2.6.1 及更早的库


class SchemaMigration:
    """表结构迁移：按版本号逐级升级到当前结构，并修复旧结构遗留的废索引。"""

    @staticmethod
    def run(sqlite_db: SqliteDatabase) -> None:
        """把已有库逐级升级到 :data:`SCHEMA_VERSION`，并修复旧结构遗留的废索引。

        空库无可升、直接落版；每步完成结构变更后抬高版本，中断后重跑不会重复变更；
        无法识别的版本抛 RuntimeError。建表建索引由调用方负责，且须在本方法之后——索引要建在补列之后。

        Args:
            sqlite_db (SqliteDatabase): 已连接的数据库。

        Raises:
            RuntimeError: 数据库结构版本高于本应用支持或无法识别。
        """
        migrator = SqliteMigrator(sqlite_db)
        while (version := SchemaMigration._user_version(sqlite_db)) != SCHEMA_VERSION:
            match version:
                case 0:
                    # 表不存在时无列可补，缺表由调用方按现行结构建出
                    if 'sent_danmaku' in sqlite_db.get_tables():
                        columns = {col.name for col in sqlite_db.get_columns('sent_danmaku')}
                        if 'task_id' not in columns:
                            migrate(migrator.add_column('sent_danmaku', 'task_id', CharField(null=True)))
                    SchemaMigration._set_user_version(sqlite_db, 1)
                case _:
                    if version > SCHEMA_VERSION:
                        raise RuntimeError(f"数据库结构版本 {version} 新于本应用支持的 {SCHEMA_VERSION}，请升级应用")
                    raise RuntimeError(f"未知的数据库结构版本 {version}，本应用支持到 {SCHEMA_VERSION}")

        SchemaMigration._repair_indexes(sqlite_db)

    @staticmethod
    def _repair_indexes(sqlite_db: SqliteDatabase) -> None:
        """重建全部索引，修复旧结构遗留的作废索引。

        Args:
            sqlite_db (SqliteDatabase): 已连接的数据库。
        """
        sqlite_db.execute_sql("REINDEX")

    @staticmethod
    def _user_version(sqlite_db: SqliteDatabase) -> int:
        """读取数据库结构版本（SQLite 的 user_version）。

        Args:
            sqlite_db (SqliteDatabase): 已连接的数据库。

        Returns:
            int: 数据库结构版本，从未写入时为 0。
        """
        return int(sqlite_db.execute_sql("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def _set_user_version(sqlite_db: SqliteDatabase, version: int) -> None:
        """写入数据库结构版本（SQLite 的 user_version）。

        PRAGMA 不支持参数绑定，version 以整数形式拼入语句。

        Args:
            sqlite_db (SqliteDatabase): 已连接的数据库。
            version (int): 要写入的数据库结构版本。
        """
        sqlite_db.execute_sql(f"PRAGMA user_version = {int(version)}")


class LegacyBackfill:
    """无主存证回填：把 task_id 为空的存证归集为 legacy 任务。

    Attributes:
        GAP (float): 断段阈值（秒）；相邻发送间隔超过它视为新批次。
        WRITE_BATCH (int): 回写批大小，不超过 SQLite 单语句的绑定变量上限。
    """

    GAP = 600.0
    WRITE_BATCH = 500

    @classmethod
    def run(cls) -> None:
        """按 (bvid, cid) 与发送连续段归集无主存证并回填 task_id。

        每段创建一条 legacy 任务（标识为 ``legacy-{bvid}-{cid}-{段首时间戳}``，标题留空）；
        只修改 task_id 为空的行，重复执行结果不变。逐行流式读取，回写按批落库。
        """
        orphans: Iterable[dict] = (
            SentDanmaku
                .select(SentDanmaku.dmid, SentDanmaku.bvid, SentDanmaku.cid, SentDanmaku.ctime)
                .where(SentDanmaku.task_id.is_null(True))
                .order_by(SentDanmaku.bvid, SentDanmaku.cid, SentDanmaku.ctime, SentDanmaku.dmid)
                .dicts()
        )  # type: ignore[assignment]
        task_id: str | None = None
        batch: list[str] = []
        prev: dict | None = None
        for row in orphans:
            if prev is not None and cls._is_new_segment(prev, row):
                cls._write(task_id, batch)
                batch = []
                task_id = None
            if task_id is None:
                task_id = cls._start_segment(row)
            batch.append(row['dmid'])
            if len(batch) >= cls.WRITE_BATCH:
                cls._write(task_id, batch)
                batch = []
            prev = row
        cls._write(task_id, batch)

    @classmethod
    def _is_new_segment(cls, prev: dict, row: dict) -> bool:
        """判定是否另起一段：归属变化，或发送间隔超过断段阈值。

        Args:
            prev (dict): 段内上一条存证。
            row (dict): 当前存证。

        Returns:
            bool: 另起一段时为 True。
        """
        return (
            (prev['bvid'], prev['cid']) != (row['bvid'], row['cid'])
            or row['ctime'] - prev['ctime'] > cls.GAP
        )

    @staticmethod
    def _start_segment(row: dict) -> str:
        """创建一段的 legacy 任务并返回其标识。

        Args:
            row (dict): 段首存证。

        Returns:
            str: legacy 任务标识。
        """
        task_id = f"legacy-{row['bvid']}-{row['cid']}-{int(row['ctime'])}"
        TaskRecord.get_or_create(
            task_id=task_id,
            defaults={
                'bvid': row['bvid'],
                'cid': row['cid'],
                'video_title': None,
                'part_page': None,
                'part_title': None,
                'xml_path': None,
                'created_at': row['ctime'],
                'status': TaskStatus.COMPLETED.name,
            },
        )
        return task_id

    @staticmethod
    def _write(task_id: str | None, dmids: list[str]) -> None:
        """把一批存证回填归属，只修改 task_id 为空的行。

        Args:
            task_id (str | None): 归属任务标识；None 表示无待写批次。
            dmids (list[str]): 待回填的存证 dmid，长度不超过 :data:`WRITE_BATCH`。
        """
        if not dmids:
            return
        (
            SentDanmaku
                .update(task_id=task_id)
                .where(SentDanmaku.dmid.in_(dmids), SentDanmaku.task_id.is_null(True))
                .execute()
        )
