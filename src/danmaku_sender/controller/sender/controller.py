"""发送任务业务控制器"""

import logging
import threading
from collections.abc import Callable
from enum import Enum

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.controller.concurrency import PoolTask
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.service.danmaku_exporter import create_xml_from_danmakus
from danmaku_sender.types.models.common import UnsentDanmakusRecord
from danmaku_sender.types.models.queue import TaskStatus

from .workers import QueueSendWorker

logger = logging.getLogger(__name__)


class SenderStatus(Enum):
    """发送校验状态"""
    READY = "ready"
    NOT_READY = "not_ready"
    NO_CREDENTIALS = "no_credentials"


class SenderController(QObject):
    """发送任务业务控制器

    持有 AppState；QueueState 只在本层（主线程 slot）变更，
    后台 QueueSendWorker 仅 emit 事件。
    """
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
        self._queue_worker: QueueSendWorker | None = None
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

    def start_queue(self, auth_config: ApiAuthConfig, reset_failed: bool = False):
        """启动队列发送。

        始终使用 AppState.queue_state；Worker 事件也只落账到该队列。

        Args:
            reset_failed: 是否重置之前失败/跳过的任务。默认 False，只重置残留的 RUNNING 状态。
        """
        if self.is_queue_running():
            logger.warning("任务已在运行中，无法启动队列。")
            return

        queue_state = self.state.queue_state
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

        # 主线程取快照交给 Worker；之后状态一律经 signal 回本类 slot 落账
        snapshot = queue_state.tasks
        self._queue_worker = QueueSendWorker(
            tasks=snapshot,
            auth_config=auth_config,
            sender_config=self.state.sender_config,
            history_manager=self.history_manager,
            stop_event=self._stop_event,
        )

        self._queue_worker.taskStarted.connect(self._on_task_started)
        self._queue_worker.taskCompleted.connect(self._on_task_completed)
        self._queue_worker.taskFailed.connect(self._on_task_failed)
        self._queue_worker.taskSkipped.connect(self._on_task_skipped)
        self._queue_worker.queueFinished.connect(self._on_queue_finished)
        self._queue_worker.queueProgressUpdated.connect(self.queueProgressUpdated.emit)
        self._queue_worker.taskProgressUpdated.connect(self._on_task_progress)

        self._queue_worker.finished.connect(self._on_queue_cleanup)
        self._queue_worker.finished.connect(self._queue_worker.deleteLater)

        # 先落下运行闸门，再启动线程，避免启动瞬间 UI 仍可结构编辑
        self.state.sender_is_active = True
        self._queue_worker.start()

    def stop_queue(self):
        """停止队列发送"""
        if self.is_queue_running():
            self._stop_event.set()

    def is_queue_running(self) -> bool:
        """检查队列是否正在运行"""
        return self._queue_worker is not None and self._queue_worker.isRunning()

    # endregion
    # region Worker slots（主线程落账 QueueState）

    @Slot(str, int)
    def _on_task_started(self, task_id: str, idx: int):
        self.state.queue_state.update_task_status(task_id, TaskStatus.RUNNING)
        self.state.queue_state.current_index = idx
        self.queueTaskStarted.emit(task_id)

    @Slot(str, object)
    def _on_task_completed(self, task_id: str, ctx):
        if (
            ctx is not None
            and getattr(ctx, "is_manually_stopped", False)
            and not getattr(ctx, "auto_stop_reason", "")
        ):
            self.state.queue_state.update_task_status(task_id, TaskStatus.PAUSED, "用户手动暂停")
        else:
            self.state.queue_state.update_task_status(task_id, TaskStatus.COMPLETED)
        self.queueTaskCompleted.emit(task_id, ctx)

    @Slot(str, str)
    def _on_task_failed(self, task_id: str, error_msg: str):
        self.state.queue_state.update_task_status(task_id, TaskStatus.FAILED, error_msg)
        self.queueTaskFailed.emit(task_id, error_msg)

    @Slot(str, str)
    def _on_task_skipped(self, task_id: str, reason: str):
        self.state.queue_state.update_task_status(task_id, TaskStatus.SKIPPED, reason)

    @Slot()
    def _on_queue_finished(self):
        self.state.queue_state.current_index = -1
        self.queueFinished.emit()

    @Slot(str, int, int, float)
    def _on_task_progress(self, task_id: str, attempted: int, task_total: int, eta: float):
        self.taskProgressUpdated.emit(task_id, attempted, task_total, eta)

    @Slot()
    def _on_queue_cleanup(self):
        if self._queue_worker is not None:
            logger.debug("QueueSendWorker 线程生命周期结束，正在清理控制器引用。")
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
