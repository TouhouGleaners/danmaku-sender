"""历史账本迁移：建表与表结构版本升级。

各步幂等、可重复执行；结构版本记在 SQLite 的 user_version。
表结构变更用 playhouse.migrate，存在性检查用 peewee 的 get_columns。
"""
import logging

from peewee import CharField, SqliteDatabase
from playhouse.migrate import SqliteMigrator, migrate

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
        """重建旧结构遗留的废索引。

        废索引的 index_info 列号为 -2（按缺列建出的空壳索引），走它的查询会漏行；
        命中即整体 REINDEX 重建。

        Args:
            sqlite_db (SqliteDatabase): 已连接的数据库。
        """
        for table in sqlite_db.get_tables():
            for index in sqlite_db.get_indexes(table):
                rows = sqlite_db.execute_sql(f"PRAGMA index_info('{index.name}')").fetchall()
                if any(column == -2 for _, column, _ in rows):
                    logger.warning(f"索引 {index.name} 为废索引，重建")
                    sqlite_db.execute_sql("REINDEX")
                    return

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
