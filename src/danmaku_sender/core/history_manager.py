import logging
import sqlite3
import time
import threading
from pathlib import Path
from platformdirs import user_data_dir
from enum import IntEnum

from .models.danmaku import Danmaku
from .models.structs import VideoTarget

from ..config.app_config import AppInfo


logger = logging.getLogger("HistoryManager")


class DanmakuStatus(IntEnum):
    PENDING = 0   # 待验证
    VERIFIED = 1  # 已存活
    LOST = 2      # 已丢失


class HistoryManager:
    """
    基于 SQLite 的弹幕生命周期管理系统。
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

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def _init_db(self):
        """初始化数据库"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sent_danmaku (
                        dmid TEXT PRIMARY KEY,
                        cid INTEGER,
                        bvid TEXT,
                        msg TEXT,
                        progress INTEGER,
                        mode INTEGER,
                        fontsize INTEGER,
                        color INTEGER,
                        ctime REAL,
                        is_visible INTEGER,
                        status INTEGER DEFAULT 0
                    )
                ''')

                cursor.execute('CREATE INDEX IF NOT EXISTS idx_cid_status ON sent_danmaku (cid, status)')
            logger.debug(f"数据库初始化完成: {self.db_path}")

        except Exception as e:
            logger.critical(f"数据库初始化致命错误: {e}", exc_info=True)
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
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT OR IGNORE INTO sent_danmaku (
                        dmid, cid, bvid, msg, progress, mode,
                        fontsize, color, ctime, is_visible, status
                    ) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(dm.dmid),
                    target.cid,
                    target.bvid,
                    dm.msg,
                    dm.progress,
                    dm.mode,
                    dm.fontsize,
                    dm.color,
                    time.time(),
                    1 if is_visible_api else 0,
                    DanmakuStatus.PENDING.value
                ))
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
            with self._get_conn() as conn:
                placeholders = ','.join(['?'] * len(verified_dmids))
                sql = f'''
                    UPDATE sent_danmaku 
                    SET status = ? 
                    WHERE dmid IN ({placeholders}) AND status = ?
                '''

                params = [DanmakuStatus.VERIFIED.value] + verified_dmids + [DanmakuStatus.PENDING.value]

                cursor = conn.execute(sql, params)
                return cursor.rowcount

        except Exception as e:
            logger.error(f"批量验证状态失败: {e}", exc_info=True)
            return 0

    def mark_as_lost(self, cid: int, verified_dmids: list[str]):
        """
        [核销] 标记丢失。
        逻辑：在该 CID 下，所有状态为 PENDING 且 不在 verified_dmids 列表中的弹幕，标记为 LOST。
        """
        try:
            with self._get_conn() as conn:
                if verified_dmids:
                    placeholders = ','.join(['?'] * len(verified_dmids))
                    sql = f'''
                        UPDATE sent_danmaku
                        SET status = ?
                        WHERE cid = ?
                            AND status = ?
                            AND dmid NOT IN ({placeholders})
                    '''
                    params = [DanmakuStatus.LOST.value, cid, DanmakuStatus.PENDING.value] + verified_dmids
                    cursor = conn.execute(sql, params)
                else:
                    sql = 'UPDATE sent_danmaku SET status = ? WHERE cid = ? AND status = ?'
                    params = [DanmakuStatus.LOST.value, cid, DanmakuStatus.PENDING.value]
                    cursor = conn.execute(sql, params)

                if cursor.rowcount > 0:
                    logger.warning(f"标记了 {cursor.rowcount} 条弹幕为'疑似丢失'。")

        except Exception as e:
            logger.error(f"标记丢失状态失败: {e}", exc_info=True)

    def get_pending_records(self, cid: int) -> list[dict]:
        """获取 Pending 弹幕"""
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    'SELECT dmid, msg, progress, ctime FROM sent_danmaku WHERE cid = ? AND status = ?', 
                    (cid, DanmakuStatus.PENDING.value)
                )
                return [
                    {"dmid": row[0], "msg": row[1], "progress": row[2], "ctime": row[3]}
                    for row in cursor.fetchall()
                ]

        except Exception as e:
            logger.error(f"查询 Pending 记录失败: {e}", exc_info=True)
            return []

    def get_stats(self, cid: int) -> tuple[int, int, int]:
        """
        获取统计数据 (UI使用)。
        """
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(f'''
                    SELECT 
                        COUNT(*),
                        SUM(CASE WHEN status = {DanmakuStatus.VERIFIED.value} THEN 1 ELSE 0 END),
                        SUM(CASE WHEN status = {DanmakuStatus.LOST.value} THEN 1 ELSE 0 END)
                    FROM sent_danmaku 
                    WHERE cid = ?
                ''', (cid,))
                
                row = cursor.fetchone()
                if row:
                    return (row[0] or 0, row[1] or 0, row[2] or 0)
        except Exception as e:
            logger.error(f"获取统计失败: {e}")
            
        return 0, 0, 0
    
    def count_records(self, target: VideoTarget, dm: Danmaku) -> int:
        """
        统计数据库中与传入弹幕完全匹配的记录数量，
        用于断点续传的计数对账
        """
        try:
            with self._get_conn() as conn:
                sql = '''
                    SELECT COUNT(*) FROM sent_danmaku
                    WHERE cid = ?
                    AND msg = ?
                    AND mode = ?
                    AND color = ?
                    AND fontsize = ?
                    AND progress = ?
                    AND status IN (?, ?)  -- 只统计 PENDING(0) 和 VERIFIED(1)
                '''
                params = (
                    target.cid,
                    dm.msg,
                    dm.mode,
                    dm.color,
                    dm.fontsize,
                    dm.progress,
                    DanmakuStatus.PENDING.value,
                    DanmakuStatus.VERIFIED.value
                )

                cursor = conn.execute(sql, params)
                return cursor.fetchone()[0]
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
            with self._get_conn() as conn:
                sql = "SELECT dmid, cid, bvid, msg, progress, mode, fontsize, color, ctime, status, is_visible FROM sent_danmaku WHERE 1=1"
                params = []

                if keyword:
                    sql += " AND (msg LIKE ? OR bvid LIKE ?)"
                    params.extend([f"%{keyword}%", f"%{keyword}%"])

                if status != -1:
                    sql += " AND status = ?"
                    params.append(status)

                sql += " ORDER BY ctime DESC LIMIT ?"
                params.append(limit)

                cursor = conn.execute(sql, params)
                return [{
                    "dmid": row[0], "cid": row[1], "bvid": row[2], "msg": row[3],
                    "progress": row[4], "mode": row[5], "fontsize": row[6],
                    "color": row[7], "ctime": row[8], "status": row[9],
                    "is_visible": row[10]
                } for row in cursor.fetchall()]

        except Exception as e:
            logger.error(f"查询历史记录失败: {e}", exc_info=True)
            return []