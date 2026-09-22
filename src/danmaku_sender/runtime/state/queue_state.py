"""发送任务队列状态管理"""

import logging
import threading
from collections import Counter
from collections.abc import Collection
from dataclasses import replace

from PySide6.QtCore import QObject, Signal

from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    InsertPosition,
    QueueTask,
    TaskRecord,
    TaskRuntime,
    TaskSnapshot,
    TaskStatus,
    TaskView,
)

logger = logging.getLogger(__name__)

# 结构可变（增删/改弹幕/改配置）只允许在这些状态下进行
_EDITABLE_STATUSES = (TaskStatus.PENDING, TaskStatus.UNCONFIGURED)


class QueueState(QObject):
    """发送任务队列的响应式状态中心。

    所有任务数据变更必须通过本类的方法进行，
    以确保信号正确发射，所有观察者（发射器、监视器等）自动同步。

    内部存 TaskRecord = TaskSpec(不可变工单) + TaskRuntime(可变运行时)。
    对外只暴露 TaskView 只读门面；跨线程读取用 snapshots()。
    QueueState 只允许在主线程变更。
    """

    # ── 信号 ──────────────────────────────────────────────
    tasksChanged = Signal()                      # 队列结构变更（增删排序）
    taskDataChanged = Signal(str)                # 任务数据变更（弹幕数、配置等）
    taskProgressChanged = Signal(str, int, int)  # (task_id, attempted, total)
    taskStatusChanged = Signal(str, TaskStatus)  # (task_id, TaskStatus 枚举)
    currentTaskChanged = Signal(int)             # 当前执行游标

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[TaskRecord] = []
        self._current_index: int = -1
        self._lock = threading.RLock()

    # ── 只读访问 ──────────────────────────────────────────

    @property
    def tasks(self) -> list[TaskView]:
        """只读视图列表。元素是 live 门面，可反复读到新值；禁止经此写入。"""
        with self._lock:
            return [TaskView(r) for r in self._records]

    def snapshots(
        self,
        statuses: Collection[TaskStatus],
    ) -> tuple[TaskSnapshot, ...]:
        """锁内定死 status 的不可变采样，供 Worker 等跨线程消费者使用。"""
        with self._lock:
            return tuple(
                TaskSnapshot(spec=r.spec, status=r.runtime.status)
                for r in self._records
                if r.runtime.status in statuses
            )

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
            return len(self._records) == 0

    # ── 统计属性 ──────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        """等待发送的任务数"""
        with self._lock:
            return sum(1 for r in self._records if r.runtime.status == TaskStatus.PENDING)

    @property
    def has_pending_tasks(self) -> bool:
        """队列中是否有待发送的任务"""
        with self._lock:
            return any(r.runtime.status == TaskStatus.PENDING for r in self._records)

    @property
    def total_danmaku_count(self) -> int:
        """全队列弹幕总数"""
        with self._lock:
            return sum(r.spec.total for r in self._records)

    @property
    def processed_danmaku_count(self) -> int:
        """全队列已处理弹幕数（不含 PENDING、UNCONFIGURED 和 PAUSED）"""
        with self._lock:
            return sum(
                r.runtime.attempted for r in self._records
                if r.runtime.status not in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED, TaskStatus.PAUSED)
            )

    @property
    def status_counts(self) -> dict[TaskStatus, int]:
        """各状态的任务数量"""
        counts: dict[TaskStatus, int] = Counter()
        with self._lock:
            for r in self._records:
                counts[r.runtime.status] += 1
        return dict(counts)

    # ── 查询 ─────────────────────────────────────────────

    def get_task_by_id(self, task_id: str) -> TaskView | None:
        """按 ID 查找任务"""
        with self._lock:
            record = self._find(task_id)
            return TaskView(record) if record else None

    def _find(self, task_id: str) -> TaskRecord | None:
        """调用方必须已持有 self._lock"""
        for record in self._records:
            if record.spec.task_id == task_id:
                return record
        return None

    # ── 结构变更（发射 tasksChanged）──────────────────────

    def add_task(self, task: QueueTask):
        """添加任务到队列末尾（入队瞬间拆成 Spec + Runtime）"""
        record = self._to_record(task)
        with self._lock:
            self._records.append(record)
        self.tasksChanged.emit()
        logger.info(
            f"任务已加入队列: [{record.spec.task_id}] "
            f"{record.spec.target.display_string} ({record.spec.total} 条弹幕)"
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
        record = self._to_record(task)
        with self._lock:
            ref_index = -1
            for i, r in enumerate(self._records):
                if r.spec.task_id == ref_task_id:
                    ref_index = i
                    break
            if ref_index < 0:
                self._records.append(record)
            else:
                index = ref_index if position is InsertPosition.ABOVE else ref_index + 1
                if index >= len(self._records):
                    self._records.append(record)
                else:
                    self._records.insert(max(0, index), record)
        self.tasksChanged.emit()
        logger.info(
            f"任务已插入队列 (相对 {ref_task_id} {position.name}): [{record.spec.task_id}] "
            f"{record.spec.target.display_string} ({record.spec.total} 条弹幕)"
        )

    def remove_task(self, task_id: str) -> bool:
        """移除指定任务（仅 PENDING/UNCONFIGURED 状态可移除）"""
        removed = False
        with self._lock:
            for i, r in enumerate(self._records):
                if r.spec.task_id == task_id and r.runtime.status in _EDITABLE_STATUSES:
                    self._records.pop(i)
                    removed = True
                    break
        if removed:
            self.tasksChanged.emit()
            logger.info(f"任务已从队列移除: [{task_id}]")
        return removed

    def move_task(self, task_id: str, direction: int) -> bool:
        """移动任务位置（direction: -1 上移, +1 下移）"""
        moved = False
        with self._lock:
            for i, r in enumerate(self._records):
                if r.spec.task_id == task_id and r.runtime.status in _EDITABLE_STATUSES:
                    new_index = i + direction
                    if (
                        0 <= new_index < len(self._records)
                        and self._records[new_index].runtime.status in _EDITABLE_STATUSES
                    ):
                        self._records[i], self._records[new_index] = (
                            self._records[new_index], self._records[i]
                        )
                        moved = True
                    break
        if moved:
            self.tasksChanged.emit()
        return moved

    def reorder_tasks(self, task_ids: list[str]):
        """按给定的 task_id 顺序重排；列表必须是当前队列的全排列。"""
        with self._lock:
            by_id = {r.spec.task_id: r for r in self._records}
            if set(task_ids) != set(by_id) or len(task_ids) != len(self._records):
                logger.warning("reorder_tasks 忽略：task_id 列表与当前队列不一致。")
                return
            self._records = [by_id[tid] for tid in task_ids]
        self.tasksChanged.emit()

    def clear_completed(self):
        """清除已完成/失败/跳过的任务（保留 PENDING、PAUSED、UNCONFIGURED）"""
        removed = 0
        with self._lock:
            before = len(self._records)
            self._records = [
                r for r in self._records
                if r.runtime.status in (TaskStatus.PENDING, TaskStatus.PAUSED, TaskStatus.UNCONFIGURED)
            ]
            removed = before - len(self._records)
        if removed > 0:
            self.tasksChanged.emit()
            logger.info(f"已清除 {removed} 个已完成任务")

    # ── 数据变更（发射 taskDataChanged）───────────────────────

    def assign_danmakus(self, task_id: str, danmakus: list[Danmaku], xml_path: str = ""):
        """为任务分配/更新弹幕列表（换新 Spec），自动联动就绪状态。

        拖放 XML、编辑器保存等场景的统一入口。
        """
        need_status = False
        total = 0
        with self._lock:
            record = self._find(task_id)
            if record is None or record.runtime.status not in _EDITABLE_STATUSES:
                return
            record.spec = replace(
                record.spec,
                danmakus=tuple(danmakus),
                xml_path=xml_path or record.spec.xml_path,
            )
            total = record.spec.total
            need_status = record.runtime.status == TaskStatus.UNCONFIGURED and total > 0

        if need_status:
            self.update_task_status(task_id, TaskStatus.PENDING)

        self.taskDataChanged.emit(task_id)
        logger.info(f"已分配弹幕: {task_id} ({total} 条)")

    def apply_edit(self, task_id: str, source: QueueTask) -> bool:
        """全量应用来自详情弹窗沙盒的修改结果（换新 Spec）。

        发送中等非可编辑状态拒绝，返回 False。
        """
        old_status: TaskStatus | None = None
        new_status: TaskStatus | None = None
        error_msg = ""
        with self._lock:
            record = self._find(task_id)
            if record is None:
                return False
            if record.runtime.status not in _EDITABLE_STATUSES:
                logger.warning(f"任务 [{task_id}] 处于 {record.runtime.status.value}，已忽略编辑结果。")
                return False

            old_status = record.runtime.status
            # 以队列中的 task_id 为准，防止沙盒误带其它 id
            record.spec = replace(source.to_spec(), task_id=task_id)
            new_status = source.status
            error_msg = source.error_msg
            record.runtime.status = new_status
            record.runtime.error_msg = error_msg

        if new_status != old_status:
            self.taskStatusChanged.emit(task_id, new_status)
        self.taskDataChanged.emit(task_id)
        return True

    # ── 状态变更（发射 taskStatusChanged）─────────────────

    def update_task_status(self, task_id: str, status: TaskStatus, error_msg: str = ""):
        """更新任务状态"""
        with self._lock:
            record = self._find(task_id)
            if record is None:
                return
            record.runtime.status = status
            record.runtime.error_msg = error_msg
        self.taskStatusChanged.emit(task_id, status)

    def update_task_progress(self, task_id: str, attempted: int, total: int):
        """更新发送进度并通知观察者（total 以 Spec 为准，入参仅作展示一致校验）"""
        with self._lock:
            record = self._find(task_id)
            if record is None:
                return
            record.runtime.attempted = attempted
            actual_total = record.spec.total or total
        self.taskProgressChanged.emit(task_id, attempted, actual_total)

    # ── 内部转换 ─────────────────────────────────────────

    @staticmethod
    def _to_record(task: QueueTask) -> TaskRecord:
        """草稿 → 存储单元。运行时字段随草稿带入（UNCONFIGURED 等）。"""
        return TaskRecord(
            spec=task.to_spec(),
            runtime=TaskRuntime(
                status=task.status,
                error_msg=task.error_msg,
                attempted=task.attempted,
            ),
        )
