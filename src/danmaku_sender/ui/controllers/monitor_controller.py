import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from ..framework.concurrency import BaseWorker

from ...core.types.common import VideoTarget
from ...core.state import ApiAuthConfig, MonitorConfig
from ...core.engines.bili_monitor import BiliDanmakuMonitor
from ...api.bili_api_client import BiliApiClient
from ...utils.system_utils import KeepSystemAwake


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


class MonitorTaskWorker(BaseWorker):
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
        parent=None
    ):
        super().__init__(parent)
        self.logger = logging.getLogger("App.Monitor.Worker")
        self.target = target
        self.auth_config = auth_config
        self.monitor_config = monitor_config
        self.stop_event = stop_event

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
            monitor = BiliDanmakuMonitor(api_client=client, target=self.target)
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