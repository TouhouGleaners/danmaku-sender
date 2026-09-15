"""发送任务队列状态管理"""

import logging
from collections import Counter

from PySide6.QtCore import QObject, Signal

from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import QueueTask, TaskStatus

logger = logging.getLogger(__name__)


class QueueState(QObject):
    """发送任务队列的响应式状态中心。

    所有任务数据变更必须通过本类的方法进行，
    以确保信号正确发射，所有观察者（发射器、监视器等）自动同步。
    """

    # ── 信号 ──────────────────────────────────────────────
    tasksChanged = Signal()                      # 队列结构变更（增删排序）
    taskUpdated = Signal(str)                    # 任务数据变更（弹幕数、配置等）
    taskStatusChanged = Signal(str, TaskStatus)  # (task_id, TaskStatus 枚举)
    currentTaskChanged = Signal(int)             # 当前执行游标

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[QueueTask] = []
        self._current_index: int = -1

    # ── 只读属性 ──────────────────────────────────────────

    @property
    def tasks(self) -> list[QueueTask]:
        """任务列表（只读快照）"""
        return self._tasks

    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value: int):
        if self._current_index != value:
            self._current_index = value
            self.currentTaskChanged.emit(value)

    @property
    def is_empty(self) -> bool:
        return len(self._tasks) == 0

    # ── 统计属性 ──────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        """等待发送的任务数"""
        return sum(1 for t in self._tasks if t.status == TaskStatus.PENDING)

    @property
    def has_pending_tasks(self) -> bool:
        """队列中是否有待发送的任务"""
        return any(t.status == TaskStatus.PENDING for t in self._tasks)

    @property
    def total_danmaku_count(self) -> int:
        """全队列弹幕总数"""
        return sum(len(t.danmakus) for t in self._tasks)

    @property
    def processed_danmaku_count(self) -> int:
        """全队列已处理弹幕数（不含 PENDING 和 PAUSED）"""
        return sum(
            t.attempted for t in self._tasks
            if t.status not in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED, TaskStatus.PAUSED)
        )

    @property
    def status_counts(self) -> dict[TaskStatus, int]:
        """各状态的任务数量"""
        counts: dict[TaskStatus, int] = Counter()
        for t in self._tasks:
            counts[t.status] += 1
        return dict(counts)

    # ── 查询 ─────────────────────────────────────────────

    def get_task_by_id(self, task_id: str) -> QueueTask | None:
        """按 ID 查找任务"""
        for task in self._tasks:
            if task.task_id == task_id:
                return task
        return None

    # ── 结构变更（发射 tasksChanged）──────────────────────

    def add_task(self, task: QueueTask):
        """添加任务到队列末尾"""
        self._tasks.append(task)
        self.tasksChanged.emit()
        logger.info(
            f"任务已加入队列: [{task.task_id}] "
            f"{task.target.display_string} ({len(task.danmakus)} 条弹幕)"
        )

    def remove_task(self, task_id: str) -> bool:
        """移除指定任务（仅 PENDING/UNCONFIGURED 状态可移除）"""
        for i, task in enumerate(self._tasks):
            if task.task_id == task_id and task.status in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED):
                self._tasks.pop(i)
                self.tasksChanged.emit()
                logger.info(f"任务已从队列移除: [{task_id}]")
                return True
        return False

    def move_task(self, task_id: str, direction: int) -> bool:
        """移动任务位置（direction: -1 上移, +1 下移）"""
        movable = (TaskStatus.PENDING, TaskStatus.UNCONFIGURED)
        for i, task in enumerate(self._tasks):
            if task.task_id == task_id and task.status in movable:
                new_index = i + direction
                if 0 <= new_index < len(self._tasks) and self._tasks[new_index].status in movable:
                    self._tasks[i], self._tasks[new_index] = self._tasks[new_index], self._tasks[i]
                    self.tasksChanged.emit()
                    return True
        return False

    def reorder_tasks(self, new_tasks: list[QueueTask]):
        """重排任务顺序"""
        self._tasks = list(new_tasks)
        self.tasksChanged.emit()

    def clear_completed(self):
        """清除已完成/失败/跳过的任务（保留 PENDING、PAUSED、UNCONFIGURED）"""
        before = len(self._tasks)
        self._tasks = [
            t for t in self._tasks
            if t.status in (TaskStatus.PENDING, TaskStatus.PAUSED, TaskStatus.UNCONFIGURED)
        ]
        removed = before - len(self._tasks)
        if removed > 0:
            self.tasksChanged.emit()
            logger.info(f"已清除 {removed} 个已完成任务")

    # ── 数据变更（发射 taskUpdated）───────────────────────

    def assign_danmakus(self, task_id: str, danmakus: list[Danmaku], xml_path: str = ""):
        """为任务分配/更新弹幕列表，自动联动计算总数并激活就绪状态。

        拖放 XML、编辑器保存等场景的统一入口。
        """
        task = self.get_task_by_id(task_id)
        if not task:
            return

        task.danmakus = danmakus
        task.total = len(danmakus)
        if xml_path:
            task.xml_path = xml_path

        # 状态自愈：UNCONFIGURED → PENDING
        if task.status == TaskStatus.UNCONFIGURED and task.total > 0:
            task.status = TaskStatus.PENDING

        self.taskUpdated.emit(task_id)
        logger.info(f"已分配弹幕: {task.target.display_string} ({task.total} 条)")

    def apply_edit(self, task_id: str, source: QueueTask):
        """全量应用来自详情弹窗沙盒的修改结果"""
        task = self.get_task_by_id(task_id)
        if not task:
            return

        task.apply_edit(source)
        self.taskUpdated.emit(task_id)

    # ── 状态变更（发射 taskStatusChanged）─────────────────

    def update_task_status(self, task_id: str, status: TaskStatus, error_msg: str = ""):
        """更新任务状态"""
        task = self.get_task_by_id(task_id)
        if task:
            task.status = status
            task.error_msg = error_msg
            self.taskStatusChanged.emit(task_id, status)
