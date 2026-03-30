import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from ..workers import MonitorTaskWorker
from ...core.models.structs import VideoTarget
from ...core.state import ApiAuthConfig, MonitorConfig


logger = logging.getLogger("App.System.MonitorController")


class MonitorController(QObject):
    """监视任务业务控制器"""
    statsUpdated = Signal(dict)
    statusUpdated = Signal(str)
    taskFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: MonitorTaskWorker | None = None
        self._stop_event = threading.Event()

    def start_task(self, target: VideoTarget, auth_config: ApiAuthConfig, monitor_config: MonitorConfig):
        """启动监视任务"""
        if self.is_running():
            logger.warning("任务已在运行中，无法重复启动。")
            return

        self._stop_event.clear()

        self._worker = MonitorTaskWorker(
            target=target,
            auth_config=auth_config,
            monitor_config=monitor_config,
            stop_event=self._stop_event
        )

        self._worker.statsUpdated.connect(self.statsUpdated.emit)
        self._worker.statusUpdated.connect(self.statusUpdated.emit)
        self._worker.taskFinished.connect(self._on_worker_finished)

        self._worker.finished.connect(self._on_worker_cleanup)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def stop_task(self):
        """停止监视任务"""
        if self.is_running():
            self._stop_event.set()

    def is_running(self) -> bool:
        """检查任务是否正在运行"""
        return self._worker is not None and self._worker.isRunning()


    # region Slots

    @Slot()
    def _on_worker_finished(self):
        """处理任务结束清理并向上传递"""
        self.taskFinished.emit()

    @Slot()
    def _on_worker_cleanup(self):
        """垃圾回收机制"""
        if self._worker is not None:
            logger.debug("MonitorTaskWorker 线程生命周期结束，正在清理控制器引用。")
            self._worker = None

    # endregion