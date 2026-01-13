import logging
import sqlite3
import time
from pathlib import Path
from platformdirs import user_data_dir

from ..config.app_config import AppInfo


logger = logging.getLogger("HistoryManager")


STATUS_PENDING = 0   # 待验证
STATUS_VERIFIED = 1  # 已存活
STATUS_LOST = 2      # 已丢失


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
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_danmakus (
                dmid TEXT PRIMARY KEY,
                cid INTEGER,
                bvid TEXT,
                content TEXT,
                progress INTEGER,
                send_time REAL,
                is_visible INTEGER
                status INTEGER DEFAULT 0
            )
        ''')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_cid ON sent_danmakus (cid)')

        conn.commit()
        conn.close()
        logger.debug(f"数据库初始化完成: {self.db_path}")

    def record_send(self, dmid: str, cid: int, bvid: str, content: str, progress: int, is_visible: bool):
        """
        [存证] 记录一条刚刚发送成功的弹幕。
        对应状态: STATUS_PENDING (0)
        """
        if not dmid:
            logger.warning("尝试记录弹幕但 dmid 为空，操作跳过。")
            return
        
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO sent_danmakus (
                    dmid, cid, bvid, content, progress, send_time, is_visible, status
                ) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                dmid,
                cid,
                bvid,
                content,
                progress,
                time.time(),
                1 if is_visible else 0,
                STATUS_PENDING
            ))
            conn.commit()
            logger.debug(f"弹幕入库: {content[:10]}... [dmid:{dmid}]")
        except Exception as e:
            logger.error(f"记录弹幕历史失败: {e}", exc_info=True)
        finally:
            conn.close()

    def verify_dmids(self, verified_dmids: list[str]):
        """
        [核销] 监视器确认存活后，批量更新状态。
        将状态更新为: STATUS_VERIFIED (1)
        """
        if not verified_dmids:
            return
        
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            placeholders = ','.join(['?'] * len(verified_dmids))
            sql = f"UPDATE sent_danmakus SET status = {STATUS_VERIFIED} WHERE dmid IN ({placeholders})"
            
            cursor.execute(sql, verified_dmids)
            conn.commit()
            logger.info(f"已核销(确认存活) {cursor.rowcount} 条弹幕。")
        except Exception as e:
            logger.error(f"批量验证状态失败: {e}", exc_info=True)
        finally:
            conn.close()

    def mark_as_lost(self, cid: int, verified_dmids: list[str]):
        """
        [核销] 标记丢失。
        逻辑：在该 CID 下，所有状态为 PENDING 且 不在 verified_dmids 列表中的弹幕，标记为 LOST。
        """
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            
            if verified_dmids:
                placeholders = ','.join(['?'] * len(verified_dmids))
                # 标记状态为 Pending 且没被 Verify 的
                sql = f'''
                    UPDATE sent_danmakus
                    SET status = {STATUS_LOST}
                    WHERE cid = ?
                        AND status = {STATUS_PENDING}
                        AND dmid NOT IN ({placeholders})
                '''
                cursor.execute(sql, [cid] + verified_dmids)
            else:
                # 如果 verify 列表为空，说明该 CID 下所有 Pending 的都丢了
                sql = f'''
                    UPDATE sent_danmaku 
                    SET status = {STATUS_LOST} 
                    WHERE cid = ? AND status = {STATUS_PENDING}
                '''
                cursor.execute(sql, (cid,))

            if cursor.rowcount > 0:
                logger.warning(f"标记了 {cursor.rowcount} 条弹幕为‘疑似丢失’。")
            conn.commit()
        except Exception as e:
            logger.error(f"标记丢失状态失败: {e}", exc_info=True)
        finally:
            conn.close()

    def get_pending_records(self, cid: int) -> list[dict]:
        """获取某分P下所有待验证 (Pending) 的弹幕"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT dmid, content, progress, send_time 
            FROM sent_danmaku 
            WHERE cid = ? AND status = {STATUS_PENDING}
        ''', (cid,))
        rows = cursor.fetchall()
        conn.close()

        return [
            {"dmid": row[0], "content": row[1], "progress": row[2], "send_time": row[3]}
            for row in rows
        ]
    
    def get_status(self, cid: int) -> tuple[int, int, int]:
        """
        获取统计数据 (UI使用)。
        Returns:
            (total_sent, verified_count, lost_count)
            注意：total_sent = pending + verified + lost
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN status = 2 THEN 1 ELSE 0 END) as lost
            FROM sent_danmaku 
            WHERE cid = ?
        ''', (cid,))

        row = cursor.fetchone()
        conn.close()
        
        if row:
            total = row[0] or 0
            verified = row[1] or 0
            lost = row[2] or 0
            return total, verified, lost
        return 0, 0, 0