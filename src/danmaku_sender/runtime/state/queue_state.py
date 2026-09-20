"""发送任务队列状态管理"""

import logging
import threading
from collections import Counter

from PySide6.QtCore import QObject, Signal

from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import InsertPosition, QueueTask, TaskStatus

logger = logging.getLogger(__name__)


class QueueState(QObject):
    """发送任务队列的响应式状态中心。

    所有任务数据变更必须通过本类的方法进行，
    以确保信号正确发射，所有观察者（发射器、监视器等）自动同步。

    内部用 RLock 保护结构读写；只读访问统一走 tasks 属性（防御性副本）。
    """

    # ── 信号 ──────────────────────────────────────────────
    tasksChanged = Signal()                      # 队列结构变更（增删排序）
    taskDataChanged = Signal(str)                # 任务数据变更（弹幕数、配置等）
    taskProgressChanged = Signal(str, int, int)  # (task_id, attempted, total)
    taskStatusChanged = Signal(str, TaskStatus)  # (task_id, TaskStatus 枚举)
    currentTaskChanged = Signal(int)             # 当前执行游标

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[QueueTask] = []
        self._current_index: int = -1
        self._lock = threading.RLock()

    # ── 只读属性 ──────────────────────────────────────────

    @property
    def tasks(self) -> list[QueueTask]:
        """任务列表快照：加锁浅拷贝，供 UI / Worker 只读使用。

        返回的是新 list，元素仍是原 QueueTask 引用；不要在副本上改结构，
        修改必须走 QueueState 的变更 API。
        """
        with self._lock:
            return list(self._tasks)

    def sample_task_fields(
        self,
        statuses: set[TaskStatus] | frozenset[TaskStatus],
    ) -> list[tuple[str, str, int, int, str, str]]:
        """在同一把锁下拷贝任务字段，避免跨线程读到撕裂的可变对象。

        Returns:
            list of (task_id, bvid, cid, p_index, p_title, target_title)
        """
        rows: list[tuple[str, str, int, int, str, str]] = []
        with self._lock:
            for t in self._tasks:
                if t.status not in statuses:
                    continue
                rows.append(
                    (
                        t.task_id,
                        t.target.bvid,
                        t.target.cid,
                        t.p_index,
                        t.p_title,
                        t.target.title,
                    )
                )
        return rows

    @property
    def current_index(self) -> int:
        with self._lock:
            return self._current_index

    @current_index.setter
    def current_index(self, value: int):
        emit = False
        with self._lock:
            if self._current_index != value:
                self._current_index = value
                emit = True
        if emit:
            self.currentTaskChanged.emit(value)

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return len(self._tasks) == 0

    # ── 统计属性 ──────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        """等待发送的任务数"""
        with self._lock:
            return sum(1 for t in self._tasks if t.status == TaskStatus.PENDING)

    @property
    def has_pending_tasks(self) -> bool:
        """队列中是否有待发送的任务"""
        with self._lock:
            return any(t.status == TaskStatus.PENDING for t in self._tasks)

    @property
    def total_danmaku_count(self) -> int:
        """全队列弹幕总数"""
        with self._lock:
            return sum(len(t.danmakus) for t in self._tasks)

    @property
    def processed_danmaku_count(self) -> int:
        """全队列已处理弹幕数（不含 PENDING、UNCONFIGURED 和 PAUSED）"""
        with self._lock:
            return sum(
                t.attempted for t in self._tasks
                if t.status not in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED, TaskStatus.PAUSED)
            )

    @property
    def status_counts(self) -> dict[TaskStatus, int]:
        """各状态的任务数量"""
        counts: dict[TaskStatus, int] = Counter()
        with self._lock:
            for t in self._tasks:
                counts[t.status] += 1
        return dict(counts)

    # ── 查询 ─────────────────────────────────────────────

    def get_task_by_id(self, task_id: str) -> QueueTask | None:
        """按 ID 查找任务"""
        with self._lock:
            for task in self._tasks:
                if task.task_id == task_id:
                    return task
        return None

    # ── 结构变更（发射 tasksChanged）──────────────────────

    def add_task(self, task: QueueTask):
        """添加任务到队列末尾"""
        with self._lock:
            self._tasks.append(task)
        self.tasksChanged.emit()
        logger.info(
            f"任务已加入队列: [{task.task_id}] "
            f"{task.target.display_string} ({len(task.danmakus)} 条弹幕)"
        )

    def insert_task(
        self,
        task: QueueTask,
        ref_task_id: str,
        position: InsertPosition = InsertPosition.BELOW,
    ):
        """在参考任务上方/下方插入；参考不存在时追加到末尾。

        这是队列插入的唯一公开入口，调用方不接触绝对下标。
        """
        with self._lock:
            ref_index = -1
            for i, t in enumerate(self._tasks):
                if t.task_id == ref_task_id:
                    ref_index = i
                    break
            if ref_index < 0:
                self._tasks.append(task)
            else:
                index = ref_index if position is InsertPosition.ABOVE else ref_index + 1
                if index >= len(self._tasks):
                    self._tasks.append(task)
                else:
                    self._tasks.insert(max(0, index), task)
        self.tasksChanged.emit()
        logger.info(
            f"任务已插入队列 (相对 {ref_task_id} {position.name}): [{task.task_id}] "
            f"{task.target.display_string} ({len(task.danmakus)} 条弹幕)"
        )

    def remove_task(self, task_id: str) -> bool:
        """移除指定任务（仅 PENDING/UNCONFIGURED 状态可移除）"""
        removed = False
        with self._lock:
            for i, task in enumerate(self._tasks):
                if task.task_id == task_id and task.status in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED):
                    self._tasks.pop(i)
                    removed = True
                    break
        if removed:
            self.tasksChanged.emit()
            logger.info(f"任务已从队列移除: [{task_id}]")
        return removed

    def move_task(self, task_id: str, direction: int) -> bool:
        """移动任务位置（direction: -1 上移, +1 下移）"""
        movable = (TaskStatus.PENDING, TaskStatus.UNCONFIGURED)
        moved = False
        with self._lock:
            for i, task in enumerate(self._tasks):
                if task.task_id == task_id and task.status in movable:
                    new_index = i + direction
                    if 0 <= new_index < len(self._tasks) and self._tasks[new_index].status in movable:
                        self._tasks[i], self._tasks[new_index] = self._tasks[new_index], self._tasks[i]
                        moved = True
                    break
        if moved:
            self.tasksChanged.emit()
        return moved

    def reorder_tasks(self, new_tasks: list[QueueTask]):
        """重排任务顺序"""
        with self._lock:
            self._tasks = list(new_tasks)
        self.tasksChanged.emit()

    def clear_completed(self):
        """清除已完成/失败/跳过的任务（保留 PENDING、PAUSED、UNCONFIGURED）"""
        removed = 0
        with self._lock:
            before = len(self._tasks)
            self._tasks = [
                t for t in self._tasks
                if t.status in (TaskStatus.PENDING, TaskStatus.PAUSED, TaskStatus.UNCONFIGURED)
            ]
            removed = before - len(self._tasks)
        if removed > 0:
            self.tasksChanged.emit()
            logger.info(f"已清除 {removed} 个已完成任务")

    # ── 数据变更（发射 taskDataChanged）───────────────────────

    def assign_danmakus(self, task_id: str, danmakus: list[Danmaku], xml_path: str = ""):
        """为任务分配/更新弹幕列表，自动联动计算总数并激活就绪状态。

        拖放 XML、编辑器保存等场景的统一入口。
        """
        task = self.get_task_by_id(task_id)
        if not task:
            return

        with self._lock:
            task.danmakus = danmakus
            task.total = len(danmakus)
            if xml_path:
                task.xml_path = xml_path
            need_status = task.status == TaskStatus.UNCONFIGURED and task.total > 0
            total = task.total

        if need_status:
            self.update_task_status(task_id, TaskStatus.PENDING)

        self.taskDataChanged.emit(task_id)
        logger.info(f"已分配弹幕: {task.target.display_string} ({total} 条)")

    def apply_edit(self, task_id: str, source: QueueTask):
        """全量应用来自详情弹窗沙盒的修改结果"""
        task = self.get_task_by_id(task_id)
        if not task:
            return

        old_status = task.status
        with self._lock:
            task.apply_edit(source)
            new_status = task.status
            error_msg = task.error_msg

        if new_status != old_status:
            self.update_task_status(task_id, new_status, error_msg)

        self.taskDataChanged.emit(task_id)

    # ── 状态变更（发射 taskStatusChanged）─────────────────

    def update_task_status(self, task_id: str, status: TaskStatus, error_msg: str = ""):
        """更新任务状态"""
        task = self.get_task_by_id(task_id)
        if not task:
            return
        with self._lock:
            task.status = status
            task.error_msg = error_msg
        self.taskStatusChanged.emit(task_id, status)

    def update_task_progress(self, task_id: str, attempted: int, total: int):
        """更新发送进度并通知观察者"""
        task = self.get_task_by_id(task_id)
        if not task:
            return
        with self._lock:
            task.attempted = attempted
            task.total = total
        self.taskProgressChanged.emit(task_id, attempted, total)
