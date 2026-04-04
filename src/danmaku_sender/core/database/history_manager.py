import logging
import time
import threading
from pathlib import Path
from platformdirs import user_data_dir
from enum import IntEnum

from peewee import SqliteDatabase, fn, Case
from playhouse.migrate import SqliteMigrator, migrate

from ..entities.danmaku import Danmaku
from .orm_models import db, SentDanmaku
from ..types.common import VideoTarget

from ...config.app_config import AppInfo


logger = logging.getLogger("App.System.DB")


class DanmakuStatus(IntEnum):
    PENDING = 0   # 待验证
    VERIFIED = 1  # 已存活
    LOST = 2      # 已丢失


class HistoryManager:
    """
    基于 Peewee ORM 的弹幕生命周期管理系统。
    负责实现“发送 -> 存证 -> 核销”的数据层逻辑。

    注意：当前的单例实现仅针对单进程多线程环境。
    如果在多进程环境中使用，SQLite 的文件锁机制会处理并发，但单例逻辑会失效。
    """
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(HistoryManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            data_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR))
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = data_dir / "history.db"
            self._init_db()

            HistoryManager._initialized = True
            logger.debug("HistoryManager 单例初始化完成")

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

            # 自动建表（已有则跳过）
            sqlite_db.create_tables([SentDanmaku], safe=True)

        except Exception as e:
            logger.critical(f"数据库初始化/迁移致命错误: {e}", exc_info=True)
            raise RuntimeError(f"HistoryManager 数据库初始化失败: {e}") from e

    def record_danmaku(self, target: VideoTarget, dm: Danmaku, is_visible_api: bool = True):
        """
        [存证] 记录一条刚刚发送成功的弹幕。
        对应状态: STATUS_PENDING (0)
        """
        if not dm.dmid:
            logger.warning("尝试记录无 ID 的弹幕，操作跳过。")
            return

        try:
            SentDanmaku.insert(
                dmid=str(dm.dmid),
                cid=target.cid,
                bvid=target.bvid,
                msg=dm.msg,
                progress=dm.progress,
                mode=dm.mode,
                fontsize=dm.fontsize,
                color=dm.color,
                ctime=time.time(),
                is_visible=1 if is_visible_api else 0,
                status=DanmakuStatus.PENDING.value
            ).on_conflict_ignore().execute()
        except Exception as e:
            logger.error(f"存证失败: {e}", exc_info=True)

    def verify_dmids(self, verified_dmids: list[str]) -> int:
        """
        [核销] 监视器确认存活后，批量更新状态。
        将状态更新为: STATUS_VERIFIED (1)
        """
        if not verified_dmids:
            return 0

        try:
            query = SentDanmaku.update(status=DanmakuStatus.VERIFIED.value).where(
                (SentDanmaku.dmid.in_(verified_dmids)) &
                (SentDanmaku.status == DanmakuStatus.PENDING.value)
            )
            return query.execute()

        except Exception as e:
            logger.error(f"批量验证状态失败: {e}", exc_info=True)
            return 0

    def mark_as_lost(self, cid: int, verified_dmids: list[str]):
        """
        [核销] 标记丢失。
        逻辑：在该 CID 下，所有状态为 PENDING 且 不在 verified_dmids 列表中的弹幕，标记为 LOST。
        """
        try:
            condition = (SentDanmaku.cid == cid) & (SentDanmaku.status == DanmakuStatus.PENDING.value)

            if verified_dmids:
                condition &= SentDanmaku.dmid.not_in(verified_dmids)

            query = SentDanmaku.update(status=DanmakuStatus.LOST.value).where(condition)
            rows_updated = query.execute()

            if rows_updated > 0:
                logger.warning(f"标记了 {rows_updated} 条弹幕为'疑似丢失'。")

        except Exception as e:
            logger.error(f"标记丢失状态失败: {e}", exc_info=True)

    def get_pending_records(self, cid: int) -> list[dict]:
        """获取 Pending 弹幕"""
        try:
            return list(
                SentDanmaku.select(
                    SentDanmaku.dmid, SentDanmaku.msg, SentDanmaku.progress, SentDanmaku.ctime
                ).where(
                    (SentDanmaku.cid == cid) &
                    (SentDanmaku.status == DanmakuStatus.PENDING.value)
                ).dicts()
            )

        except Exception as e:
            logger.error(f"查询 Pending 记录失败: {e}", exc_info=True)
            return []

    def get_stats(self, cid: int, stats_baseline: float = 0.0) -> tuple[int, int, int]:
        """获取统计数据 (UI使用)"""
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

    def count_records(self, target: VideoTarget, dm: Danmaku) -> int:
        """
        统计数据库中与传入弹幕完全匹配的记录数量，
        用于断点续传的计数对账
        """
        try:
            return SentDanmaku.select().where(
                (SentDanmaku.cid == target.cid) &
                (SentDanmaku.msg == dm.msg) &
                (SentDanmaku.mode == dm.mode) &
                (SentDanmaku.color == dm.color) &
                (SentDanmaku.fontsize == dm.fontsize) &
                (SentDanmaku.progress == dm.progress) &
                (SentDanmaku.status.in_([DanmakuStatus.PENDING.value, DanmakuStatus.VERIFIED.value]))
            ).count()

        except Exception as e:
            logger.error(f"查重失败: {e}", exc_info=True)
            return 0

    def query_history(self, keyword: str = "", status: int = -1, limit: int = 500) -> list[dict]:
        """
        查询接口

        支持关键词和状态筛选
        返回数据库原始 dict，后续 UI 层会结合 API 数据进行展示
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

            return list(query.dicts())

        except Exception as e:
            logger.error(f"查询历史记录失败: {e}", exc_info=True)
            return []