"""启动恢复的编排：读队列库、修正状态、装入状态树。"""

import logging
from dataclasses import replace

from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.state import QueueState
from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.queue import TaskStatus

logger = logging.getLogger(__name__)


class QueueRestorer:
    """把队列库里的任务恢复进状态树，并把状态修正写回数据库。

    本类是唯一同时看得见队列库与状态树的地方：库侧的开机自愈归 QueueStore，
    两侧之间的状态对齐与写回归这里，Runtime 只负责唤起。
    """

    @staticmethod
    def restore(store: QueueStore, queue_state: QueueState) -> None:
        """读出全部任务，按规则修正状态，装入状态树。

        崩溃残留的 RUNNING 改回可续的 PAUSED；按配置齐备度对齐出的状态变化
        写回数据库，保证两端一致。

        Args:
            store (QueueStore): 已打开的队列存储。
            queue_state (QueueState): 目标状态树。
        """
        recovered = store.load_all()
        normalized = []
        corrected = 0
        for task in recovered:
            before = task.execution
            if before.status is TaskStatus.RUNNING:
                status, error = TaskStatus.PAUSED, before.error_msg
            else:
                status, error = QueueState.aligned_status(
                    before.status, before.error_msg, task.definition.is_config_complete
                )
            normalized.append(replace(task, execution=replace(before, status=status, error_msg=error)))
            if status is before.status and error == before.error_msg:
                continue
            corrected += 1
            try:
                store.update_task_state(
                    task.definition.task_id,
                    status=status,
                    cursor=before.attempted,
                    burst_count=0,
                    error=error or None,
                )
            except QueueStorageError:
                logger.exception(f"启动修正写入失败 [task_id={task.definition.task_id}]")
        if corrected:
            logger.info(f"启动时已修正 {corrected} 个任务状态并写回数据库")

        queue_state.restore_tasks(normalized)
