import logging
import threading
from enum import Enum
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from .concurrency import WorkerThread, PoolTask
from .system_utils import KeepSystemAwake

from danmaku_sender.service.sender import SendPipeline, SendJob
from danmaku_sender.service.danmaku_parser import DanmakuParser
from danmaku_sender.service.danmaku_exporter import create_xml_from_danmakus
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.common import VideoTarget, UnsentDanmakusRecord
from danmaku_sender.types.models.queue import QueueTask, TaskStatus
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
    queueTaskStarted = Signal(str)                  # task_id
    queueTaskCompleted = Signal(str, object)        # (task_id, SendingContext)
    queueTaskFailed = Signal(str, str)              # (task_id, error_msg)
    queueFinished = Signal()
    queueProgressUpdated = Signal(int, int, float)  # (current_idx, total, eta)

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

    def start_queue(self, queue_state: QueueState, auth_config: ApiAuthConfig):
        """启动队列发送"""
        if self.is_running() or self.is_queue_running():
            logger.warning("任务已在运行中，无法启动队列。")
            return

        if queue_state.pending_count == 0:
            logger.warning("队列中没有待发送的任务。")
            return

        self._stop_event.clear()

        self._queue_worker = QueueWorker(
            queue_state=queue_state,
            auth_config=auth_config,
            history_manager=self.history_manager,
            stop_event=self._stop_event,
        )

        self._queue_worker.taskStarted.connect(self.queueTaskStarted.emit)
        self._queue_worker.taskCompleted.connect(self.queueTaskCompleted.emit)
        self._queue_worker.taskFailed.connect(self.queueTaskFailed.emit)
        self._queue_worker.queueFinished.connect(self._on_queue_finished)
        self._queue_worker.progressUpdated.connect(self.queueProgressUpdated.emit)

        self._queue_worker.finished.connect(self._on_queue_cleanup)
        self._queue_worker.finished.connect(self._queue_worker.deleteLater)
        self._queue_worker.start()

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

    @Slot()
    def _on_queue_cleanup(self):
        """队列 Worker 清理"""
        if self._queue_worker is not None:
            logger.debug("QueueWorker 线程生命周期结束，正在清理控制器引用。")
            self._queue_worker = None

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


class SendTaskWorker(WorkerThread):
    """用于后台发送弹幕的线程（薄壳：仅负责线程生命周期与信号桥接）"""
    progressUpdated = Signal(int, int, float)  # 已尝试, 总数, ETA
    taskFinished = Signal(object)              # SendingContext

    def __init__(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        auth_config: ApiAuthConfig,
        strategy_config: SenderConfig,
        stop_event: threading.Event,
        history_manager: HistoryManager,
        parent=None
    ):
        super().__init__(parent)
        self.target = target
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.strategy_config = strategy_config
        self.stop_event = stop_event
        self.history_manager = history_manager

    def run(self):
        ctx = None
        try:
            with KeepSystemAwake(self.strategy_config.prevent_sleep):
                pipeline = SendPipeline(self.auth_config, self.history_manager)
                job = SendJob(
                    target=self.target,
                    danmakus=self.danmakus,
                    config=self.strategy_config,
                    stop_event=self.stop_event,
                )
                ctx = pipeline.execute(job, progress_emitter=self.progressUpdated.emit)
        except Exception as e:
            self.report_error("任务发生严重错误", e)
        finally:
            self.taskFinished.emit(ctx)


class QueueWorker(WorkerThread):
    """队列调度引擎：遍历 QueueState 中的待发送任务，逐个执行 SendPipeline。"""
    taskStarted = Signal(str)                  # task_id
    taskCompleted = Signal(str, object)        # (task_id, SendingContext)
    taskFailed = Signal(str, str)              # (task_id, error_msg)
    queueFinished = Signal()
    progressUpdated = Signal(int, int, float)  # (current_idx, total, eta)

    def __init__(
        self,
        queue_state: QueueState,
        auth_config: ApiAuthConfig,
        history_manager: HistoryManager,
        stop_event: threading.Event,
        parent=None,
    ):
        super().__init__(parent)
        self.queue_state = queue_state
        self.auth_config = auth_config
        self.history_manager = history_manager
        self.stop_event = stop_event

    def run(self):
        tasks = self.queue_state.tasks
        total = len(tasks)
        aborted = False

        with KeepSystemAwake(True):
            for idx, task in enumerate(tasks):
                if self.stop_event.is_set():
                    self.queue_state.update_task_status(task.task_id, TaskStatus.SKIPPED)
                    continue

                if task.status != TaskStatus.PENDING:
                    continue

                self.queue_state.current_index = idx
                should_continue = self._execute_task(task, idx, total)

                if not should_continue:
                    aborted = True
                    break

                # 任务间防风控间隔
                if not self.stop_event.is_set() and idx < total - 1:
                    delay = task.config_snapshot.delay_between_tasks
                    if delay > 0:
                        self.stop_event.wait(delay)

        # 如果因致命错误中止，跳过剩余所有 PENDING 任务
        if aborted:
            for task in tasks:
                if task.status == TaskStatus.PENDING:
                    self.queue_state.update_task_status(task.task_id, TaskStatus.SKIPPED)

        self.queueFinished.emit()

    def _execute_task(self, task: QueueTask, idx: int, total: int) -> bool:
        """执行单个队列任务。返回 True 表示继续，False 表示致命错误需中止队列。"""
        self.taskStarted.emit(task.task_id)
        self.queue_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        logger.info(f"[{idx + 1}/{total}] 开始发送: {task.target.display_string}")

        def progress_emitter(attempted: int, task_total: int, eta: float):
            self.progressUpdated.emit(idx, total, eta)

        try:
            pipeline = SendPipeline(self.auth_config, self.history_manager)
            job = SendJob(
                target=task.target,
                danmakus=task.danmakus,
                config=task.config_snapshot,
                stop_event=self.stop_event,
            )
            ctx = pipeline.execute(job, progress_emitter=progress_emitter)

            if ctx.fatal_error_occurred:
                self.queue_state.update_task_status(task.task_id, TaskStatus.FAILED, "致命错误，队列中止")
                self.taskFailed.emit(task.task_id, "致命错误，队列中止")
                logger.error(f"致命错误，队列中止于: {task.target.display_string}")
                return False

            self.queue_state.update_task_status(task.task_id, TaskStatus.COMPLETED)
            self.taskCompleted.emit(task.task_id, ctx)
            logger.info(f"[{idx + 1}/{total}] 发送完成: {task.target.display_string}")
            return True

        except Exception as e:
            self.queue_state.update_task_status(task.task_id, TaskStatus.FAILED, str(e))
            self.taskFailed.emit(task.task_id, str(e))
            logger.error(f"[{idx + 1}/{total}] 发送失败: {task.target.display_string} - {e}")
            return True  # 单任务异常不阻断队列，继续下一个
