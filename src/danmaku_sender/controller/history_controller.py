import logging

from PySide6.QtCore import QObject, Signal

from .concurrency import PoolTask

from danmaku_sender.repo.history_manager import HistoryManager


logger = logging.getLogger("App.Controller.History")


class HistoryController(QObject):
    """历史记录业务控制器"""
    historyFetched = Signal(list)
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