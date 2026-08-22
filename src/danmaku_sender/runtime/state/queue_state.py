import logging

from PySide6.QtCore import QObject, Signal

from danmaku_sender.types.models.queue import QueueTask, TaskStatus


logger = logging.getLogger(__name__)


class QueueState(QObject):
    """发送任务队列状态管理"""

    tasksChanged = Signal()               # 队列列表变更
    taskStatusChanged = Signal(str, str)  # (task_id, new_status.value)
    currentTaskChanged = Signal(int)      # 当前执行索引变更

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[QueueTask] = []
        self._current_index: int = -1

    @property
    def tasks(self) -> list[QueueTask]:
        return self._tasks

    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value: int):
        if self._current_index != value:
            self._current_index = value
            self.currentTaskChanged.emit(value)

    def add_task(self, task: QueueTask):
        """添加任务到队列末尾"""
        self._tasks.append(task)
        self.tasksChanged.emit()
        logger.info(f"任务已加入队列: [{task.task_id}] {task.target.display_string} ({len(task.danmakus)} 条弹幕)")

    def remove_task(self, task_id: str) -> bool:
        """移除指定任务（仅 PENDING 状态可移除）"""
        for i, task in enumerate(self._tasks):
            if task.task_id == task_id and task.status == TaskStatus.PENDING:
                self._tasks.pop(i)
                self.tasksChanged.emit()
                logger.info(f"任务已从队列移除: [{task_id}]")
                return True
        return False

    def move_task(self, task_id: str, direction: int) -> bool:
        """移动任务位置（direction: -1 上移, +1 下移）"""
        for i, task in enumerate(self._tasks):
            if task.task_id == task_id and task.status == TaskStatus.PENDING:
                new_index = i + direction
                if 0 <= new_index < len(self._tasks) and self._tasks[new_index].status == TaskStatus.PENDING:
                    self._tasks[i], self._tasks[new_index] = self._tasks[new_index], self._tasks[i]
                    self.tasksChanged.emit()
                    return True
        return False

    def clear_completed(self):
        """清除已完成/失败/跳过的任务（保留 PENDING 和 PAUSED）"""
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.status in (TaskStatus.PENDING, TaskStatus.PAUSED)]
        removed = before - len(self._tasks)
        if removed > 0:
            self.tasksChanged.emit()
            logger.info(f"已清除 {removed} 个已完成任务")

    def get_task_by_id(self, task_id: str) -> QueueTask | None:
        """按 ID 查找任务"""
        for task in self._tasks:
            if task.task_id == task_id:
                return task
        return None

    def update_task_status(self, task_id: str, status: TaskStatus, error_msg: str = ""):
        """更新任务状态"""
        task = self.get_task_by_id(task_id)
        if task:
            task.status = status
            task.error_msg = error_msg
            self.taskStatusChanged.emit(task_id, status.value)

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self._tasks if t.status == TaskStatus.PENDING)

    @property
    def is_empty(self) -> bool:
        return len(self._tasks) == 0
