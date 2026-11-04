"""历史账本迁移：建表、表结构版本升级与数据回填。

各步幂等、可重复执行；结构版本记在 SQLite 的 user_version。
表结构变更用 playhouse.migrate，存在性检查用 peewee 的 get_columns。
"""
import logging
from collections.abc import Iterable

from peewee import CharField, SqliteDatabase
from playhouse.migrate import SqliteMigrator, migrate

from danmaku_sender.types.models.queue import TaskStatus

from .orm_models import SentDanmaku, TaskRecord, db

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1  # 数据库结构版本；0 表示 2.6.1 及更早的库


class SchemaMigration:
    """表结构迁移：按版本号逐级升级到当前结构，并重建失效索引。"""

    @staticmethod
    def run(sqlite_db: SqliteDatabase) -> None:
        """将已有数据库逐级升级至 :data:`SCHEMA_VERSION`，并重建失效索引。

        空数据库无版本可升级，直接写入当前版本号；每步完成结构变更后更新版本号，
        中断后重跑不会重复变更；无法识别的版本抛 RuntimeError。
        创建表与索引由调用方负责，且须在本方法之后执行。

        Args:
            sqlite_db (SqliteDatabase): 已连接的数据库。

        Raises:
            RuntimeError: 数据库结构版本高于本应用支持或无法识别。
        """
        migrator = SqliteMigrator(sqlite_db)
        while (version := SchemaMigration._user_version(sqlite_db)) != SCHEMA_VERSION:
            match version:
                case 0:
                    # 表不存在时没有可添加的列；缺失的表由调用方按当前结构创建
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
        """重建失效索引：task_id 索引存在而 (task_id, bvid, cid, ctime) 索引缺失时执行 REINDEX。

        Args:
            sqlite_db (SqliteDatabase): 已连接的数据库。
        """
        indexes = {tuple(index.columns) for index in sqlite_db.get_indexes('sent_danmaku')}
        if ('task_id', 'bvid', 'cid', 'ctime') in indexes:
            return
        if ('task_id',) not in indexes:
            return
        logger.warning("检测到失效索引，执行 REINDEX")
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
    """无主存证回填：将 task_id 为空的存证归集为 legacy 任务。

    Attributes:
        GAP (float): 分段间隔阈值（秒）；相邻发送间隔超过该值时开始新分段。
    """

    GAP = 600.0

    @classmethod
    def run(cls) -> None:
        """按 (bvid, cid) 与发送连续段归集无主存证并回填 task_id。

        每段创建一条 legacy 任务（标识为 ``legacy-{bvid}-{cid}-{段首时间戳}``，标题留空）；
        只修改 task_id 为空的行，重复执行结果不变。逐行流式读取，每段整体写入。
        """
        orphans: Iterable[dict] = (
            SentDanmaku
                .select(SentDanmaku.bvid, SentDanmaku.cid, SentDanmaku.ctime)
                .where(SentDanmaku.task_id.is_null(True))
                .order_by(SentDanmaku.bvid, SentDanmaku.cid, SentDanmaku.ctime)
                .dicts()
                .iterator()
        )  # type: ignore[assignment]
        first: dict | None = None
        prev: dict | None = None
        for row in orphans:
            if first is not None and prev is not None and cls._is_new_segment(prev, row):
                cls._backfill_segment(first, prev)
                first = None
            if first is None:
                first = row
            prev = row
        if first is not None and prev is not None:
            cls._backfill_segment(first, prev)

    @classmethod
    def _is_new_segment(cls, prev: dict, row: dict) -> bool:
        """判定是否开始新分段：归属变化，或发送间隔超过分段间隔阈值。

        Args:
            prev (dict): 段内上一条存证。
            row (dict): 当前存证。

        Returns:
            bool: 开始新分段时为 True。
        """
        return (
            (prev['bvid'], prev['cid']) != (row['bvid'], row['cid'])
            or row['ctime'] - prev['ctime'] > cls.GAP
        )

    @staticmethod
    def _backfill_segment(first: dict, last: dict) -> None:
        """为一个分段创建 legacy 任务并整体回填。

        Args:
            first (dict): 段首存证。
            last (dict): 段尾存证。
        """
        task_id = f"legacy-{first['bvid']}-{first['cid']}-{int(first['ctime'])}"
        with db.atomic():
            TaskRecord.get_or_create(
                task_id=task_id,
                defaults={
                    'bvid': first['bvid'],
                    'cid': first['cid'],
                    'video_title': None,
                    'part_page': None,
                    'part_title': None,
                    'xml_path': None,
                    'created_at': first['ctime'],
                    'status': TaskStatus.COMPLETED.name,
                },
            )
            (
                SentDanmaku
                    .update(task_id=task_id)
                    .where(
                        SentDanmaku.task_id.is_null(True),
                        SentDanmaku.bvid == first['bvid'],
                        SentDanmaku.cid == first['cid'],
                        SentDanmaku.ctime >= first['ctime'],
                        SentDanmaku.ctime <= last['ctime'],
                    )
                    .execute()
            )
