"""发送任务业务控制器"""

import logging
import threading
from enum import Enum
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from .workers import QueueWorker

from danmaku_sender.controller.concurrency import PoolTask
from danmaku_sender.service.danmaku_exporter import create_xml_from_danmakus
from danmaku_sender.types.models.common import UnsentDanmakusRecord
from danmaku_sender.types.models.queue import TaskStatus
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.runtime.state.queue_state import QueueState


logger = logging.getLogger(__name__)


class SenderStatus(Enum):
    """发送校验状态"""
    READY = "ready"
    NOT_READY = "not_ready"
    NO_CREDENTIALS = "no_credentials"


class SenderController(QObject):
    """发送任务业务控制器"""
    # 队列信号
    queueTaskStarted = Signal(str)                      # task_id
    queueTaskCompleted = Signal(str, object)            # (task_id, SendingContext)
    queueTaskFailed = Signal(str, str)                  # (task_id, error_msg)
    queueFinished = Signal()
    queueReady = Signal()                               # Worker 清理完毕，可重新启动
    queueProgressUpdated = Signal(int, int, float)      # (current_idx_0based, total, eta)
    taskProgressUpdated = Signal(str, int, int, float)  # (task_id, attempted, task_total, eta)

    def __init__(self, state: AppState, history_manager: HistoryManager, parent=None):
        super().__init__(parent)
        self.state = state
        self.history_manager = history_manager
        self._queue_worker: QueueWorker | None = None
        self._stop_event = threading.Event()

    @property
    def send_status(self) -> SenderStatus:
        """当前发送状态，READY 表示队列可以启动。"""
        if not self.state.sessdata or not self.state.bili_jct:
            return SenderStatus.NO_CREDENTIALS
        if self.state.queue_state.pending_count == 0:
            return SenderStatus.NOT_READY
        return SenderStatus.READY

    # region Queue

    def start_queue(self, queue_state: QueueState, auth_config: ApiAuthConfig, reset_failed: bool = False):
        """启动队列发送。

        Args:
            reset_failed: 是否重置之前失败/跳过的任务。默认 False，只重置残留的 RUNNING 状态。
        """
        if self.is_queue_running():
            logger.warning("任务已在运行中，无法启动队列。")
            return

        # 重置残留状态
        resettable = {TaskStatus.RUNNING, TaskStatus.PAUSED}
        if reset_failed:
            resettable |= {TaskStatus.FAILED, TaskStatus.SKIPPED}

        for task in queue_state.tasks:
            if task.status in resettable:
                queue_state.update_task_status(task.task_id, TaskStatus.PENDING)
        queue_state.current_index = -1

        if queue_state.pending_count == 0:
            logger.warning("队列中没有待发送的任务。")
            return

        self._stop_event.clear()

        self._queue_worker = QueueWorker(
            queue_state=queue_state,
            auth_config=auth_config,
            sender_config=self.state.sender_config,
            history_manager=self.history_manager,
            stop_event=self._stop_event,
        )

        self._queue_worker.taskStarted.connect(self.queueTaskStarted.emit)
        self._queue_worker.taskCompleted.connect(self.queueTaskCompleted.emit)
        self._queue_worker.taskFailed.connect(self.queueTaskFailed.emit)
        self._queue_worker.queueFinished.connect(self._on_queue_finished)
        self._queue_worker.queueProgressUpdated.connect(self.queueProgressUpdated.emit)
        self._queue_worker.taskProgressUpdated.connect(self._on_task_progress)

        self._queue_worker.finished.connect(self._on_queue_cleanup)
        self._queue_worker.finished.connect(self._queue_worker.deleteLater)
        self._queue_worker.start()

        # 标记队列运行状态
        self.state.sender_is_active = True

    def stop_queue(self):
        """停止队列发送"""
        if self.is_queue_running():
            self._stop_event.set()

    def is_queue_running(self) -> bool:
        """检查队列是否正在运行"""
        return self._queue_worker is not None and self._queue_worker.isRunning()

    @Slot()
    def _on_queue_finished(self):
        """队列执行完毕"""
        self.queueFinished.emit()

    @Slot(str, int, int, float)
    def _on_task_progress(self, task_id: str, attempted: int, task_total: int, eta: float):
        """转发单任务粒度进度"""
        self.taskProgressUpdated.emit(task_id, attempted, task_total, eta)

    @Slot()
    def _on_queue_cleanup(self):
        """队列 Worker 清理完毕，可安全重启"""
        if self._queue_worker is not None:
            logger.debug("QueueWorker 线程生命周期结束，正在清理控制器引用。")
            self._queue_worker = None
        self.state.sender_is_active = False
        self.queueReady.emit()

    # endregion

    def export_unsent_xml(
        self,
        unsent_danmakus: list[UnsentDanmakusRecord],
        file_path: str,
        on_success: Callable[[None], None],
        on_error: Callable[[str], None],
    ):
        """异步保存未发送弹幕到 XML 文件"""
        PoolTask.submit(
            create_xml_from_danmakus,
            on_success,
            lambda err: on_error(str(err)),
            unsent_danmakus, file_path,
        )
