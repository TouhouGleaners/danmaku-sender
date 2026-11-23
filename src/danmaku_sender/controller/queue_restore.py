"""队列启动恢复：读取队列库、修正任务状态并载入状态树。"""

import logging
from dataclasses import replace

from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.state import QueueState
from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.queue import Task, TaskStatus

logger = logging.getLogger(__name__)


class QueueRestorer:
    """负责将队列库中的持久化任务恢复至状态树，并回写启动修正后的状态。

    作为唯一同时衔接队列存储与状态树的恢复协调器，数据库连接与损坏备份由QueueStore 处理，跨层状态同步由此类完成，Runtime 仅负责在启动时调用。
    """

    @classmethod
    def restore(cls, store: QueueStore, queue_state: QueueState) -> None:
        """读取全部任务，执行启动态修正并写回数据库，随后载入队列状态。

        Args:
            store (QueueStore): 已打开的队列存储。
            queue_state (QueueState): 目标队列状态树。
        """
        loaded = store.load_all()
        normalized = [cls._normalize(task) for task in loaded]
        changed = [new for old, new in zip(loaded, normalized) if new.state != old.state]
        cls._write_back(store, changed)
        queue_state.restore_tasks(normalized)

    @staticmethod
    def _normalize(task: Task) -> Task:
        """修正单条任务在启动恢复时的状态。

        将异常退出残留的 RUNNING 修正为可继续发送的 PAUSED，并按配置完整性对齐其余待运行状态。

        Args:
            task (Task): 从数据库读取的任务。

        Returns:
            Task: 状态修正后的任务；无需修正时返回原对象。
        """
        state = task.state
        if state.status is TaskStatus.RUNNING:
            return replace(task, state=replace(state, status=TaskStatus.PAUSED))

        status, error = QueueState.aligned_status(
            state.status, state.error_msg, task.is_config_complete
        )
        if status is state.status and error == state.error_msg:
            return task
        return replace(task, state=replace(state, status=status, error_msg=error))

    @staticmethod
    def _write_back(store: QueueStore, changed: list[Task]) -> None:
        """将启动修正后状态发生变化的任务写回数据库。

        单条写入失败仅记录异常日志，不阻断其余任务的恢复与界面启动。

        Args:
            store (QueueStore): 目标队列存储。
            changed (list[Task]): 状态发生变化的任务列表。
        """
        if not changed:
            return

        for task in changed:
            state = task.state
            try:
                store.update_task_state(
                    task.task_id,
                    status=state.status,
                    cursor=state.cursor,
                    burst_count=0,
                    error=state.error_msg or None,
                )
            except QueueStorageError:
                logger.exception(f"启动修正写入失败 [task_id={task.task_id}]")

        logger.info(f"启动时已修正 {len(changed)} 个任务状态并写回数据库")
