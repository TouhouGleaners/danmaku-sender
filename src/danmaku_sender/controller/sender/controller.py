"""发送任务业务控制器"""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, Settings
from danmaku_sender.controller.concurrency import PoolTask
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.service.danmaku_xml import DanmakuXml
from danmaku_sender.service.sender.context import SendingContext
from danmaku_sender.state import AppState, QueueState
from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.common import (
    RelativePosition,
    StartReadiness,
    UnsentDanmakusRecord,
)
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    Task,
    TaskDefinition,
    TaskDraft,
    TaskExecution,
    TaskStatus,
)

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
    queueCompleted = Signal()                           # 全部任务执行完毕
    queueAborted = Signal()                             # 中途终止：人工停止或致命中断
    queueReady = Signal()                               # Worker 清理完毕，可重新启动
    queueProgressUpdated = Signal(int, int, float)      # (current_idx_0based, total, eta)
    taskProgressUpdated = Signal(str, int, int, float)  # (task_id, attempted, task_total, eta)

    def __init__(
        self,
        state: AppState,
        settings: Settings,
        history_manager: HistoryManager,
        queue_store: QueueStore,
        parent=None,
    ):
        """初始化控制器。

        Args:
            state: 状态树聚合根，取活动会话与队列。
            settings: 配置容器，取发送策略与传输策略。
            history_manager: 本地账本。
            queue_store: 队列存储，结构变更与运行状态的持久化入口。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.state = state
        self.settings = settings
        self.history_manager = history_manager
        self.queue_store = queue_store
        self._queue_worker: QueueSendWorker | None = None
        self._stop_event = threading.Event()
        self._task_definitions: dict[str, TaskDefinition] = {}  # 本轮队列的任务定义快照，落账取此而非实时队列

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

    # region 队列结构命令（UI 只发命令，先写入数据库再更新内存状态）

    def add_task(self, task: TaskDraft) -> None:
        """追加任务至队列末尾，先写入数据库再更新内存状态。

        Args:
            task: 任务草稿。
        """
        self.queue_store.add_task(self._built_task(task))
        self.state.workspace.queue_state.add_task(task)

    def insert_task(
        self,
        task: TaskDraft,
        ref_task_id: str,
        position: RelativePosition = RelativePosition.BELOW,
    ) -> None:
        """在参考任务上方/下方插入任务，先写入数据库再更新内存状态；参考不存在时追加到末尾。

        Args:
            task: 任务草稿。
            ref_task_id: 参考任务标识。
            position: 插在参考任务的哪一侧。
        """
        queue_state = self.state.workspace.queue_state
        at = queue_state.insert_index_for(ref_task_id, position)
        self.queue_store.insert_task(self._built_task(task), at)
        queue_state.insert_task(task, ref_task_id, position)

    def remove_task(self, task_id: str) -> None:
        """移除指定任务，先写入数据库再更新内存状态。

        Args:
            task_id: 任务标识。
        """
        view = self.state.workspace.queue_state.get_task_by_id(task_id)
        # 与 QueueState.remove_task 同一闸门：发送中的任务不移除
        if view is None or view.status is TaskStatus.RUNNING:
            return
        self.queue_store.delete_tasks([task_id])
        self.state.workspace.queue_state.remove_task(task_id)

    def move_task(self, task_id: str, toward: RelativePosition) -> None:
        """上下移动一个任务，先写入数据库再更新内存状态。

        Args:
            task_id: 任务标识。
            toward: 移向参考项的哪一侧，ABOVE 为上移，BELOW 为下移。
        """
        queue_state = self.state.workspace.queue_state
        order = queue_state.order_with_move(task_id, toward)
        if order is None:
            return
        self.queue_store.reorder_tasks(order)
        queue_state.move_task(task_id, toward)

    def reorder_tasks(self, task_ids: list[str]) -> None:
        """按给定顺序重排任务，先写入数据库再更新内存状态。

        Args:
            task_ids: 当前队列的全排列。
        """
        self.queue_store.reorder_tasks(task_ids)
        self.state.workspace.queue_state.reorder_tasks(task_ids)

    def apply_edit(self, task_id: str, source: TaskDraft) -> None:
        """应用任务详情的编辑结果，先写入数据库再更新内存状态。

        若原有已指定的发送目标被修改，则视为创建新任务并重新生成 task_id，以避免同一 task_id跨视频记录导致后续历史对账错位；
        更换 task_id 或弹幕列表时进度游标归零，若弹幕列表未变则保留既有弹幕及失败记录。

        Args:
            task_id: 原任务标识。
            source: 编辑结果草稿。
        """
        queue_state = self.state.workspace.queue_state
        view = queue_state.get_task_by_id(task_id)
        # 与 QueueState.apply_edit 同一闸门：不可编辑的状态拒绝结构编辑
        if view is None or not view.status.is_editable:
            return
        # 未指定目标时填上是补配置，不算换任务；改掉已指定的目标即另立新任务
        reissued = view.target.is_assigned and source.target != view.target
        new_id = uuid.uuid4().hex if reissued else task_id
        list_changed = tuple(source.danmakus) != view.danmakus
        definition = replace(source.to_definition(), task_id=new_id)
        built = self._built(
            definition,
            source.status,
            source.error_msg,
            0 if (reissued or list_changed) else view.attempted,
        )
        if reissued:
            self.queue_store.reissue_task(task_id, built)
        else:
            self.queue_store.update_task(built, items_replaced=list_changed)
        queue_state.apply_edit(task_id, source, new_id=new_id)

    def assign_danmakus(
        self,
        task_id: str,
        danmakus: list[Danmaku],
        xml_path: Path | None = None,
    ) -> None:
        """为任务分配或更新弹幕列表，先写入数据库再更新内存状态。

        Args:
            task_id: 任务标识。
            danmakus: 弹幕列表。
            xml_path: 弹幕来源文件；可为 None。
        """
        queue_state = self.state.workspace.queue_state
        view = queue_state.get_task_by_id(task_id)
        # 与 QueueState.assign_danmakus 同一闸门：不可编辑的状态拒绝换清单
        if view is None or not view.status.is_editable:
            return
        list_changed = tuple(danmakus) != view.danmakus
        definition = replace(
            view.definition,
            danmakus=tuple(danmakus),
            meta=replace(view.meta, xml_path=xml_path if xml_path is not None else view.meta.xml_path),
        )
        built = self._built(
            definition,
            view.status,
            view.error_msg,
            0 if list_changed else view.attempted,
        )
        self.queue_store.update_task(built, items_replaced=list_changed)
        queue_state.assign_danmakus(task_id, danmakus, xml_path=xml_path)

    def clear_all(self) -> None:
        """清空队列中的全部任务，先写入数据库再更新内存状态。"""
        self.queue_store.clear_all()
        self.state.workspace.queue_state.clear_all()

    def reset_queue(self) -> None:
        """重置队列：移除已完成，失败任务转待发，先写入数据库再更新内存状态。"""
        queue_state = self.state.workspace.queue_state
        remove_ids = [view.task_id for view in queue_state.tasks if view.status is TaskStatus.COMPLETED]
        revive_ids = [view.task_id for view in queue_state.tasks if view.status is TaskStatus.FAILED]
        if remove_ids or revive_ids:
            self.queue_store.reset_queue(remove_ids, revive_ids)
        queue_state.reset_queue()

    def reset_progress(self, task_id: str) -> None:
        """清零指定任务的发送进度游标，持久化后同步更新内存状态。

        Args:
            task_id: 任务唯一标识。
        """
        view = self.state.workspace.queue_state.get_task_by_id(task_id)
        if view is None:
            return
        self.queue_store.reset_tasks([task_id], status=view.status, error=view.error_msg or None)
        self.state.workspace.queue_state.reset_progress(task_id)

    # endregion

    # region 持久化辅助

    @staticmethod
    def _built(definition: TaskDefinition, status: TaskStatus, error_msg: str, cursor: int) -> Task:
        """按配置完整性对齐任务状态，组装待持久化的 Task 对象。

        Args:
            definition: 不可变任务定义。
            status: 对齐前的任务状态。
            error_msg: 对齐前的错误说明。
            cursor: 断点续传游标。

        Returns:
            Task: 状态已对齐的待持久化任务对象。
        """
        aligned_status, aligned_error = QueueState.reconciled_status(
            status, error_msg, definition.is_config_complete
        )
        return Task(
            definition=definition,
            execution=TaskExecution(status=aligned_status, error_msg=aligned_error, attempted=cursor),
        )

    @classmethod
    def _built_task(cls, draft: TaskDraft) -> Task:
        """将任务草稿转换为待持久化的 Task 对象。

        Args:
            draft: 任务草稿。

        Returns:
            Task: 转换后的任务对象。
        """
        return cls._built(draft.to_definition(), draft.status, draft.error_msg, draft.attempted)

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
                self._persist_run_state(task.task_id)
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
        self._task_definitions = {s.definition.task_id: s.definition for s in snapshots}

        # 整队规则同样取启动时快照：运行期间改设置不影响本次运行，
        # 也避免设置页与 Worker 跨线程共享同一个可变对象。
        queue_config = self.settings.sender_config.queue.model_copy(deep=True)
        session = self.state.session
        auth = ApiAuthConfig(sessdata=session.sessdata, bili_jct=session.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)

        worker = QueueSendWorker(
            tasks=snapshots,
            auth=auth,
            network=network,
            queue_config=queue_config,
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
        # 进度不清零：游标是断点续传的起点，任务行继续从原位置显示
        self.state.workspace.queue_state.current_index = idx
        self._persist_run_state(task_id)
        self._persist_task_record(task_id, TaskStatus.RUNNING)
        self.queueTaskStarted.emit(task_id)

    @Slot(str, object)
    def _on_task_completed(self, task_id: str, ctx: SendingContext | None):
        if ctx is not None and ctx.is_manually_stopped:
            self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.PAUSED, "用户手动暂停")
            self._persist_task_record(task_id, TaskStatus.PAUSED)
        else:
            self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.COMPLETED)
            self._persist_task_record(task_id, TaskStatus.COMPLETED)
        self._persist_run_state(task_id)
        self.queueTaskCompleted.emit(task_id, ctx)

    @Slot(str, str, object)
    def _on_task_failed(self, task_id: str, error_msg: str, ctx: SendingContext):
        self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.FAILED, error_msg)
        self._persist_run_state(task_id)
        self._persist_task_record(task_id, TaskStatus.FAILED)
        self.queueTaskFailed.emit(task_id, error_msg, ctx)

    @Slot(str, str)
    def _on_task_skipped(self, task_id: str, reason: str):
        # SKIPPED 的任务从未发包、无存证可对账，不写任务记录；已有记录保持原状
        self.state.workspace.queue_state.update_task_status(task_id, TaskStatus.SKIPPED, reason)
        self._persist_run_state(task_id)

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
        self._persist_run_state(task_id)
        self.taskProgressUpdated.emit(task_id, attempted, task_total, eta)

    def _persist_run_state(self, task_id: str) -> None:
        """将任务当前的运行状态与进度游标同步写入队列数据库。

        爆发计数暂未接入运行时状态，固定写入 0。写入失败仅记录日志，不阻断当前发送流程。

        Args:
            task_id: 任务唯一标识。
        """
        view = self.state.workspace.queue_state.get_task_by_id(task_id)
        if view is None:
            return
        try:
            self.queue_store.update_task_state(
                task_id,
                status=view.status,
                cursor=view.attempted,
                burst_count=0,
                error=view.error_msg or None,
            )
        except QueueStorageError:
            logger.exception(f"运行状态写入失败 [task_id={task_id}]")

    def _persist_task_record(self, task_id: str, status: TaskStatus) -> None:
        """把任务身份与当前状态写入账本，供任务级历史对账。

        身份取启动时固化的任务定义快照，不回查实时队列
        ——终态信号到达时队列可能已被清理，用实时数据会让存证失去归属。
        任务身份属元数据，落账失败只记日志、不阻断发送；弹幕存证另有独立入账路径。

        SKIPPED 不落账：该状态的任务从未发包、无存证可对账，写入即是空行；
        已有记录保持原状，不覆盖成 SKIPPED。

        Args:
            task_id (str): 任务标识。
            status (TaskStatus): 落账的任务状态。
        """
        definition = self._task_definitions.get(task_id)
        if definition is None:
            logger.warning(f"任务记录落账跳过：没有任务 [{task_id}] 的任务定义快照")
            return
        try:
            self.history_manager.upsert_task(definition, status)
        except Exception:
            logger.exception(f"任务记录落账失败 [task_id={task_id}]")

    @Slot(object)
    def _on_worker_discard(self, worker: QueueSendWorker):
        """主线程清理：仅当仍是当前 _queue_worker 时释放引用。"""
        if worker is not self._queue_worker:
            return

        logger.debug("QueueSendWorker 线程生命周期结束，正在清理控制器引用。")
        self._queue_worker = None
        self._task_definitions.clear()
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
