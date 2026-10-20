"""队列监视业务控制器"""

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, Settings
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.state import AppState

from .workers import QueueMonitorWorker

logger = logging.getLogger(__name__)


class MonitorController(QObject):
    """队列监视控制器：持有 QueueMonitorWorker，信号转发给 UI。

    本类在主线程运行，`stats_baseline` / `refresh_interval` 由这里取值
    并作为冻结参数交给 Worker——Worker 不持有任何 State，也不写 QueueState。
    """

    # cid 用 object 传：Qt 信号的 int 是 32 位，B 站新视频的 cid 会溢出绕回
    targetStatsUpdated = Signal(str, object, object)  # (bvid, cid, MonitorStats)
    targetVerifyFailed = Signal(str, object)          # (bvid, cid)
    overallStatsUpdated = Signal(object)           # MonitorStats
    statusUpdated = Signal(str)
    monitorFailed = Signal(str)                    # 异常终止
    monitorStarted = Signal()
    monitorFinished = Signal()
    monitorReady = Signal()

    def __init__(
        self,
        state: AppState,
        settings: Settings,
        history_manager: HistoryManager,
        parent=None,
    ):
        """初始化控制器。

        Args:
            state: 状态树聚合根，取活动会话与统计基线。
            settings: 配置容器，取监视参数与传输策略。
            history_manager: 本地账本。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.state = state
        self.settings = settings
        self.history_manager = history_manager
        self._worker: QueueMonitorWorker | None = None
        self._stop_event = threading.Event()

    def start_queue_monitor(
        self,
        send_done: threading.Event | None = None,
        post_send_watch_seconds: float = 300.0,
    ) -> bool:
        """启动队列监视 Worker。

        Args:
            send_done: 「发送+监视」时传入的发送结束标记；发送结束后再监视
                ``post_send_watch_seconds`` 自动停。传 None 表示独立监视，跑到手动停。
            post_send_watch_seconds: 发送结束后的继续监视时长（秒）。

        Returns:
            成功启动返回 True；拒绝启动返回 False。
        """
        if self.is_running():
            logger.warning("队列监视已在运行中。")
            return False

        if self._worker is not None:
            logger.warning("上一个监视 Worker 仍在清理中，稍后再试。")
            return False

        session = self.state.session
        auth = ApiAuthConfig(sessdata=session.sessdata, bili_jct=session.bili_jct)
        if not auth.sessdata:
            logger.warning("凭证缺失，无法启动队列监视。")
            return False

        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        baseline = float(self.state.workspace.stats_baseline)

        self._stop_event.clear()
        worker = QueueMonitorWorker(
            auth=auth,
            network=network,
            history_manager=self.history_manager,
            stop_event=self._stop_event,
            baseline=baseline,
            poll_interval=float(self.settings.monitor_config.refresh_interval),
            prevent_sleep=self.settings.global_config.prevent_sleep,
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
        self.state.workspace.monitor_is_active = True
        worker.start()
        self.monitorStarted.emit()
        logger.info(
            f"▶ 队列监视已启动：{len(self.state.workspace.queue_state.tasks)} 个任务，"
            f"轮询间隔 {self.settings.monitor_config.refresh_interval} 秒"
        )
        return True

    def stop_queue_monitor(self):
        """请求停止队列监视。"""
        if self.is_running():
            self._stop_event.set()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    @Slot(str, object, object)
    def _on_target_stats(self, bvid: str, cid: int, stats):
        self.targetStatsUpdated.emit(bvid, cid, stats)

    @Slot(str, object)
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
        self.state.workspace.monitor_is_active = False
        self.monitorReady.emit()
