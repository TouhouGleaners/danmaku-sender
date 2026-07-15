import logging

from PySide6.QtCore import QObject, Signal

from danmaku_sender.ui.framework.concurrency import PoolTask
from danmaku_sender.repo.history_manager import HistoryManager


logger = logging.getLogger("App.System.History")


def _query(keyword: str, status_filter: int) -> list:
    """纯业务逻辑：从单例的 HistoryManager 获取数据"""
    hm = HistoryManager()
    return hm.query_history(keyword, status_filter)


class HistoryController(QObject):
    """历史记录业务控制器"""
    historyFetched = Signal(list)
    errorOccurred = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

    def query(self, keyword: str, status_filter: int):
        """发起异步数据库查询"""
        PoolTask.submit(_query, self.historyFetched.emit, self.errorOccurred.emit, keyword, status_filter)