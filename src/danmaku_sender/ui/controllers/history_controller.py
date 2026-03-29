import logging

from PySide6.QtCore import QObject, Signal, QThreadPool

from ..framework.concurrency import GenericTask
from ...core.database.history_manager import HistoryManager


logger = logging.getLogger("App.System.History")


def _query(keyword: str, status_filter: int) -> list:
    """纯业务逻辑：从单例的 HistoryManager 获取数据"""
    hm = HistoryManager()
    return hm.query_history(keyword, status_filter)


class HistoryController(QObject):
    """历史记录业务控制器"""
    historyFetched = Signal(list)
    errorOccurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def query(self, keyword: str, status_filter: int):
        """发起异步数据库查询"""
        task = GenericTask(_query, keyword, status_filter)

        # 绑定回调
        task.signals.result.connect(self.historyFetched.emit)
        task.signals.error.connect(self.errorOccurred.emit)

        # 提交到全局线程池
        QThreadPool.globalInstance().start(task)