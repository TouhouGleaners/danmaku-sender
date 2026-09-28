"""队列监视业务控制器"""

import logging
import threading
from collections.abc import Collection

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState

from .workers import QueueMonitorWorker

logger = logging.getLogger(__name__)


class MonitorController(QObject):
    """队列监视控制器：持有 QueueMonitorWorker，信号转发给 UI。

    本类在主线程运行，`stats_baseline` / `refresh_interval` 由这里取值
    并作为冻结参数交给 Worker——Worker 不持有 AppState，也不写 QueueState。
    """

    targetStatsUpdated = Signal(str, int, object)  # (bvid, cid, MonitorStats)
    targetVerifyFailed = Signal(str, int)          # (bvid, cid)
    overallStatsUpdated = Signal(object)           # MonitorStats
    statusUpdated = Signal(str)
    monitorFailed = Signal(str)                    # 异常终止
    monitorFinished = Signal()
    monitorReady = Signal()

    def __init__(self, state: AppState, history_manager: HistoryManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.history_manager = history_manager
        self._worker: QueueMonitorWorker | None = None
        self._stop_event = threading.Event()

    def start_queue_monitor(
        self,
        recorded_targets: Collection[tuple[str, int]],
        auth_config: ApiAuthConfig | None = None,
        send_done: threading.Event | None = None,
        post_send_watch_seconds: float = 300.0,
    ) -> bool:
        """启动队列监视 Worker。成功返回 True；拒绝启动返回 False。

        Args:
            recorded_targets: 核销范围，调用方查好后传入，本方法不再查库。
                Worker 每轮仍自行重查，以纳入发送中新出现的目标。
            send_done: 「发送+监视」时传入的发送结束标记；发送结束后再监视
                ``post_send_watch_seconds`` 自动停。传 None 表示独立监视，跑到手动停。
        """
        if self.is_running():
            logger.warning("队列监视已在运行中。")
            return False

        if self._worker is not None:
            logger.warning("上一个监视 Worker 仍在清理中，稍后再试。")
            return False

        if not recorded_targets:
            logger.warning("核销范围为空，没有可监视的目标。")
            return False

        if auth_config is None:
            auth_config = self.state.get_api_auth()

        if not auth_config.sessdata:
            logger.warning("凭证缺失，无法启动队列监视。")
            return False

        baseline = float(self.state.stats_baseline)

        self._stop_event.clear()
        worker = QueueMonitorWorker(
            auth_config=auth_config,
            history_manager=self.history_manager,
            stop_event=self._stop_event,
            baseline=baseline,
            poll_interval=float(self.state.monitor_config.refresh_interval),
            prevent_sleep=self.state.global_config.prevent_sleep,
            send_done=send_done,
            post_send_watch_seconds=post_send_watch_seconds,
        )

        worker.targetStatsUpdated.connect(self._on_target_stats)
        worker.targetVerifyFailed.connect(self._on_target_verify_failed)
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
            f"▶ 队列监视已启动：{len(recorded_targets)} 个目标，"
            f"轮询间隔 {self.state.monitor_config.refresh_interval} 秒"
        )
        return True

    def stop_queue_monitor(self):
        """请求停止队列监视。"""
        if self.is_running():
            self._stop_event.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @Slot(str, int, object)
    def _on_target_stats(self, bvid: str, cid: int, stats):
        self.targetStatsUpdated.emit(bvid, cid, stats)

    @Slot(str, int)
    def _on_target_verify_failed(self, bvid: str, cid: int):
        self.targetVerifyFailed.emit(bvid, cid)

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
