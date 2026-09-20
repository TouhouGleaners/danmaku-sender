import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState

from .workers import QueueMonitorWorker

logger = logging.getLogger(__name__)


class MonitorController(QObject):
    """队列监视控制器：持有 QueueMonitorWorker，信号转发给 UI。

    QueueState 只读；核销与统计查询在 Worker 线程执行。
    """

    taskStatsUpdated = Signal(str, object)   # (task_id, MonitorStats)
    overallStatsUpdated = Signal(object)     # MonitorStats
    statusUpdated = Signal(str)
    monitorFinished = Signal()
    monitorReady = Signal()

    def __init__(self, state: AppState, history_manager: HistoryManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.history_manager = history_manager
        self._worker: QueueMonitorWorker | None = None
        self._stop_event = threading.Event()

    def start_queue_monitor(self, auth_config: ApiAuthConfig | None = None):
        """启动队列监视 Worker。"""
        if self.is_running():
            logger.warning("队列监视已在运行中。")
            return

        if auth_config is None:
            auth_config = self.state.get_api_auth()
        if not auth_config.sessdata:
            logger.warning("凭证缺失，无法启动队列监视。")
            return
        if not self.state.queue_state.tasks:
            logger.warning("队列为空，没有任务可以监视。")
            return

        self._stop_event.clear()
        self._worker = QueueMonitorWorker(
            state=self.state,
            auth_config=auth_config,
            history_manager=self.history_manager,
            stop_event=self._stop_event,
        )

        self._worker.taskStatsUpdated.connect(self._on_task_stats)
        self._worker.overallStatsUpdated.connect(self._on_overall_stats)
        self._worker.statusUpdated.connect(self._on_status)
        self._worker.monitorFinished.connect(self._on_monitor_finished)
        self._worker.finished.connect(self._on_worker_cleanup)
        self._worker.finished.connect(self._worker.deleteLater)

        self.state.monitor_is_active = True
        self._worker.start()
        logger.info(
            f"▶ 队列监视已启动：{len(self.state.queue_state.tasks)} 个任务，"
            f"轮询间隔 {self.state.monitor_config.refresh_interval} 秒"
        )

    def stop_queue_monitor(self):
        """请求停止队列监视。"""
        if self.is_running():
            self._stop_event.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @Slot(str, object)
    def _on_task_stats(self, task_id: str, stats):
        self.taskStatsUpdated.emit(task_id, stats)

    @Slot(object)
    def _on_overall_stats(self, stats):
        self.overallStatsUpdated.emit(stats)

    @Slot(str)
    def _on_status(self, message: str):
        self.statusUpdated.emit(message)

    @Slot()
    def _on_monitor_finished(self):
        self.monitorFinished.emit()

    @Slot()
    def _on_worker_cleanup(self):
        if self._worker is not None:
            logger.debug("QueueMonitorWorker 线程生命周期结束，正在清理控制器引用。")
            self._worker = None
        self.state.monitor_is_active = False
        self.monitorReady.emit()
