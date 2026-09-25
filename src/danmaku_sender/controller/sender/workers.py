"""发送任务 Worker - 负责队列执行的后台线程"""

import logging
import threading

from PySide6.QtCore import Signal

from danmaku_sender.config import ApiAuthConfig, SendPolicy
from danmaku_sender.controller.concurrency import WorkerThread
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.infra.platform import KeepSystemAwake
from danmaku_sender.service.sender import SendJob, SendPipeline
from danmaku_sender.service.sender.delay_manager import DelayManager
from danmaku_sender.types.models.queue import TaskConfig, TaskSnapshot, TaskStatus

logger = logging.getLogger(__name__)


class QueueSendWorker(WorkerThread):
    """队列发送 Worker：薄壳，只执行管线并 emit，不写 QueueState。

    启动时接收不可变 TaskSnapshot 采样；状态落账一律由 SenderController 在主线程完成。
    """

    taskStarted = Signal(str, int)                  # (task_id, idx_0based)
    taskCompleted = Signal(str, object)             # (task_id, SendingContext)
    taskFailed = Signal(str, str)                   # (task_id, error_msg)
    taskSkipped = Signal(str, str)                  # (task_id, reason)
    queueFinished = Signal()
    queueProgressUpdated = Signal(int, int, float)  # (current_idx_0based, total, eta)
    taskProgressUpdated = Signal(str, int, int, float)  # (task_id, attempted, task_total, eta)
    ending = Signal(object)                         # run() 退出时 emit(self)

    def __init__(
        self,
        tasks: tuple[TaskSnapshot, ...],
        auth_config: ApiAuthConfig,
        send_policy: SendPolicy,
        history_manager: HistoryManager,
        stop_event: threading.Event,
        prevent_sleep: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.tasks = tasks
        self.auth_config = auth_config
        self.send_policy = send_policy
        self.history_manager = history_manager
        self.stop_event = stop_event
        self.prevent_sleep = prevent_sleep

    def run(self):
        """遍历任务快照逐个执行。启动后添加的任务不会被处理。"""
        tasks = self.tasks
        total = len(tasks)
        stopped_early = False
        # 本线程已发出终态信号的任务；跳过循环不得再依赖共享 status（主线程 slot 可能尚未落账）
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
                        handled.add(snap.spec.task_id)
                        self.taskSkipped.emit(snap.spec.task_id, "未配置弹幕")
                        continue

                    should_continue = self._execute_task(snap, idx, total)
                    handled.add(snap.spec.task_id)

                    if not should_continue:
                        stopped_early = True
                        break

                    if not self.stop_event.is_set() and idx < total - 1:
                        delay = self.send_policy.delay_between_tasks
                        if delay > 0:
                            self.stop_event.wait(delay)

            if stopped_early and not self.stop_event.is_set():
                for snap in tasks:
                    if snap.spec.task_id in handled:
                        continue
                    if snap.status == TaskStatus.PENDING:
                        self.taskSkipped.emit(snap.spec.task_id, "致命错误，队列中止")

        except Exception as e:
            logger.error(f"队列执行发生未预期异常: {e}", exc_info=True)

        finally:
            self.queueFinished.emit()
            self.ending.emit(self)

    def _execute_task(self, snap: TaskSnapshot, idx: int, total: int) -> bool:
        """执行单个队列任务。返回 True 表示继续，False 表示致命错误需中止队列。"""
        spec = snap.spec
        task_id = spec.task_id
        self.taskStarted.emit(task_id, idx)
        logger.info(f"[{idx + 1}/{total}] 开始发送: {spec.target.display_string}")

        future_tasks = self.tasks[idx + 1:]

        def progress_emitter(attempted: int, task_total: int, eta: float):
            queue_eta = self._calc_queue_eta(attempted, task_total, spec.config, future_tasks, self.send_policy)
            self.queueProgressUpdated.emit(idx, total, queue_eta)
            self.taskProgressUpdated.emit(task_id, attempted, task_total, eta)

        try:
            pipeline = SendPipeline(self.auth_config, self.history_manager)
            job = SendJob(
                target=spec.target,
                danmakus=list(spec.danmakus),  # Danmaku 不可变，无需克隆
                config=spec.config,
                policy=self.send_policy,
                stop_event=self.stop_event,
            )
            ctx = pipeline.execute(job, progress_emitter=progress_emitter)

            if ctx.fatal_error_occurred:
                self.taskFailed.emit(task_id, "致命错误，队列中止")
                logger.error(f"致命错误，队列中止于: {spec.target.display_string}")
                return False

            # COMPLETED / PAUSED 由 Controller 根据 ctx 在主线程判定落账
            self.taskCompleted.emit(task_id, ctx)
            logger.info(f"[{idx + 1}/{total}] 发送完成: {spec.target.display_string}")
            return True

        except Exception as e:
            self.taskFailed.emit(task_id, str(e))
            logger.error(f"[{idx + 1}/{total}] 发送失败: {spec.target.display_string} - {e}")
            return True  # 单任务异常不阻断队列，继续下一个

    @staticmethod
    def _calc_queue_eta(
        current_attempted: int,
        current_total: int,
        current_config: TaskConfig,
        future_tasks: tuple[TaskSnapshot, ...],
        policy: SendPolicy,
    ) -> float:
        """计算整个队列的剩余 ETA（秒）。

        = 当前任务剩余 ETA + 所有未来任务的 ETA
        """
        def _task_eta(attempted: int, total: int, config: TaskConfig) -> float:
            avg_normal = (config.min_delay + config.max_delay) / 2
            avg_rest = (config.rest_min + config.rest_max) / 2
            return DelayManager.calc_eta(
                attempted=attempted,
                total=total,
                burst_enabled=config.burst_enabled,
                burst_size=config.burst_size,
                avg_normal=avg_normal,
                avg_rest=avg_rest,
            )

        queue_eta = _task_eta(current_attempted, current_total, current_config)
        pending_future = [s for s in future_tasks if s.status == TaskStatus.PENDING]

        if future_tasks:
            queue_eta += policy.delay_between_tasks

        for i, s in enumerate(pending_future):
            queue_eta += _task_eta(0, s.spec.total, s.spec.config)
            if future_tasks and s is not future_tasks[-1]:
                queue_eta += policy.delay_between_tasks

        return queue_eta
