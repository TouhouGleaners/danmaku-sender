"""发送任务队列状态管理"""

import logging
from collections import Counter
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from danmaku_sender.types.models.common import RelativePosition
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    Task,
    TaskDraft,
    TaskExecution,
    TaskSnapshot,
    TaskStatus,
    TaskView,
)

logger = logging.getLogger(__name__)


class QueueState(QObject):
    """发送任务队列的响应式状态中心。

    所有任务数据变更必须通过本类的方法进行，
    以确保信号正确发射，所有观察者（发射器、监视器等）自动同步。

    内部存 Task = TaskDefinition(不可变工单) + TaskExecution(可变运行时)。
    对外只暴露 TaskView 只读门面。

    只允许主线程访问；给 Worker 数据用 snapshots() 取不可变拷贝。
    """

    # ── 信号 ──────────────────────────────────────────────
    tasksChanged = Signal()                      # 队列结构变更（增删排序）
    taskDataChanged = Signal(str)                # 任务数据变更（弹幕数、配置等）
    taskProgressChanged = Signal(str, int, int)  # (task_id, attempted, total)
    taskStatusChanged = Signal(str, TaskStatus)  # (task_id, TaskStatus 枚举)
    currentTaskChanged = Signal(int)             # 当前执行游标

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[Task] = []
        self._current_index: int = -1

    # ── 只读访问 ──────────────────────────────────────────

    @property
    def tasks(self) -> list[TaskView]:
        """只读视图列表。元素是 live 门面，可反复读到新值；禁止经此写入。"""
        return [TaskView(r) for r in self._tasks]

    def snapshots(
        self,
        statuses: Collection[TaskStatus],
    ) -> tuple[TaskSnapshot, ...]:
        """定死 status 的不可变采样，交给 Worker 后与后续变更隔离。"""
        return tuple(
            TaskSnapshot(definition=r.definition, status=r.execution.status)
            for r in self._tasks
            if r.execution.status in statuses
        )

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
        return sum(1 for r in self._tasks if r.execution.status == TaskStatus.PENDING)

    @property
    def has_pending_tasks(self) -> bool:
        """队列中是否有待发送的任务"""
        return any(r.execution.status == TaskStatus.PENDING for r in self._tasks)

    @property
    def has_startable_tasks(self) -> bool:
        """启动队列后是否存在可执行的任务。

        PENDING 与 PAUSED 均计入: `SenderController.start_queue` 启动时会把
        残留运行态转回 PENDING 再取快照，PAUSED 因此属于可启动范围。
        """
        return any(r.execution.status in (TaskStatus.PENDING, TaskStatus.PAUSED) for r in self._tasks)

    @property
    def total_danmaku_count(self) -> int:
        """全队列弹幕总数"""
        return sum(r.definition.total for r in self._tasks)

    @property
    def sendable_danmaku_count(self) -> int:
        """可发送弹幕总数（不含配置未完成的任务）。

        配置不完整的任务——无论此刻是 UNCONFIGURED 还是已被跳过
        ——都永远不会发，不能进发送进度的分母。
        判据取配置完整性而非运行时状态:
        被跳过的残缺任务状态已经变了，但照样发不出去。
        """
        return sum(r.definition.total for r in self._tasks if r.definition.is_config_complete)

    @property
    def processed_danmaku_count(self) -> int:
        """全队列已处理弹幕数（不含 PENDING、UNCONFIGURED 和 PAUSED）"""
        return sum(
            r.execution.attempted for r in self._tasks
            if r.execution.status not in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED, TaskStatus.PAUSED)
        )

    @property
    def status_counts(self) -> dict[TaskStatus, int]:
        """各状态的任务数量"""
        return dict(Counter(r.execution.status for r in self._tasks))

    # ── 查询 ─────────────────────────────────────────────

    def get_task_by_id(self, task_id: str) -> TaskView | None:
        """按 ID 查找任务"""
        record = self._find(task_id)
        return TaskView(record) if record else None

    def _find_index(self, task_id: str) -> int | None:
        """按 task_id 查找索引；不存在返回 None。

        Args:
            task_id (str): 任务标识。

        Returns:
            int | None: 命中的索引。
        """
        for i, record in enumerate(self._tasks):
            if record.definition.task_id == task_id:
                return i
        return None

    def _find(self, task_id: str) -> Task | None:
        """按 task_id 查找存储单元；不存在返回 None。

        Args:
            task_id (str): 任务标识。

        Returns:
            Task | None: 命中的存储单元。
        """
        index = self._find_index(task_id)
        return self._tasks[index] if index is not None else None

    # ── 结构变更（发射 tasksChanged）──────────────────────

    def add_task(self, task: TaskDraft):
        """添加任务到队列末尾（入队瞬间拆成 Spec + Runtime）。

        入队时按配置完整性对齐状态，
        不信任草稿自带的 status——配置残缺的任务不可能以待发进队。
        """
        record = self._to_task(task)
        self._reconcile_config_status(record)
        self._tasks.append(record)
        self.tasksChanged.emit()
        logger.info(
            f"任务已加入队列: [{record.definition.task_id}] "
            f"{record.definition.display_string} ({record.definition.total} 条弹幕)"
        )

    def insert_task(self, task: TaskDraft, ref_task_id: str, position: RelativePosition = RelativePosition.BELOW):
        """在参考任务上方/下方插入；参考不存在时追加到末尾。

        这是队列插入的唯一公开入口，调用方不接触绝对下标。
        入队时按配置完整性对齐状态，不信任草稿自带的 status。

        Args:
            task (TaskDraft): 任务草稿，入队时拆成不可变工单与可变运行时。
            ref_task_id (str): 参考任务标识。
            position (RelativePosition): 插在参考任务的哪一侧，默认 BELOW。

        Raises:
            ValueError: position 不是 ABOVE / BELOW。
        """
        record = self._to_task(task)
        self._reconcile_config_status(record)

        match position:
            case RelativePosition.ABOVE:
                offset = 0
            case RelativePosition.BELOW:
                offset = 1
            case _:
                raise ValueError(f"未知的相对位置: {position!r}")

        # 查找参考任务索引
        ref_index = self._find_index(ref_task_id)

        # 计算实际插入位置
        insert_index = len(self._tasks) if ref_index is None else ref_index + offset

        # 执行插入
        self._tasks.insert(insert_index, record)

        self.tasksChanged.emit()
        logger.info(
            f"任务已插入队列 (相对 {ref_task_id} {position.value}): [{record.definition.task_id}] "
            f"{record.definition.display_string} ({record.definition.total} 条弹幕)"
        )

    def remove_task(self, task_id: str):
        """移除指定任务(非 RUNNING 任务)

        Args:
            task_id (str): 要移除的任务标识。
        """
        index = self._find_index(task_id)
        if index is None:
            logger.warning(f"移除任务失败: 找不到任务 [{task_id}]")
            return

        if self._tasks[index].execution.status is TaskStatus.RUNNING:
            logger.warning(f"移除任务失败: 任务 [{task_id}] 正在发送中，无法移除。")
            return

        self._tasks.pop(index)
        self.tasksChanged.emit()
        logger.info(f"任务已从队列移除: [{task_id}]")

    def move_task(self, task_id: str, toward: RelativePosition):
        """上下移动一个任务；相邻项不可编辑时不动。

        Args:
            task_id (str): 要移动的任务标识。
            toward (RelativePosition): 移向参考项的哪一侧，ABOVE 为上移，BELOW 为下移。
        """
        match toward:
            case RelativePosition.ABOVE:
                offset = -1
            case RelativePosition.BELOW:
                offset = 1
            case _:
                raise ValueError(f"未知的相对位置: {toward!r}")

        # 目标任务索引
        index = self._find_index(task_id)

        # 目标任务不存在
        if index is None:
            logger.warning(f"移动任务失败: 找不到任务 [{task_id}]")
            return

        # 目标任务不可编辑
        if not self._tasks[index].execution.status.is_editable:
            logger.warning(f"移动任务失败: 任务 [{task_id}] 状态为 {self._tasks[index].execution.status.value}，不可编辑。")
            return

        # 校验目标位置是否越界
        new_index = index + offset
        if not (0 <= new_index < len(self._tasks)):
            logger.warning(f"移动任务失败: 任务 [{task_id}] 已在队列最{toward.value}。")
            return

        # 校验相邻任务是否可编辑
        adjacent_task = self._tasks[new_index]
        if not adjacent_task.execution.status.is_editable:
            logger.warning(f"移动任务失败: 相邻任务 [{adjacent_task.definition.task_id}] 状态为 {adjacent_task.execution.status.value}，不可编辑。")
            return

        self._tasks[index], self._tasks[new_index] = self._tasks[new_index], self._tasks[index]
        self.tasksChanged.emit()

    def reorder_tasks(self, task_ids: list[str]):
        """按给定的 task_id 顺序重排；列表必须是当前队列的全排列。"""
        by_id = {r.definition.task_id: r for r in self._tasks}
        if set(task_ids) != set(by_id) or len(task_ids) != len(self._tasks):
            logger.warning("reorder_tasks 忽略: task_id 列表与当前队列不一致。")
            return
        self._tasks = [by_id[tid] for tid in task_ids]
        self.tasksChanged.emit()

    def clear_all(self):
        """清空整个队列（所有状态的任务都移除）"""
        removed = len(self._tasks)
        if removed == 0:
            return
        self._tasks.clear()
        self.tasksChanged.emit()
        logger.info(f"已清空队列（{removed} 个任务）")

    def reset_queue(self):
        """重置队列: 移除已完成、失败任务转待发。

        SKIPPED / UNCONFIGURED 保留——它们缺配置，转待发没有意义；
        PENDING / PAUSED / RUNNING 不动。转待发清零进度与错误信息，
        失败任务按工单从头再发。
        """
        revived: list[str] = []
        removed = 0
        kept: list[Task] = []
        for record in self._tasks:
            if record.execution.status is TaskStatus.COMPLETED:
                removed += 1
                continue
            if record.execution.status is TaskStatus.FAILED:
                record.execution.status = TaskStatus.PENDING
                record.execution.error_msg = ""
                record.execution.attempted = 0
                revived.append(record.definition.task_id)
            kept.append(record)
        self._tasks = kept

        if not removed and not revived:
            return
        for task_id in revived:
            self.taskStatusChanged.emit(task_id, TaskStatus.PENDING)
        self.tasksChanged.emit()
        logger.info(f"队列已重置: 移除 {removed} 个已完成任务，{len(revived)} 个失败任务转待发")

    # ── 数据变更（发射 taskDataChanged）───────────────────────

    def assign_danmakus(self, task_id: str, danmakus: list[Danmaku], xml_path: Path | None = None):
        """为任务分配/更新弹幕列表（换新 Spec），自动联动就绪状态。

        拖放 XML、编辑器保存等场景的统一入口。
        弹幕与视频目标**都**齐备才会转待发，只有弹幕仍停在未配置。
        """
        record = self._find(task_id)
        if record is None:
            return

        if not record.execution.status.is_editable:
            return

        record.definition = replace(
            record.definition,
            danmakus=tuple(danmakus),
            meta=replace(
                record.definition.meta,
                xml_path=xml_path if xml_path is not None else record.definition.meta.xml_path,
            ),
        )
        if self._reconcile_config_status(record):
            self.taskStatusChanged.emit(record.definition.task_id, record.execution.status)

        self.taskDataChanged.emit(task_id)
        logger.info(f"已分配弹幕: {task_id} ({record.definition.total} 条)")

    def apply_edit(self, task_id: str, source: TaskDraft):
        """全量应用来自详情弹窗沙盒的修改结果（换新 Spec）。

        发送中等非可编辑状态拒绝并记警告，队列保持原样。
        """
        record = self._find(task_id)
        if record is None:
            return
        if not record.execution.status.is_editable:
            logger.warning(f"任务 [{task_id}] 处于 {record.execution.status.value}，已忽略编辑结果。")
            return

        old_status = record.execution.status
        # 以队列中的 task_id 为准，防止沙盒误带其它 id
        record.definition = replace(source.to_definition(), task_id=task_id)
        record.execution.status = source.status
        record.execution.error_msg = source.error_msg
        self._reconcile_config_status(record)

        if record.execution.status != old_status:
            self.taskStatusChanged.emit(task_id, record.execution.status)
        self.taskDataChanged.emit(task_id)

    def _reconcile_config_status(self, record: Task) -> bool:
        """按配置完整性对齐预运行状态；返回状态是否变化。

        配置齐备（弹幕 + 视频目标）的 UNCONFIGURED / SKIPPED 转回 PENDING；
        配置被拆掉的 PENDING 降回 UNCONFIGURED。终态与运行态不在此处理
        ——结构编辑有 is_editable 闸门，本方法只在配置变更后调用。

        Args:
            record: 待对齐的队列存储单元，就地修改其运行时状态。

        Returns:
            bool: 状态发生变化返回 True。
        """
        status = record.execution.status
        complete = record.definition.is_config_complete

        if complete and status in (TaskStatus.UNCONFIGURED, TaskStatus.SKIPPED):
            record.execution.status = TaskStatus.PENDING
            record.execution.error_msg = ""
            return True
        if not complete and status is TaskStatus.PENDING:
            record.execution.status = TaskStatus.UNCONFIGURED
            return True
        return False

    # ── 状态变更（发射 taskStatusChanged）─────────────────

    def update_task_status(self, task_id: str, status: TaskStatus, error_msg: str = ""):
        """更新任务状态"""
        record = self._find(task_id)
        if record is None:
            return
        record.execution.status = status
        record.execution.error_msg = error_msg
        self.taskStatusChanged.emit(task_id, status)

    def update_task_progress(self, task_id: str, attempted: int, total: int):
        """更新发送进度并通知观察者（total 以 Spec 为准，入参仅作展示一致校验）"""
        record = self._find(task_id)
        if record is None:
            return
        record.execution.attempted = attempted
        actual_total = record.definition.total or total
        self.taskProgressChanged.emit(task_id, attempted, actual_total)

    # ── 内部转换 ─────────────────────────────────────────

    @staticmethod
    def _to_task(task: TaskDraft) -> Task:
        """草稿 → 队列里的一项。运行时字段随草稿带入（UNCONFIGURED 等）。"""
        return Task(
            definition=task.to_definition(),
            execution=TaskExecution(
                status=task.status,
                error_msg=task.error_msg,
                attempted=task.attempted,
            ),
        )
