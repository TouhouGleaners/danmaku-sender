"""队列发送 Worker：在后台线程执行发送管线并把结果发回主线程。"""

import logging
import threading

from PySide6.QtCore import Signal

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, SenderConfig
from danmaku_sender.controller.concurrency import WorkerThread
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.infra.platform import KeepSystemAwake
from danmaku_sender.service.sender import (
    SendingContext,
    SendJob,
    SendPipeline,
    SendPlan,
)
from danmaku_sender.types.exceptions.exceptions import HistoryStorageError
from danmaku_sender.types.models.queue import TaskSnapshot, TaskStatus

logger = logging.getLogger(__name__)


class QueueSendWorker(WorkerThread):
    """队列发送 Worker。

    启动时接收不可变的 TaskSnapshot 采样，逐个执行发送管线并通过信号发回结果；
    不写 QueueState，状态落账由 SenderController 在主线程完成。
    """

    taskStarted = Signal(str, int)                      # (task_id, idx_0based)
    taskCompleted = Signal(str, object)                 # (task_id, SendingContext)
    taskFailed = Signal(str, str, object)               # (task_id, error_msg, SendingContext)
    taskSkipped = Signal(str, str)                      # (task_id, reason)
    queueCompleted = Signal()                           # 跑完全部任务
    queueAborted = Signal()                             # 中途止住：人工终止或致命中断
    queueProgressUpdated = Signal(int, int, float)      # (current_idx_0based, total, eta)
    taskProgressUpdated = Signal(str, int, int, float)  # (task_id, attempted, task_total, eta)
    ending = Signal(object)                             # run() 退出时 emit(self)

    def __init__(
        self,
        tasks: tuple[TaskSnapshot, ...],
        auth: ApiAuthConfig,
        network: NetworkPolicy,
        queue_config: SenderConfig.QueueConfig,
        history_manager: HistoryManager,
        stop_event: threading.Event,
        prevent_sleep: bool = True,
        parent=None,
    ):
        """初始化队列发送 Worker。

        Args:
            tasks: 启动时的任务快照，运行期间不再追加。
            auth: 身份凭据。
            network: 传输策略。
            queue_config: 整队规则快照。
            history_manager: 本地账本，供存证与查重。
            stop_event: 中止标记。
            prevent_sleep: 任务运行期间是否阻止系统休眠。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.tasks = tasks
        self.auth = auth
        self.network = network
        self.queue_config = queue_config
        self.history_manager = history_manager
        self.stop_event = stop_event
        self.prevent_sleep = prevent_sleep

    def run(self):
        """遍历任务快照逐个执行。启动后添加的任务不会被处理。"""
        tasks = self.tasks
        total = len(tasks)
        stopped_early = False
        # 本线程已发出终态信号的任务
        handled: set[str] = set()

        try:
            with KeepSystemAwake(self.prevent_sleep):
                for idx, snap in enumerate(tasks):
                    if self.stop_event.is_set():
                        stopped_early = True
                        break

                    if snap.status not in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED):
                        continue

                    if snap.status == TaskStatus.UNCONFIGURED:
                        handled.add(snap.definition.task_id)
                        self.taskSkipped.emit(snap.definition.task_id, snap.definition.missing_config_text)
                        continue

                    should_continue = self._execute_task(snap, idx, total)
                    handled.add(snap.definition.task_id)

                    if not should_continue:
                        stopped_early = True
                        break

                    # 任务间隔只在后面还有活干的任务时才有意义（游标走满的空任务不算）
                    has_later_pending = any(
                        s.status is TaskStatus.PENDING and s.attempted < s.definition.total
                        for s in tasks[idx + 1:]
                    )
                    if not self.stop_event.is_set() and has_later_pending:
                        delay = self.queue_config.delay_between_tasks
                        if delay > 0:
                            self.stop_event.wait(delay)

            if stopped_early and not self.stop_event.is_set():
                for snap in tasks:
                    if snap.definition.task_id in handled:
                        continue
                    if snap.status == TaskStatus.PENDING:
                        self.taskSkipped.emit(snap.definition.task_id, "致命错误，队列中止")

        except Exception:
            stopped_early = True
            logger.exception("队列执行发生未预期异常")

        finally:
            if stopped_early or self.stop_event.is_set():
                self.queueAborted.emit()
            else:
                self.queueCompleted.emit()
            self.ending.emit(self)

    def _execute_task(self, snap: TaskSnapshot, idx: int, total: int) -> bool:
        """执行单个队列任务。

        Args:
            snap (TaskSnapshot): 任务快照。
            idx (int): 任务在队列中的序号。
            total (int): 队列任务总数。

        Returns:
            bool: 可继续返回 True，致命错误需中止队列返回 False。
        """
        definition = snap.definition
        task_id = definition.task_id
        self.taskStarted.emit(task_id, idx)
        logger.info(f"[{idx + 1}/{total}] 开始发送: {definition.display_string}")

        ctx = SendingContext(total=len(definition.danmakus), target=definition.target)
        try:
            tail_eta = self._tail_eta(self.tasks[idx + 1:])

            def progress_emitter(attempted: int, task_total: int, eta: float):
                self.queueProgressUpdated.emit(idx, total, eta + tail_eta)
                self.taskProgressUpdated.emit(task_id, attempted, task_total, eta)

            pipeline = SendPipeline(self.auth, self.network, self.history_manager)
            job = SendJob(
                task_id=definition.task_id,
                target=definition.target,
                danmakus=definition.danmakus,
                config=definition.config,
                queue_config=self.queue_config,
                stop_event=self.stop_event,
                allow_duplicates=definition.allow_duplicates,
                start_index=snap.attempted,
            )
            ctx = pipeline.execute(job, progress_emitter=progress_emitter)

            if ctx.fatal_error_occurred:
                # 致命失败中止整队，后续任务不再执行——队列剩余时间归零
                self.queueProgressUpdated.emit(idx, total, 0.0)
                self.taskFailed.emit(task_id, ctx.fatal_error_msg, ctx)
                logger.error(f"致命错误，队列中止于: {definition.display_string} - {ctx.fatal_error_msg}")
                return False

            # COMPLETED / PAUSED 由 Controller 根据 ctx 在主线程判定落账
            self.taskCompleted.emit(task_id, ctx)
            logger.info(f"[{idx + 1}/{total}] 发送完成: {definition.display_string}")
            return True

        except Exception as e:
            self.taskFailed.emit(task_id, str(e), ctx)
            logger.error(f"[{idx + 1}/{total}] 发送失败: {definition.display_string} - {e}")
            return True  # 单任务异常不阻断队列，继续下一个

    def _tail_eta(self, future_tasks: tuple[TaskSnapshot, ...]) -> float:
        """当前任务之后的队列尾部预计时长：每个还有剩余条目的待发任务，任务间隔与计划剩余等待之和。

        计划在估算时生成；轮到该任务执行时会重新生成一份。
        估算失败按 0 计，估算不阻断发送。

        Args:
            future_tasks (tuple[TaskSnapshot, ...]): 后续任务快照。

        Returns:
            float: 秒数。
        """
        eta = 0.0
        try:
            for snap in future_tasks:
                # 游标走满的空任务没有发送，不值得等任务间隔
                if snap.status is not TaskStatus.PENDING or snap.attempted >= snap.definition.total:
                    continue
                eta += self.queue_config.delay_between_tasks
                # 查重关闭时计划不做跳过判定，也就无需查询账本
                db_counts = (
                    {}
                    if snap.definition.allow_duplicates
                    else self.history_manager.count_records_grouped(snap.definition.target)
                )
                plan = SendPlan(
                    snap.definition.danmakus,
                    snap.attempted,
                    snap.definition.config,
                    snap.definition.allow_duplicates,
                    db_counts,
                )
                eta += plan.remaining_eta()
        except HistoryStorageError:
            logger.exception("队列尾部时长估算失败")
            return 0.0
        return eta
