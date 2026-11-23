"""发送任务队列状态管理"""

import logging
import uuid
from collections import Counter
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from danmaku_sender.types.models.common import RelativePosition
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    DanmakuPack,
    Task,
    TaskDraft,
    TaskState,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class QueueState(QObject):
    """发送任务队列的响应式状态中心。

    所有任务数据变更必须通过本类的方法进行，
    以确保信号正确发射，所有观察者（发射器、监视器等）自动同步。

    内部存 Task（task_id + 四个抽屉，见 Task），整体是冻结值对象：
    变更一律换新实例，经信号把新值交给观察者。

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
    def tasks(self) -> list[Task]:
        """只读任务列表

        Task 为不可变对象，状态变更后需重新获取以读取最新实例。
        """
        return list(self._tasks)

    def snapshots(
        self,
        statuses: Collection[TaskStatus],
    ) -> tuple[Task, ...]:
        """取定状态的不可变拷贝，交给 Worker 后与后续变更隔离。"""
        return tuple(r for r in self._tasks if r.status in statuses)

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
        return sum(1 for r in self._tasks if r.status == TaskStatus.PENDING)

    @property
    def has_pending_tasks(self) -> bool:
        """队列中是否有待发送的任务"""
        return any(r.status == TaskStatus.PENDING for r in self._tasks)

    @property
    def has_startable_tasks(self) -> bool:
        """启动队列后是否存在可执行的任务。

        PENDING 与 PAUSED 均计入: `SenderController.start_queue` 启动时会把
        残留运行态转回 PENDING 再取快照，PAUSED 因此属于可启动范围。
        """
        return any(r.status in (TaskStatus.PENDING, TaskStatus.PAUSED) for r in self._tasks)

    @property
    def total_danmaku_count(self) -> int:
        """全队列弹幕总数"""
        return sum(r.total for r in self._tasks)

    @property
    def sendable_danmaku_count(self) -> int:
        """可发送弹幕总数（不含配置未完成的任务）。

        配置不完整的任务——无论此刻是 UNCONFIGURED 还是已被跳过
        ——都永远不会发，不能进发送进度的分母。
        判据取配置完整性而非运行时状态:
        被跳过的残缺任务状态已经变了，但照样发不出去。
        """
        return sum(r.total for r in self._tasks if r.is_config_complete)

    @property
    def processed_danmaku_count(self) -> int:
        """全队列已处理弹幕数（各任务游标之和，含未跑完的任务）。

        断点续传下 PENDING / PAUSED 任务也带着游标，不能按状态排除，
        否则启动队列那一刻进度条会倒退。
        """
        return sum(r.cursor for r in self._tasks)

    @property
    def status_counts(self) -> dict[TaskStatus, int]:
        """各状态的任务数量"""
        return dict(Counter(r.status for r in self._tasks))

    # ── 查询 ─────────────────────────────────────────────

    def get_task_by_id(self, task_id: str) -> Task | None:
        """按 ID 查找任务"""
        return self._find(task_id)

    def _find_index(self, task_id: str) -> int | None:
        """按 task_id 查找索引；不存在返回 None。

        Args:
            task_id (str): 任务标识。

        Returns:
            int | None: 命中的索引。
        """
        for i, record in enumerate(self._tasks):
            if record.task_id == task_id:
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

    def insert_index_for(self, ref_task_id: str, position: RelativePosition) -> int:
        """计算相对参考任务的插入位置索引；参考任务不存在时返回队列末尾索引。

        该方法只读不改状态，供持久化与内存插入共用同一定位规则。

        Args:
            ref_task_id (str): 参考任务标识。
            position (RelativePosition): 插入在参考任务的上方或下方。

        Returns:
            int: 计算得到的 0-based 插入位置索引。

        Raises:
            ValueError: ``position`` 不是 ABOVE 或 BELOW。
        """
        match position:
            case RelativePosition.ABOVE:
                offset = 0
            case RelativePosition.BELOW:
                offset = 1
            case _:
                raise ValueError(f"未知的相对位置: {position!r}")
        ref_index = self._find_index(ref_task_id)
        return len(self._tasks) if ref_index is None else ref_index + offset

    def order_with_move(self, task_id: str, toward: RelativePosition) -> list[str] | None:
        """计算上下移动指定任务后的全队列 task_id 顺序；不可移动时返回 None。

        该方法只读不改状态，供持久化与内存移动共用同一校验与重排规则（需自身与相邻任务均处于可编辑状态，且目标位置不越界）。

        Args:
            task_id (str): 待移动的任务标识。
            toward (RelativePosition): 移动方向，ABOVE 为上移，BELOW 为下移。

        Returns:
            list[str] | None: 移动后的 task_id 顺序列表；无法移动时返回 None。

        Raises:
            ValueError: ``toward`` 不是 ABOVE 或 BELOW。
        """
        match toward:
            case RelativePosition.ABOVE:
                offset = -1
            case RelativePosition.BELOW:
                offset = 1
            case _:
                raise ValueError(f"未知的相对位置: {toward!r}")

        index = self._find_index(task_id)
        if index is None:
            logger.warning(f"移动任务失败: 找不到任务 [{task_id}]")
            return None

        if not self._tasks[index].status.is_editable:
            logger.warning(f"移动任务失败: 任务 [{task_id}] 状态为 {self._tasks[index].status.value}，不可编辑。")
            return None

        new_index = index + offset
        if not (0 <= new_index < len(self._tasks)):
            logger.warning(f"移动任务失败: 任务 [{task_id}] 已在队列最{toward.value}。")
            return None

        adjacent_task = self._tasks[new_index]
        if not adjacent_task.status.is_editable:
            logger.warning(f"移动任务失败: 相邻任务 [{adjacent_task.task_id}] 状态为 {adjacent_task.status.value}，不可编辑。")
            return None

        order = [r.task_id for r in self._tasks]
        order[index], order[new_index] = order[new_index], order[index]
        return order

    # ── 结构变更（发射 tasksChanged）──────────────────────

    def restore_tasks(self, tasks: list[Task]):
        """批量恢复持久化任务到队列，覆盖现有内容并发射一次 tasksChanged。

        恢复时将按配置完整性重新对齐待运行状态，运行中/已暂停状态与游标保持原值。

        Args:
            tasks (list[Task]): 按队列顺序排列的待恢复任务列表。
        """
        self._tasks = [self._sync_config_status(record) for record in tasks]
        self.tasksChanged.emit()
        logger.info(f"队列已恢复: {len(self._tasks)} 个任务")

    def add_task(self, task: TaskDraft):
        """添加任务到队列末尾（入队瞬间打成不可变任务）。

        入队时按配置完整性对齐状态，
        不信任草稿自带的 status——配置残缺的任务不可能以待发进队。
        """
        record = self._sync_config_status(task.to_task())
        self._tasks.append(record)
        self.tasksChanged.emit()
        logger.info(
            f"任务已加入队列: [{record.task_id}] "
            f"{record.display_string} ({record.total} 条弹幕)"
        )

    def insert_task(self, task: TaskDraft, ref_task_id: str, position: RelativePosition = RelativePosition.BELOW):
        """在参考任务上方/下方插入；参考不存在时追加到末尾。

        这是队列插入的唯一公开入口，调用方不接触绝对索引。
        入队时按配置完整性对齐状态，不信任草稿自带的 status。

        Args:
            task (TaskDraft): 任务草稿，入队时打成不可变任务。
            ref_task_id (str): 参考任务标识。
            position (RelativePosition): 插在参考任务的哪一侧，默认 BELOW。

        Raises:
            ValueError: position 不是 ABOVE / BELOW。
        """
        record = self._sync_config_status(task.to_task())

        self._tasks.insert(self.insert_index_for(ref_task_id, position), record)

        self.tasksChanged.emit()
        logger.info(
            f"任务已插入队列 (相对 {ref_task_id} {position.value}): [{record.task_id}] "
            f"{record.display_string} ({record.total} 条弹幕)"
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

        if self._tasks[index].status is TaskStatus.RUNNING:
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
        order = self.order_with_move(task_id, toward)
        if order is None:
            return
        by_id = {r.task_id: r for r in self._tasks}
        self._tasks = [by_id[tid] for tid in order]
        self.tasksChanged.emit()

    def reorder_tasks(self, task_ids: list[str]):
        """按给定的 task_id 顺序重排；列表必须是当前队列的全排列。"""
        by_id = {r.task_id: r for r in self._tasks}
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
        失败任务按任务定义从头再发。
        """
        revived: list[str] = []
        removed = 0
        kept: list[Task] = []
        for record in self._tasks:
            if record.status is TaskStatus.COMPLETED:
                removed += 1
                continue
            if record.status is TaskStatus.FAILED:
                record = replace(record, state=TaskState(status=TaskStatus.PENDING))
                revived.append(record.task_id)
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
        换了弹幕列表则游标归零——旧游标会指进新列表的中段。
        """
        index = self._find_index(task_id)
        if index is None:
            return

        record = self._tasks[index]
        if not record.status.is_editable:
            return

        new_danmakus = tuple(danmakus)
        state = record.state
        if new_danmakus != record.danmakus:
            state = replace(state, cursor=0)

        pack = DanmakuPack(
            items=new_danmakus,
            source_path=xml_path if xml_path is not None else record.pack.source_path,
        )
        old_status = record.status
        record = self._sync_config_status(replace(record, pack=pack, state=state))
        self._tasks[index] = record
        if record.status != old_status:
            self.taskStatusChanged.emit(task_id, record.status)

        self.taskDataChanged.emit(task_id)
        logger.info(f"已分配弹幕: {task_id} ({record.total} 条)")

    def apply_edit(self, task_id: str, source: TaskDraft, new_id: str | None = None):
        """应用任务详情弹窗的修改结果。

        若任务处于不可编辑状态则忽略修改并记录警告。
        当原有的已指定目标发生变更时，将另立新的 task_id 以避免历史发送记录错配；
        外部持久化已预先生成 ``new_id`` 时直接沿用，未传入则在内部生成。
        若更换了 task_id 或弹幕列表，游标将同步归零。
        """
        index = self._find_index(task_id)
        if index is None:
            return
        record = self._tasks[index]
        if not record.status.is_editable:
            logger.warning(f"任务 [{task_id}] 处于 {record.status.value}，已忽略编辑结果。")
            return

        old_status = record.status
        old_target = record.target
        # 未指定目标时填上是补配置，不算换任务；其余情况以队列中的 task_id 为准
        replaced = old_target is not None and source.target != old_target
        if new_id is None:
            new_id = uuid.uuid4().hex if replaced else task_id
        incoming = replace(source.to_task(), task_id=new_id)
        state = replace(record.state, status=source.status, error_msg=source.error_msg)
        if new_id != task_id or incoming.danmakus != record.danmakus:
            # 换任务或换弹幕列表，旧游标都不再指得准：前者换了目标视频，后者会指进新列表的中段
            state = replace(state, cursor=0)
        record = self._sync_config_status(replace(incoming, state=state))
        self._tasks[index] = record

        if record.status != old_status:
            self.taskStatusChanged.emit(new_id, record.status)
        if new_id != task_id:
            # 换号后表格行的任务标识要整体刷新
            self.tasksChanged.emit()
        self.taskDataChanged.emit(new_id)

    @staticmethod
    def aligned_status(status: TaskStatus, error_msg: str, complete: bool) -> tuple[TaskStatus, str]:
        """根据配置完整性对齐待运行任务的预备状态。

        配置齐备的 UNCONFIGURED / SKIPPED 任务自动转为 PENDING 并清空错误说明；
        配置不再齐备的 PENDING 任务回退为 UNCONFIGURED，其余状态保持不变。
        持久化层与内存状态树共用此规则，确保两端状态一致。

        Args:
            status (TaskStatus): 对齐前的任务状态。
            error_msg (str): 对齐前的错误说明。
            complete (bool): 目标与弹幕配置是否均已齐备。

        Returns:
            tuple[TaskStatus, str]: 对齐后的 (状态, 错误说明)。
        """
        match (status, complete):
            case (TaskStatus.UNCONFIGURED | TaskStatus.SKIPPED, True):
                return TaskStatus.PENDING, ""
            case (TaskStatus.PENDING, False):
                return TaskStatus.UNCONFIGURED, error_msg
            case _:
                return status, error_msg

    def _sync_config_status(self, record: Task) -> Task:
        """按配置完整性对齐预运行状态，返回对齐后的任务。

        终态与运行态不在此处理——结构编辑有 is_editable 闸门，本方法只在配置变更后调用。

        Args:
            record: 待对齐的任务。

        Returns:
            Task: 对齐后的任务。
        """
        status, error_msg = self.aligned_status(
            record.status,
            record.error_msg,
            record.is_config_complete,
        )
        return replace(record, state=replace(record.state, status=status, error_msg=error_msg))

    # ── 状态变更（发射 taskStatusChanged）─────────────────

    def update_task_status(self, task_id: str, status: TaskStatus, error_msg: str = ""):
        """更新任务状态"""
        index = self._find_index(task_id)
        if index is None:
            return
        record = self._tasks[index]
        self._tasks[index] = replace(
            record, state=replace(record.state, status=status, error_msg=error_msg)
        )
        self.taskStatusChanged.emit(task_id, status)

    def update_task_progress(self, task_id: str, cursor: int, total: int):
        """更新发送进度并通知观察者（total 以弹幕包为准，入参仅作展示一致校验）"""
        index = self._find_index(task_id)
        if index is None:
            return
        record = self._tasks[index]
        self._tasks[index] = replace(record, state=replace(record.state, cursor=cursor))
        actual_total = record.total or total
        self.taskProgressChanged.emit(task_id, cursor, actual_total)

    def reset_progress(self, task_id: str):
        """清零任务的发送进度游标，下次启动从头发。"""
        index = self._find_index(task_id)
        if index is None:
            return
        record = self._tasks[index]
        self._tasks[index] = replace(record, state=replace(record.state, cursor=0))
        self.taskProgressChanged.emit(task_id, 0, record.total)
