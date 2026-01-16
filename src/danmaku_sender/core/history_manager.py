import logging
import sqlite3
import time
from pathlib import Path
from platformdirs import user_data_dir
from enum import IntEnum

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
    """
    def __init__(self):
        data_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR))
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / "history.db"
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def _init_db(self):
        """初始化数据库"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_danmaku (
                dmid TEXT PRIMARY KEY,
                cid INTEGER,
                bvid TEXT,
                content TEXT,
                progress INTEGER,
                send_time REAL,
                is_visible INTEGER,
                status INTEGER DEFAULT 0
            )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cid ON sent_danmaku (cid)')

        logger.debug(f"数据库初始化完成: {self.db_path}")

    def record_send(self, dmid: str, cid: int, bvid: str, content: str, progress: int, is_visible: bool):
        """
        [存证] 记录一条刚刚发送成功的弹幕。
        对应状态: STATUS_PENDING (0)
        """
        if not dmid:
            logger.warning("尝试记录弹幕但 dmid 为空，操作跳过。")
            return
        
        try:
            with self._get_conn() as conn:
                conn.execute('''
                    INSERT OR IGNORE INTO sent_danmaku (
                        dmid, cid, bvid, content, progress, send_time, is_visible, status
                    ) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(dmid),
                    cid,
                    bvid,
                    content,
                    progress,
                    time.time(),
                    1 if is_visible else 0,
                    DanmakuStatus.PENDING.value
                ))
            logger.debug(f"弹幕入库: {content[:10]}... [dmid:{dmid}]")
        except Exception as e:
            logger.error(f"记录弹幕历史失败: {e}", exc_info=True)

    def verify_dmids(self, verified_dmids: list[str]):
        """
        [核销] 监视器确认存活后，批量更新状态。
        将状态更新为: STATUS_VERIFIED (1)
        """
        if not verified_dmids:
            return
        
        try:
            with self._get_conn() as conn:
                placeholders = ','.join(['?'] * len(verified_dmids))
                sql = f"UPDATE sent_danmaku SET status = ? WHERE dmid IN ({placeholders})"
            
                conn.execute(sql, verified_dmids)

            logger.info(f"已核销(确认存活) {len(verified_dmids)} 条弹幕。")
        except Exception as e:
            logger.error(f"批量验证状态失败: {e}", exc_info=True)

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
                    logger.warning(f"标记了 {cursor.rowcount} 条弹幕为‘疑似丢失’。")
        except Exception as e:
            logger.error(f"标记丢失状态失败: {e}", exc_info=True)

    def get_pending_records(self, cid: int) -> list[dict]:
        """获取 Pending 弹幕"""
        try:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    'SELECT dmid, content, progress, send_time FROM sent_danmaku WHERE cid = ? AND status = ?', 
                    (cid, DanmakuStatus.PENDING.value)
                )
                return [
                    {"dmid": row[0], "content": row[1], "progress": row[2], "send_time": row[3]}
                    for row in cursor.fetchall()
                ]

        except Exception as e:
            logger.error(f"查询 Pending 记录失败: {e}")
            return []
    
    def get_stats(self, cid: int) -> tuple[int, int, int]:
        """
        获取统计数据 (UI使用)。
        """
        try:
            with self._get_conn() as conn:
                cursor = conn.execute('''
                    SELECT 
                        COUNT(*),
                        SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END),
                        SUM(CASE WHEN status = 2 THEN 1 ELSE 0 END)
                    FROM sent_danmaku 
                    WHERE cid = ?
                ''', (cid,))
                
                row = cursor.fetchone()
                if row:
                    return (row[0] or 0, row[1] or 0, row[2] or 0)
        except Exception as e:
            logger.error(f"获取统计失败: {e}")
            
        return 0, 0, 0