"""发送任务业务控制器"""

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, Settings
from danmaku_sender.controller.concurrency import PoolTask
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.service.danmaku_xml import DanmakuXml
from danmaku_sender.service.sender.context import SendingContext
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import (
    RelativePosition,
    StartReadiness,
    UnsentDanmakusRecord,
)
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDraft, TaskStatus

from .workers import QueueSendWorker

logger = logging.getLogger(__name__)


class SenderController(QObject):
    """发送任务业务控制器

    持有 AppState；QueueState 只在本层（主线程 slot）变更，
    后台 QueueSendWorker 仅 emit 事件。
    """
    # 队列信号
    queueStarted = Signal()                             # 启动成功
    queueTaskStarted = Signal(str)                      # task_id
    queueTaskCompleted = Signal(str, object)            # (task_id, SendingContext)
    queueTaskFailed = Signal(str, str, object)          # (task_id, error_msg, SendingContext)
    queueCompleted = Signal()                           # 跑完全部任务
    queueAborted = Signal()                             # 中途止住：人工终止或致命中断
    queueReady = Signal()                               # Worker 清理完毕，可重新启动
    queueProgressUpdated = Signal(int, int, float)      # (current_idx_0based, total, eta)
    taskProgressUpdated = Signal(str, int, int, float)  # (task_id, attempted, task_total, eta)

    def __init__(
        self,
        state: AppState,
        settings: Settings,
        history_manager: HistoryManager,
        parent=None,
    ):
        """初始化控制器。

        Args:
            state: 状态树聚合根，取活动会话与队列。
            settings: 配置容器，取发送策略与传输策略。
            history_manager: 本地账本。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.state = state
        self.settings = settings
        self.history_manager = history_manager
        self._queue_worker: QueueSendWorker | None = None
        self._stop_event = threading.Event()

    @property
    def queue_readiness(self) -> StartReadiness:
        """队列能否启动。

        各未满足条件相互独立，调用方据此给出各自的提示。
        """
        if self._queue_worker is not None:
            # 运行中或上一个 Worker 尚在收尾
            return StartReadiness.ALREADY_RUNNING
        if not self.state.session.sessdata or not self.state.session.bili_jct:
            return StartReadiness.MISSING_CREDENTIALS
        if not self.state.workspace.queue_state.has_startable_tasks:
            return StartReadiness.NO_RUNNABLE_TASKS
        return StartReadiness.READY

    # region 队列结构命令（UI 只发命令，落账在本层）

    def add_task(self, task: TaskDraft) -> None:
        """把任务追加到队列末尾。

        Args:
            task: 任务草稿。
        """
        self.state.workspace.queue_state.add_task(task)

    def insert_task(
        self,
        task: TaskDraft,
        ref_task_id: str,
        position: RelativePosition = RelativePosition.BELOW,
    ) -> None:
        """在参考任务上方/下方插入任务；参考不存在时追加到末尾。

        Args:
            task: 任务草稿。
            ref_task_id: 参考任务标识。
            position: 插在参考任务的哪一侧。
        """
        self.state.workspace.queue_state.insert_task(task, ref_task_id, position)

    def remove_task(self, task_id: str) -> None:
        """移除指定任务。

        Args:
            task_id: 任务标识。
        """
        self.state.workspace.queue_state.remove_task(task_id)

    def move_task(self, task_id: str, toward: RelativePosition) -> None:
        """上下移动一个任务。

        Args:
            task_id: 任务标识。
            toward: 移向参考项的哪一侧，ABOVE 为上移，BELOW 为下移。
        """
        self.state.workspace.queue_state.move_task(task_id, toward)

    def reorder_tasks(self, task_ids: list[str]) -> None:
        """按给定顺序重排任务。

        Args:
            task_ids: 当前队列的全排列。
        """
        self.state.workspace.queue_state.reorder_tasks(task_ids)

    def apply_edit(self, task_id: str, source: TaskDraft) -> None:
        """全量应用任务详情的编辑结果。

        Args:
            task_id: 任务标识。
            source: 编辑结果草稿。
        """
        self.state.workspace.queue_state.apply_edit(task_id, source)

    def assign_danmakus(
        self,
        task_id: str,
        danmakus: list[Danmaku],
        xml_path: Path | None = None,
    ) -> None:
        """为任务分配或更新弹幕列表。

        Args:
            task_id: 任务标识。
            danmakus: 弹幕列表。
            xml_path: 弹幕来源文件；可为 None。
        """
        self.state.workspace.queue_state.assign_danmakus(task_id, danmakus, xml_path=xml_path)

    def clear_all(self) -> None:
        """清空队列中的全部任务。"""
        self.state.workspace.queue_state.clear_all()

    def reset_queue(self) -> None:
        """重置队列：移除已完成，失败任务转待发。"""
        self.state.workspace.queue_state.reset_queue()

    # endregion

    # region Queue

    def start_queue(self) -> None:
        """启动队列发送。

        始终使用 WorkspaceState.queue_state；Worker 事件也只落账到该队列。
        启动成功发 ``queueStarted``，启动条件见 :attr:`queue_readiness`。
        """
        if self._queue_worker is not None:
            logger.warning("任务已在运行或清理中，无法启动队列。")
            return
        if not self.state.session.sessdata or not self.state.session.bili_jct:
            logger.warning("凭证缺失，无法启动队列发送。")
            return

        queue_state = self.state.workspace.queue_state

        # 只清理残留运行态（崩溃留下的 RUNNING、暂停中的 PAUSED）。
        # 失败/跳过转待发必须显式——用户没改动就重跑只会得到同样结果，
        # 重置只由「重置队列」按钮触发（QueueState.reset_queue）。
        for task in queue_state.tasks:
            if task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED):
                queue_state.update_task_status(task.task_id, TaskStatus.PENDING)
        queue_state.current_index = -1

        if queue_state.pending_count == 0:
            logger.warning("队列中没有待发送的任务。")
            return

        self._stop_event.clear()

        # 主线程取不可变快照交给 Worker；之后状态一律经 signal 回本类 slot 落账
        snapshots = queue_state.snapshots({TaskStatus.PENDING, TaskStatus.UNCONFIGURED})
        if not snapshots:
            logger.warning("队列中没有可执行的任务快照。")
            return

        # 队列策略同样取启动时快照：运行期间改设置不影响本次运行，
        # 也避免设置页与 Worker 跨线程共享同一个可变对象。
        send_policy = self.settings.send_policy.model_copy(deep=True)
        session = self.state.session
        auth = ApiAuthConfig(sessdata=session.sessdata, bili_jct=session.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)

        worker = QueueSendWorker(
            tasks=snapshots,
            auth=auth,
            network=network,
            send_policy=send_policy,
            history_manager=self.history_manager,
            stop_event=self._stop_event,
            prevent_sleep=self.settings.global_config.prevent_sleep,
        )

        worker.taskStarted.connect(self._on_task_started)
        worker.taskCompleted.connect(self._on_task_completed)
        worker.taskFailed.connect(self._on_task_failed)
        worker.taskSkipped.connect(self._on_task_skipped)
        worker.queueCompleted.connect(self._on_queue_completed)
        worker.queueAborted.connect(self._on_queue_aborted)
        worker.queueProgressUpdated.connect(self.queueProgressUpdated.emit)
        worker.taskProgressUpdated.connect(self._on_task_progress)

        worker.ending.connect(self._on_worker_discard)
        worker.finished.connect(worker.deleteLater)

        # 先落下运行闸门，再启动线程，避免启动瞬间 UI 仍可结构编辑
        self._queue_worker = worker
        self.state.workspace.sender_is_active = True
        worker.start()
        self.queueStarted.emit()

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
        self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.RUNNING)
        task = self.state.workspace.queue_state.get_task_by_id(task_id)
        if task:
            self.state.workspace.queue_state.update_task_progress(task_id, 0, task.total)
        self.state.workspace.queue_state.current_index = idx
        self._persist_task_record(task_id, TaskStatus.RUNNING)
        self.queueTaskStarted.emit(task_id)

    @Slot(str, object)
    def _on_task_completed(self, task_id: str, ctx: SendingContext | None):
        if ctx is not None and ctx.is_manually_stopped and not ctx.auto_stop_reason:
            self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.PAUSED, "用户手动暂停")
            self._persist_task_record(task_id, TaskStatus.PAUSED)
        else:
            self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.COMPLETED)
            self._persist_task_record(task_id, TaskStatus.COMPLETED)
        self.queueTaskCompleted.emit(task_id, ctx)

    @Slot(str, str, object)
    def _on_task_failed(self, task_id: str, error_msg: str, ctx: SendingContext):
        self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.FAILED, error_msg)
        self._persist_task_record(task_id, TaskStatus.FAILED)
        self.queueTaskFailed.emit(task_id, error_msg, ctx)

    @Slot(str, str)
    def _on_task_skipped(self, task_id: str, reason: str):
        self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.SKIPPED, reason)
        self._persist_task_record(task_id, TaskStatus.SKIPPED)

    @Slot()
    def _on_queue_completed(self):
        self.state.workspace.queue_state.current_index = -1
        self.queueCompleted.emit()

    @Slot()
    def _on_queue_aborted(self):
        self.state.workspace.queue_state.current_index = -1
        self.queueAborted.emit()

    @Slot(str, int, int, float)
    def _on_task_progress(self, task_id: str, attempted: int, task_total: int, eta: float):
        self.state.workspace.queue_state.update_task_progress(task_id, attempted, task_total)
        self.taskProgressUpdated.emit(task_id, attempted, task_total, eta)

    def _persist_task_record(self, task_id: str, status: TaskStatus) -> None:
        """把任务身份与当前状态写入账本，供任务级历史对账。

        任务身份属元数据，落账失败只记日志、不阻断发送；弹幕存证另有独立入账路径。

        Args:
            task_id (str): 任务标识。
            status (TaskStatus): 落账的任务状态。
        """
        task = self.state.workspace.queue_state.get_task_by_id(task_id)
        if task is None:
            logger.warning(f"任务记录落账跳过：队列中已无任务 {task_id}")
            return
        try:
            self.history_manager.upsert_task(task.definition, status)
        except Exception:
            logger.exception(f"任务记录落账失败 [task_id={task_id}]")

    @Slot(object)
    def _on_worker_discard(self, worker: QueueSendWorker):
        """主线程清理：仅当仍是当前 _queue_worker 时释放引用。"""
        if worker is not self._queue_worker:
            return

        logger.debug("QueueSendWorker 线程生命周期结束，正在清理控制器引用。")
        self._queue_worker = None
        self.state.workspace.sender_is_active = False
        self.queueReady.emit()

    # endregion

    def export_unsent_xml(
        self,
        unsent_danmakus: list[UnsentDanmakusRecord],
        file_path: Path,
        on_success: Callable[[None], None],
        on_error: Callable[[str], None],
    ):
        """异步保存未发送弹幕到 XML 文件"""
        PoolTask.submit(
            DanmakuXml.export_unsent,
            on_success,
            lambda err: on_error(str(err)),
            unsent_danmakus, file_path,
        )
