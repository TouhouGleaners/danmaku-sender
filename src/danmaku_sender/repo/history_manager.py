import logging
import time
from pathlib import Path

from peewee import Case, CharField, SqliteDatabase, fn
from playhouse.migrate import SqliteMigrator, migrate

from danmaku_sender.types.models.common import (
    DanmakuStatus,
    MonitorStats,
    PendingCidRecord,
    PendingDanmakuRecord,
    VideoTarget,
)
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDefinition, TaskStatus

from .orm_models import SentDanmaku, TaskRecord, db

logger = logging.getLogger(__name__)


class HistoryManager:
    """
    基于 Peewee ORM 的弹幕生命周期管理系统。
    负责实现"发送 -> 存证 -> 核销"的数据层逻辑。

    线程安全契约:
    - Peewee 的 SqliteDatabase 内部使用 threading.local() 为每个线程维护
      独立的 SQLite 连接，不存在跨线程共享连接的问题。
    - WAL 模式允许并发读 + 单写，配合 Peewee 的线程本地连接机制，
      在"短事务 + 适度写入并发"的前提下，多线程并发调用通常是安全的；
      高写入并发或长事务仍可能触发 ``database is locked`` 错误。
    - 每个写操作均为单条 SQL（Peewee 默认 autocommit），在上述前提下是原子操作，
      但不意味着该历史层在任意写入压力下都具备高可扩展性。
    """

    def __init__(self, db_path: Path):
        """打开（或创建）账本数据库并完成迁移。

        Args:
            db_path (Path): SQLite 文件路径。
        """
        self.db_path = db_path
        self._init_db()
        logger.debug("HistoryManager 初始化完成")

    def _init_db(self):
        """初始化数据库，自动迁移"""
        try:
            # 开启 WAL 模式提升并发性能
            sqlite_db = SqliteDatabase(
                self.db_path,
                pragmas={'journal_mode': 'wal'},
                check_same_thread=False
            )

            # 绑定代理并连接
            db.initialize(sqlite_db)
            sqlite_db.connect(reuse_if_open=True)

            # 建表（含索引，已存在则跳过）→ 迁移补列
            sqlite_db.create_tables([SentDanmaku, TaskRecord], safe=True)
            self._run_migrations(sqlite_db)

        except Exception as e:
            logger.critical(f"数据库初始化/迁移致命错误: {e}", exc_info=True)
            raise RuntimeError(f"HistoryManager 数据库初始化失败: {e}") from e

    def _run_migrations(self, sqlite_db: SqliteDatabase) -> None:
        """幂等迁移：补齐历史版本缺失的列与索引。

        Args:
            sqlite_db (SqliteDatabase): 已连接的数据库。
        """
        migrator = SqliteMigrator(sqlite_db)
        columns = {col.name for col in sqlite_db.get_columns('sent_danmaku')}
        if 'task_id' not in columns:
            migrate(migrator.add_column('sent_danmaku', 'task_id', CharField(null=True)))

    def record_danmaku(
        self,
        task_id: str,
        target: VideoTarget,
        dm: Danmaku,
        dmid: str,
        is_visible_api: bool = True,
    ):
        """
        记录一条刚刚发送成功的弹幕，状态置为 STATUS_PENDING (0)。

        Args:
            task_id (str): 归属任务，用于任务级历史对账。
            target (VideoTarget): 发送目标。
            dm (Danmaku): 发送的弹幕。
            dmid (str): 服务器返回的弹幕身份。
            is_visible_api (bool): API 是否回执可见。
        """
        if not dmid:
            logger.warning("尝试记录无 ID 的弹幕，操作跳过。")
            return

        try:
            (
                SentDanmaku
                    .insert(
                        dmid=str(dmid),
                        task_id=task_id,
                        cid=target.cid,
                        bvid=target.bvid,
                        msg=dm.msg,
                        progress=dm.progress,
                        mode=dm.mode,
                        fontsize=dm.fontsize,
                        color=dm.color,
                        ctime=time.time(),
                        is_visible=1 if is_visible_api else 0,
                        status=DanmakuStatus.PENDING.value,
                    )
                    .on_conflict_ignore()
                    .execute()
            )
        except Exception as e:
            logger.error(f"存证失败: {e}", exc_info=True)
            raise

    def upsert_task(self, definition: TaskDefinition, status: TaskStatus) -> None:
        """写入或更新一条任务记录。

        发送开始时调用；已写入的记录不删除，仅更新任务状态。

        Args:
            definition (TaskDefinition): 任务工单，提供身份与描述。
            status (TaskStatus): 当前任务状态，按 ``TaskStatus.name`` 落库。
        """
        meta = definition.meta
        try:
            (
                TaskRecord
                    .insert(
                        task_id=definition.task_id,
                        bvid=definition.target.bvid,
                        cid=definition.target.cid,
                        video_title=meta.video_title,
                        part_page=meta.part_page,
                        part_title=meta.part_title,
                        xml_path=str(meta.xml_path) if meta.xml_path is not None else None,
                        created_at=time.time(),
                        status=status.name,
                    )
                    .on_conflict(
                        conflict_target=[TaskRecord.task_id],
                        update={
                            TaskRecord.bvid: definition.target.bvid,
                            TaskRecord.cid: definition.target.cid,
                            TaskRecord.video_title: meta.video_title,
                            TaskRecord.part_page: meta.part_page,
                            TaskRecord.part_title: meta.part_title,
                            TaskRecord.xml_path: str(meta.xml_path) if meta.xml_path is not None else None,
                            TaskRecord.status: status.name,
                        },
                    )
                    .execute()
            )
        except Exception as e:
            logger.error(f"任务记录写入失败: {e}", exc_info=True)
            raise

    def get_task(self, task_id: str) -> dict | None:
        """读取一条任务记录。

        Args:
            task_id (str): 任务标识。

        Returns:
            dict | None: 记录字典；不存在返回 None。
        """
        row = TaskRecord.get_or_none(TaskRecord.task_id == task_id)
        return (
            {
                'task_id': row.task_id,
                'bvid': row.bvid,
                'cid': row.cid,
                'video_title': row.video_title,
                'part_page': row.part_page,
                'part_title': row.part_title,
                'xml_path': row.xml_path,
                'created_at': row.created_at,
                'status': row.status,
            }
            if row is not None
            else None
        )

    def get_recorded_targets(self, baseline: float = 0.0) -> list[tuple[str, int]]:
        """返回 baseline 之后有记录的目标，即监视器的核销范围。

        Args:
            baseline (float): 统计基线时间，0 表示不限。

        Returns:
            list[tuple[str, int]]: (bvid, cid)，按首次记录时间排序。

        Raises:
            Exception: 查询失败时上抛。
        """
        query = (
            SentDanmaku
                .select(SentDanmaku.bvid, SentDanmaku.cid)
                .group_by(SentDanmaku.bvid, SentDanmaku.cid)
                .order_by(fn.MIN(SentDanmaku.ctime))
        )
        if baseline > 0:
            # peewee 的 where() 不接受空条件
            query = query.where(SentDanmaku.ctime >= baseline)

        return [(row.bvid, row.cid) for row in query]

    def verify_dmids(self, verified_dmids: list[str]) -> int:
        """将确认存活的弹幕置为已验证。

        状态更新为 STATUS_VERIFIED (1)，只翻转当前仍为 PENDING 的行。

        Args:
            verified_dmids (list[str]): 监视器确认存活的弹幕身份列表。

        Returns:
            int: 实际翻转的行数。
        """
        if not verified_dmids:
            return 0

        try:
            query = (
                SentDanmaku
                    .update(status=DanmakuStatus.VERIFIED.value)
                    .where(
                        (SentDanmaku.dmid.in_(verified_dmids)) &
                        (SentDanmaku.status == DanmakuStatus.PENDING.value)
                    )
            )
            return query.execute()

        except Exception as e:
            logger.error(f"批量验证状态失败: {e}", exc_info=True)
            return 0

    def mark_as_lost(self, cid: int, verified_dmids: list[str]) -> int:
        """将该 CID 下未确认存活的 PENDING 弹幕标记为丢失。

        Args:
            cid (int): 分P 的 CID。
            verified_dmids (list[str]): 已确认存活的弹幕身份，不参与标记。

        Returns:
            int: 被标记为丢失的弹幕数量。
        """
        try:
            condition = (SentDanmaku.cid == cid) & (SentDanmaku.status == DanmakuStatus.PENDING.value)

            if verified_dmids:
                condition &= SentDanmaku.dmid.not_in(verified_dmids)

            query = (
                SentDanmaku
                    .update(status=DanmakuStatus.LOST.value)
                    .where(condition)
            )
            rows_updated = query.execute()

            if rows_updated > 0:
                logger.warning(f"标记了 {rows_updated} 条弹幕为'疑似丢失'。")

            return rows_updated

        except Exception as e:
            logger.error(f"标记丢失状态失败: {e}", exc_info=True)
            return 0

    def get_pending_cids(self) -> list[PendingCidRecord]:
        """获取所有含有待验证弹幕的 (bvid, cid) 列表。

        Returns:
            list[PendingCidRecord]: 待验证的目标列表。
        """
        try:
            return list(
                SentDanmaku
                    .select(SentDanmaku.bvid, SentDanmaku.cid)
                    .where(SentDanmaku.status == DanmakuStatus.PENDING.value)
                    .group_by(SentDanmaku.bvid, SentDanmaku.cid)
                    .dicts()
            )  # type: ignore[return-value]
        except Exception as e:
            logger.error(f"查询待验证 CID 列表失败: {e}", exc_info=True)
            return []

    def get_pending_records(self, cid: int) -> list[PendingDanmakuRecord]:
        """获取指定分P 下的待验证弹幕。

        Args:
            cid (int): 分P 的 CID。

        Returns:
            list[PendingDanmakuRecord]: 待验证弹幕列表。
        """
        try:
            return list(
                SentDanmaku
                    .select(SentDanmaku.dmid, SentDanmaku.msg, SentDanmaku.progress, SentDanmaku.ctime)
                    .where(
                        (SentDanmaku.cid == cid) &
                        (SentDanmaku.status == DanmakuStatus.PENDING.value)
                    )
                    .dicts()
            )  # type: ignore[return-value]

        except Exception as e:
            logger.error(f"查询 Pending 记录失败: {e}", exc_info=True)
            return []

    def get_stats(self, cid: int, stats_baseline: float = 0.0) -> tuple[int, int, int]:
        """获取指定分P 的存活统计。

        Args:
            cid (int): 分P 的 CID。
            stats_baseline (float): 统计基线时间，0 表示不限。

        Returns:
            tuple[int, int, int]: (总数, 已验证, 已丢失)。
        """
        try:
            conditions = [SentDanmaku.cid == cid]
            if stats_baseline > 0:
                conditions.append(SentDanmaku.ctime >= stats_baseline)

            stats = (
                SentDanmaku
                    .select(
                        fn.COUNT(SentDanmaku.dmid),
                        fn.SUM(Case(None, [(SentDanmaku.status == DanmakuStatus.VERIFIED.value, 1)], 0)),
                        fn.SUM(Case(None, [(SentDanmaku.status == DanmakuStatus.LOST.value, 1)], 0))
                    )
                    .where(*conditions)
                    .scalar(as_tuple=True)
            )

            if stats:
                total, verified, lost = stats
                return (total or 0, int(verified or 0), int(lost or 0))

        except Exception as e:
            logger.error(f"获取统计失败: {e}", exc_info=True)

        return 0, 0, 0

    def get_stats_for_target(self, target: VideoTarget, baseline: float = 0.0) -> MonitorStats:
        """获取指定目标的存活统计，包含 pending 的完整计数。

        Args:
            target (VideoTarget): 发送目标。
            baseline (float): 统计基线时间，0 表示不限。

        Returns:
            MonitorStats: 总数、已验证、待验证、已丢失。
        """
        cid = target.cid
        if cid is None:
            return MonitorStats(total=0, verified=0, pending=0, lost=0)

        total, verified, lost = self.get_stats(cid, baseline)
        pending = total - verified - lost
        return MonitorStats(
            total=total,
            verified=verified,
            pending=max(0, pending),
            lost=lost
        )

    def count_records(self, target: VideoTarget, dm: Danmaku) -> int:
        """统计数据库中与传入弹幕完全匹配的记录数量。

        Args:
            target (VideoTarget): 发送目标。
            dm (Danmaku): 比对的弹幕。

        Returns:
            int: 匹配的记录数。
        """
        try:
            return (
                SentDanmaku
                    .select()
                    .where(
                        (SentDanmaku.cid == target.cid) &
                        (SentDanmaku.msg == dm.msg) &
                        (SentDanmaku.mode == dm.mode) &
                        (SentDanmaku.color == dm.color) &
                        (SentDanmaku.fontsize == dm.fontsize) &
                        (SentDanmaku.progress == dm.progress) &
                        (SentDanmaku.status.in_([DanmakuStatus.PENDING.value, DanmakuStatus.VERIFIED.value]))
                    )
                    .count()
            )

        except Exception as e:
            logger.error(f"查重失败: {e}", exc_info=True)
            return 0

    def query_history(self, keyword: str = "", status: int = -1, limit: int = 500) -> list[dict]:
        """按关键词与状态筛选弹幕历史。

        Args:
            keyword (str): 消息关键词，空串表示不筛。
            status (int): 核销状态，-1 表示不筛。
            limit (int): 返回条数上限。

        Returns:
            list[dict]: 数据库原始记录，由 UI 层结合 API 数据展示。
        """
        try:
            query = SentDanmaku.select()

            if keyword:
                query = query.where(
                    (SentDanmaku.msg.contains(keyword)) |
                    (SentDanmaku.bvid.contains(keyword))
                )

            if status != -1:
                query = query.where(SentDanmaku.status == status)

            query = query.order_by(SentDanmaku.ctime.desc()).limit(limit)

            return list(query.dicts())  # type: ignore[return-value]

        except Exception as e:
            logger.error(f"查询历史记录失败: {e}", exc_info=True)
            return []
