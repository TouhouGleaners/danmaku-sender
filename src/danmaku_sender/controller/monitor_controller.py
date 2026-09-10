import logging
import random
import threading
import time

from PySide6.QtCore import QObject, Signal, Slot

from .concurrency import PoolTask, WorkerThread

from danmaku_sender.runtime.infra.platform import KeepSystemAwake
from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.config import ApiAuthConfig, MonitorConfig
from danmaku_sender.service.bili_monitor import BiliDanmakuMonitor
from danmaku_sender.service.danmaku_verifier import DanmakuVerifier


logger = logging.getLogger(__name__)


class MonitorController(QObject):
    """监视任务业务控制器"""
    statsUpdated = Signal(dict)
    statusUpdated = Signal(str)
    taskFinished = Signal()
    queueVerifyFinished = Signal()  # 一轮后台在线核销结束（无论成败）

    def __init__(self, history_manager: HistoryManager, parent=None):
        super().__init__(parent)
        self.history_manager = history_manager
        self._worker: MonitorTaskWorker | None = None
        self._stop_event = threading.Event()
        self._verify_in_flight = False

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
            stop_event=self._stop_event,
            history_manager=self.history_manager,
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

    # region 队列在线核销

    def verify_queue_online(self, cid_labels: list[tuple[int, str]], auth_config: ApiAuthConfig):
        """后台核销队列分P：PoolTask 中拉取在线名单并核销存活，完成后发 queueVerifyFinished。

        网络请求不进 UI 线程；同一时间只允许一个核销批次在途，重复调用会被忽略。
        Args:
            cid_labels: [(cid, 日志前缀)]，前缀形如 "P1 - 序章"
        """
        if self._verify_in_flight or not cid_labels:
            return

        self._verify_in_flight = True
        PoolTask.submit(
            self._verify_blocking,
            self._on_verify_done,
            self._on_verify_done,
            cid_labels, auth_config,
        )

    def _verify_blocking(self, cid_labels: list[tuple[int, str]], auth_config: ApiAuthConfig):
        logger.info(f"🔍 在线核销开始，共 {len(cid_labels)} 个分P。")
        with BiliApiClient.from_config(auth_config) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)
            for i, (cid, label) in enumerate(cid_labels):
                try:
                    result = verifier.verify_cid(cid, mark_lost=False)
                    logger.info(
                        f"[{label}] 对账完成: 核销 {result['verified']} 条，在线共 {result['total_checked']} 条。"
                    )
                except Exception as e:
                    logger.warning(f"[{label}] 在线核销失败，跳过: {e}")

                if i + 1 < len(cid_labels):
                    # 逐 CID 安全间隔，避免连发请求触发风控
                    time.sleep(random.uniform(1.0, 3.0))
        logger.info("✅ 本轮在线核销结束。")

    @Slot(object)
    def _on_verify_done(self, _result=None):
        """核销批次结束（无论成败）：恢复可发起状态，并通知页面刷新统计"""
        self._verify_in_flight = False
        self.queueVerifyFinished.emit()

    # endregion

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


class MonitorTaskWorker(WorkerThread):
    """监视任务后台线程"""
    statsUpdated = Signal(dict)
    statusUpdated = Signal(str)
    taskFinished = Signal()

    def __init__(
        self,
        target: VideoTarget,
        auth_config: ApiAuthConfig,
        monitor_config: MonitorConfig,
        stop_event: threading.Event,
        history_manager: HistoryManager,
        parent=None
    ):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.target = target
        self.auth_config = auth_config
        self.monitor_config = monitor_config
        self.stop_event = stop_event
        self.history_manager = history_manager

    def run(self):
        try:
            self._run_monitor_loop()
        except Exception as e:
            self.report_error("监视任务异常", e)
        finally:
            self.taskFinished.emit()

    def _run_monitor_loop(self):
        with (
            KeepSystemAwake(self.monitor_config.prevent_sleep),
            BiliApiClient.from_config(self.auth_config) as client
        ):
            # 由 Worker 管理 BiliApiClient 生命周期，注入给 Monitor
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)
            monitor = BiliDanmakuMonitor(verifier=verifier, target=self.target, history_manager=self.history_manager)

            self.logger.info(f"🛡️ 监视启动: {self.target.display_string} | CID: {self.target.cid}")

            while not self.stop_event.is_set():
                self._execute_single_check(monitor)
                if self.stop_event.wait(self.monitor_config.refresh_interval):
                    self.logger.info("收到停止信号，监视任务终止。")
                    break

    def _execute_single_check(self, monitor: BiliDanmakuMonitor):
        snap_baseline = self.monitor_config.stats_baseline
        stats = monitor.monitor(stats_baseline=snap_baseline)

        self.statsUpdated.emit(stats)
        self.statusUpdated.emit(f"监视中 (存活: {stats['verified']})")

        msg = (
            f"监视中... 总计:{stats['total']} | "
            f"✅存活:{stats['verified']} | "
            f"⏳待验:{stats['pending']}"
        )
        if stats.get('lost', 0) > 0:
            msg += f" | ❌丢失:{stats['lost']}"

        self.logger.info(msg)