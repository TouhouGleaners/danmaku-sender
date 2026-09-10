"""发送任务 Worker - 负责队列执行的后台线程"""

import logging
import threading

from PySide6.QtCore import Signal

from danmaku_sender.controller.concurrency import WorkerThread
from danmaku_sender.runtime.infra.platform import KeepSystemAwake
from danmaku_sender.service.sender import SendPipeline, SendJob
from danmaku_sender.service.sender.delay_manager import DelayManager
from danmaku_sender.types.models.queue import QueueTask, TaskStatus
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.config import ApiAuthConfig, SenderConfig
from danmaku_sender.runtime.state.queue_state import QueueState


logger = logging.getLogger(__name__)


class QueueWorker(WorkerThread):
    """队列调度引擎：遍历 QueueState 中的待发送任务，逐个执行 SendPipeline。"""
    taskStarted = Signal(str)                           # task_id
    taskCompleted = Signal(str, object)                 # (task_id, SendingContext)
    taskFailed = Signal(str, str)                       # (task_id, error_msg)
    queueFinished = Signal()
    queueProgressUpdated = Signal(int, int, float)      # (current_idx_0based, total, eta)
    taskProgressUpdated = Signal(str, int, int, float)  # (task_id, attempted, task_total, eta)

    def __init__(
        self,
        queue_state: QueueState,
        auth_config: ApiAuthConfig,
        sender_config: SenderConfig,
        history_manager: HistoryManager,
        stop_event: threading.Event,
        parent=None,
    ):
        super().__init__(parent)
        self.queue_state = queue_state
        self.auth_config = auth_config
        self.sender_config = sender_config
        self.history_manager = history_manager
        self.stop_event = stop_event

    def run(self):
        """遍历队列快照逐个执行。启动后添加的任务不会被处理。"""
        tasks = list(self.queue_state.tasks)  # 快照，避免运行期间被并发修改
        total = len(tasks)
        stopped_early = False

        try:
            with KeepSystemAwake(True):
                for idx, task in enumerate(tasks):
                    # 停止信号或致命错误：跳出循环，后续统一跳过
                    if self.stop_event.is_set():
                        stopped_early = True
                        break

                    if task.status not in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED):
                        continue

                    if task.status == TaskStatus.UNCONFIGURED:
                        self.queue_state.update_task_status(task.task_id, TaskStatus.SKIPPED, "未配置弹幕")
                        continue

                    self.queue_state.current_index = idx
                    should_continue = self._execute_task(task, idx, total)

                    if not should_continue:
                        stopped_early = True
                        break

                    # 任务间防风控间隔
                    if not self.stop_event.is_set() and idx < total - 1:
                        delay = task.config_snapshot.delay_between_tasks
                        if delay > 0:
                            self.stop_event.wait(delay)

            # 处理提前终止
            if stopped_early and not self.stop_event.is_set():
                # 致命错误：跳过所有 PENDING 任务
                for task in tasks:
                    if task.status == TaskStatus.PENDING:
                        self.queue_state.update_task_status(task.task_id, TaskStatus.SKIPPED, "致命错误，队列中止")

        except Exception as e:
            logger.error(f"队列执行发生未预期异常: {e}", exc_info=True)

        finally:
            self.queue_state.current_index = -1
            self.queueFinished.emit()

    def _execute_task(self, task: QueueTask, idx: int, total: int) -> bool:
        """执行单个队列任务。返回 True 表示继续，False 表示致命错误需中止队列。"""
        self.taskStarted.emit(task.task_id)
        self.queue_state.update_task_status(task.task_id, TaskStatus.RUNNING)
        logger.info(f"[{idx + 1}/{total}] 开始发送: {task.target.display_string}")

        tasks = list(self.queue_state.tasks)
        future_tasks = tasks[idx + 1:]

        def progress_emitter(attempted: int, task_total: int, eta: float):
            queue_eta = self._calc_queue_eta(attempted, task_total, task.config_snapshot, future_tasks)
            self.queueProgressUpdated.emit(idx, total, queue_eta)
            self.taskProgressUpdated.emit(task.task_id, attempted, task_total, eta)

        try:
            pipeline = SendPipeline(self.auth_config, self.history_manager)
            config = task.config_snapshot.model_copy()
            config.skip_sent = self.sender_config.skip_sent  # 全局策略，不走快照
            job = SendJob(
                target=task.target,
                danmakus=task.danmakus,
                config=config,
                stop_event=self.stop_event,
            )
            ctx = pipeline.execute(job, progress_emitter=progress_emitter)

            if ctx.fatal_error_occurred:
                self.queue_state.update_task_status(task.task_id, TaskStatus.FAILED, "致命错误，队列中止")
                self.taskFailed.emit(task.task_id, "致命错误，队列中止")
                logger.error(f"致命错误，队列中止于: {task.target.display_string}")
                return False

            if ctx.is_manually_stopped and not ctx.auto_stop_reason:
                self.queue_state.update_task_status(task.task_id, TaskStatus.PAUSED, "用户手动暂停")
            else:
                self.queue_state.update_task_status(task.task_id, TaskStatus.COMPLETED)
            self.taskCompleted.emit(task.task_id, ctx)
            logger.info(f"[{idx + 1}/{total}] 发送完成: {task.target.display_string}")
            return True

        except Exception as e:
            self.queue_state.update_task_status(task.task_id, TaskStatus.FAILED, str(e))
            self.taskFailed.emit(task.task_id, str(e))
            logger.error(f"[{idx + 1}/{total}] 发送失败: {task.target.display_string} - {e}")
            return True  # 单任务异常不阻断队列，继续下一个

    @staticmethod
    def _calc_queue_eta(
        current_attempted: int,
        current_total: int,
        current_config: SenderConfig,
        future_tasks: list[QueueTask],
    ) -> float:
        """计算整个队列的剩余 ETA（秒）。

        = 当前任务剩余 ETA + 所有未来任务的 ETA
        """
        def _task_eta(attempted: int, total: int, config: SenderConfig) -> float:
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
        pending_future = [t for t in future_tasks if t.status == TaskStatus.PENDING]

        # 当前任务之后有任务（不论状态），worker 会等待一个 delay
        if future_tasks:
            queue_eta += current_config.delay_between_tasks

        for i, t in enumerate(pending_future):
            queue_eta += _task_eta(0, t.total, t.config_snapshot)
            # 每个 PENDING 任务之后，只要不是原始队列最后一项，就加延迟
            if future_tasks and t is not future_tasks[-1]:
                queue_eta += t.config_snapshot.delay_between_tasks

        return queue_eta
