"""队列监视业务控制器"""

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState

from .workers import MONITORABLE_STATUSES, QueueMonitorWorker

logger = logging.getLogger(__name__)


class MonitorController(QObject):
    """队列监视控制器：持有 QueueMonitorWorker，信号转发给 UI。

    QueueState 只读；核销与统计查询在 Worker 线程执行。
    """

    taskStatsUpdated = Signal(str, object)   # (task_id, MonitorStats)
    taskVerifyFailed = Signal(str)           # task_id
    overallStatsUpdated = Signal(object)     # MonitorStats
    statusUpdated = Signal(str)
    monitorFailed = Signal(str)              # 异常终止
    monitorFinished = Signal()
    monitorReady = Signal()

    def __init__(self, state: AppState, history_manager: HistoryManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.history_manager = history_manager
        self._worker: QueueMonitorWorker | None = None
        self._stop_event = threading.Event()

    def start_queue_monitor(self, auth_config: ApiAuthConfig | None = None) -> bool:
        """启动队列监视 Worker。成功返回 True；拒绝启动返回 False。"""
        if self.is_running():
            logger.warning("队列监视已在运行中。")
            return False

        if self._worker is not None:
            logger.warning("上一个监视 Worker 仍在清理中，稍后再试。")
            return False

        if auth_config is None:
            auth_config = self.state.get_api_auth()

        if not auth_config.sessdata:
            logger.warning("凭证缺失，无法启动队列监视。")
            return False

        if not self.state.queue_state.tasks:
            logger.warning("队列为空，没有任务可以监视。")
            return False
        if not self.state.queue_state.sample_task_fields(set(MONITORABLE_STATUSES)):
            logger.warning(
                "队列中没有可监视的任务（需要已完成/发送中/失败/暂停的任务）。"
            )
            return False

        self._stop_event.clear()
        worker = QueueMonitorWorker(
            state=self.state,
            auth_config=auth_config,
            history_manager=self.history_manager,
            stop_event=self._stop_event,
        )

        worker.taskStatsUpdated.connect(self._on_task_stats)
        worker.taskVerifyFailed.connect(self._on_task_verify_failed)
        worker.overallStatsUpdated.connect(self._on_overall_stats)
        worker.statusUpdated.connect(self._on_status)
        worker.monitorFailed.connect(self._on_monitor_failed)
        worker.monitorFinished.connect(self._on_monitor_finished)
        # ending 携带 worker 实例；槽在 Controller（主线程）执行
        worker.ending.connect(self._on_worker_discard)
        worker.finished.connect(worker.deleteLater)

        self._worker = worker
        self.state.monitor_is_active = True
        worker.start()
        logger.info(
            f"▶ 队列监视已启动：{len(self.state.queue_state.tasks)} 个任务，"
            f"轮询间隔 {self.state.monitor_config.refresh_interval} 秒"
        )
        return True

    def stop_queue_monitor(self):
        """请求停止队列监视。"""
        if self.is_running():
            self._stop_event.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @Slot(str, object)
    def _on_task_stats(self, task_id: str, stats):
        self.taskStatsUpdated.emit(task_id, stats)

    @Slot(str)
    def _on_task_verify_failed(self, task_id: str):
        self.taskVerifyFailed.emit(task_id)

    @Slot(object)
    def _on_overall_stats(self, stats):
        self.overallStatsUpdated.emit(stats)

    @Slot(str)
    def _on_status(self, message: str):
        self.statusUpdated.emit(message)

    @Slot(str)
    def _on_monitor_failed(self, error_msg: str):
        logger.error(f"队列监视异常终止: {error_msg}")
        self.monitorFailed.emit(error_msg)

    @Slot()
    def _on_monitor_finished(self):
        self.monitorFinished.emit()

    @Slot(object)
    def _on_worker_discard(self, worker: QueueMonitorWorker):
        """主线程清理：仅当仍是当前 _worker 时释放引用。"""
        if worker is not self._worker:
            return

        logger.debug("QueueMonitorWorker 线程生命周期结束，正在清理控制器引用。")
        self._worker = None
        self.state.monitor_is_active = False
        self.monitorReady.emit()
