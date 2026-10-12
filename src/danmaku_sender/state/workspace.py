"""会话工作区：队列与活动状态。"""
import time

from PySide6.QtCore import QObject, Signal

from .queue_state import QueueState


class WorkspaceState(QObject):
    """会话工作区。

    Attributes:
        queue_state: 发送任务队列。
        app_launch_time: 应用启动时间戳。
        stats_baseline: 监视统计基线时间戳，0 表示全量历史。
    """

    senderActiveChanged = Signal()
    monitorActiveChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        """初始化工作区状态。

        Args:
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.queue_state = QueueState(self)
        self.app_launch_time = time.time()
        self.stats_baseline: float = 0.0
        self._sender_is_active: bool = False
        self._monitor_is_active: bool = False

    @property
    def sender_is_active(self) -> bool:
        """发射器是否运行中。"""
        return self._sender_is_active

    @sender_is_active.setter
    def sender_is_active(self, value: bool) -> None:
        if self._sender_is_active != value:
            self._sender_is_active = value
            self.senderActiveChanged.emit()

    @property
    def monitor_is_active(self) -> bool:
        """监视器是否运行中。"""
        return self._monitor_is_active

    @monitor_is_active.setter
    def monitor_is_active(self, value: bool) -> None:
        if self._monitor_is_active != value:
            self._monitor_is_active = value
            self.monitorActiveChanged.emit()
