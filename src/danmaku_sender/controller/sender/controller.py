"""发送任务业务控制器"""

import logging
import threading
from enum import Enum
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from .workers import SendTaskWorker, QueueWorker

from danmaku_sender.controller.concurrency import PoolTask
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.service.danmaku_exporter import create_xml_from_danmakus
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.common import VideoTarget, UnsentDanmakusRecord
from danmaku_sender.types.models.queue import TaskStatus
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.config import ApiAuthConfig, SenderConfig
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.runtime.state.queue_state import QueueState


logger = logging.getLogger(__name__)


class SenderStatus(Enum):
    """发送校验状态"""
    READY = "ready"
    EDITOR_DIRTY = "editor_dirty"
    NOT_READY = "not_ready"
    NO_CREDENTIALS = "no_credentials"


class SenderState(Enum):
    """发送任务生命周期状态"""
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"


class SenderController(QObject):
    """发送任务业务控制器"""
    progressUpdated = Signal(int, int, float)
    taskFinished = Signal(object)
    xmlParsed = Signal(str, int)          # file_path, danmaku_count
    xmlParseFailed = Signal(str, object)  # file_path, raw_exception

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
        self._worker: SendTaskWorker | None = None
        self._queue_worker: QueueWorker | None = None
        self._stop_event = threading.Event()

    @property
    def send_status(self) -> SenderStatus:
        """当前发送状态，READY 表示可以启动。"""
        if self.state.editor_is_dirty:
            return SenderStatus.EDITOR_DIRTY
        if not self.state.video_state.is_ready_to_send:
            return SenderStatus.NOT_READY
        if not self.state.sessdata or not self.state.bili_jct:
            return SenderStatus.NO_CREDENTIALS
        return SenderStatus.READY

    def start_task(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        auth_config: ApiAuthConfig,
        strategy_config: SenderConfig
    ):
        """启动发送任务"""
        if self.is_running() or self.is_queue_running():
            logger.warning("任务已在运行中，无法重复启动。")
            return

        self._stop_event.clear()

        self._worker = SendTaskWorker(
            target=target,
            danmakus=danmakus,
            auth_config=auth_config,
            strategy_config=strategy_config,
            stop_event=self._stop_event,
            history_manager=self.history_manager,
        )

        self._worker.progressUpdated.connect(self.progressUpdated.emit)
        self._worker.taskFinished.connect(self._on_worker_finished)

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

    @property
    def sender_state(self) -> SenderState:
        """当前任务生命周期状态"""
        if self._stop_event.is_set():
            return SenderState.STOPPING
        if self.is_running():
            return SenderState.RUNNING
        return SenderState.READY

    # region Queue

    def start_queue(self, queue_state: QueueState, auth_config: ApiAuthConfig, reset_failed: bool = False):
        """启动队列发送。

        Args:
            reset_failed: 是否重置之前失败/跳过的任务。默认 False，只重置残留的 RUNNING 状态。
        """
        if self.is_running() or self.is_queue_running():
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

    def load_xml_file(self, file_path: str):
        """异步解析 XML 弹幕文件"""
        self.state.video_state.loaded_danmakus = []
        parser = DanmakuParser()
        PoolTask.submit(
            parser.parse_xml_file,
            lambda parsed: self._on_parse_success(parsed, file_path),
            lambda err: self._on_parse_error(err, file_path),
            file_path,
        )

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

    # region Slots

    @Slot(object)
    def _on_worker_finished(self, ctx):
        """内部槽函数：处理任务结束清理并向上传递"""
        self.taskFinished.emit(ctx)

    @Slot()
    def _on_worker_cleanup(self):
        """垃圾回收机制"""
        if self._worker is not None:
            logger.debug("SendTaskWorker 线程生命周期结束，正在清理控制器引用。")
            self._worker = None

    @Slot(list, str)
    def _on_parse_success(self, parsed: list, file_path: str):
        if parsed:
            self.state.video_state.loaded_danmakus = parsed
        self.xmlParsed.emit(file_path, len(parsed))

    @Slot(object, str)
    def _on_parse_error(self, err: Exception, file_path: str):
        self.xmlParseFailed.emit(file_path, err)

    # endregion
