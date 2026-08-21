import logging

from PySide6.QtCore import QObject, Signal

from .concurrency import PoolTask

from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.service.bili_monitor import BiliDanmakuMonitor
from danmaku_sender.config import ApiAuthConfig


logger = logging.getLogger(__name__)


class HistoryController(QObject):
    """历史记录业务控制器"""
    historyFetched = Signal(list)
    verifyCompleted = Signal(dict)
    errorOccurred = Signal(object)

    def __init__(self, history_manager: HistoryManager, parent=None):
        super().__init__(parent)
        self.history_manager = history_manager

    def query(self, keyword: str, status_filter: int):
        """发起异步数据库查询"""
        PoolTask.submit(
            self.history_manager.query_history,
            self.historyFetched.emit,
            self.errorOccurred.emit,
            keyword, status_filter,
        )

    def verify_records(self, cid: int, auth_config: ApiAuthConfig):
        """发起异步弹幕验证（单个分P）"""
        PoolTask.submit(
            BiliDanmakuMonitor.verify_by_cid,
            self.verifyCompleted.emit,
            self.errorOccurred.emit,
            cid, auth_config, self.history_manager,
        )

    def verify_all(self, auth_config: ApiAuthConfig):
        """发起异步批量验证（所有待验证记录）"""
        PoolTask.submit(
            BiliDanmakuMonitor.verify_all_pending,
            self.verifyCompleted.emit,
            self.errorOccurred.emit,
            auth_config, self.history_manager,
        )