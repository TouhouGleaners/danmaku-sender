import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from ..workers import SendTaskWorker
from ...core.models.structs import VideoTarget
from ...core.models.danmaku import Danmaku
from ...core.state import ApiAuthConfig, SenderConfig


logger = logging.getLogger("App.System.SenderController")


class SenderController(QObject):
    """发送任务业务控制器"""
    progressUpdated = Signal(int, int)
    taskFinished = Signal(object)
    messageLogged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: SendTaskWorker | None = None
        self._stop_event = threading.Event()

    def start_task(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        auth_config: ApiAuthConfig,
        strategy_config: SenderConfig
    ):
        """启动发送任务"""
        if self.is_running():
            logger.warning("任务已在运行中，无法重复启动。")
            return

        self._stop_event.clear()

        self._worker = SendTaskWorker(
            target=target,
            danmakus=danmakus,
            auth_config=auth_config,
            strategy_config=strategy_config,
            stop_event=self._stop_event,
            parent=self
        )

        self._worker.progressUpdated.connect(self.progressUpdated.emit)
        self._worker.taskFinished.connect(self._on_worker_finished)
        self._worker.messageLogged.connect(self.messageLogged.emit)

        self._worker.finished.connect(self._on_worker_cleanup)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def stop_task(self):
        """停止发送任务"""
        if self.is_running():
            self._stop_event.set()

    def is_running(self) -> bool:
        """检查任务是否正在运行"""
        return self._worker is not None and self._worker.isRunning()

    def is_stopped_manually(self) -> bool:
        """检查任务是否被手动中断"""
        return self._stop_event.is_set()


    # region Slots

    @Slot(object)
    def _on_worker_finished(self, scheduler_instance):
        """内部槽函数：处理任务结束清理并向上传递"""
        self.taskFinished.emit(scheduler_instance)

    @Slot()
    def _on_worker_cleanup(self):
        """垃圾回收机制"""
        if self._worker is not None:
            logger.debug("SendTaskWorker 线程生命周期结束，正在清理控制器引用。")
            self._worker = None

    # endregion