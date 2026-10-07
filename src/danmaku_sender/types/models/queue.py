import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from .common import VideoTarget
from .danmaku import Danmaku


class TaskStatus(Enum):
    """队列任务状态"""
    UNCONFIGURED = "未配置"
    PENDING = "等待中"
    RUNNING = "发送中"
    PAUSED = "已暂停"
    COMPLETED = "已完成"
    FAILED = "失败"
    SKIPPED = "已跳过"

    @property
    def is_editable(self) -> bool:
        """结构可变（改弹幕、改配置、移动）的状态。

        UNCONFIGURED 与 SKIPPED 都表示「缺配置」，补完配置一律转回 PENDING。
        """
        return self in (TaskStatus.PENDING, TaskStatus.UNCONFIGURED, TaskStatus.SKIPPED)


@dataclass(frozen=True)
class TaskConfig:
    """任务工单的发送节奏参数（入队后不可变）。

    描述**单个任务**（一个视频）里弹幕怎么发：延迟、爆发、休息。
    队列级策略（跳过已发送、任务间隔、自动终止）作用于**整个任务队列**，
    见 :class:`danmaku_sender.config.SendPolicy`。

    由 ``SenderConfig.to_task_config()`` 派生，字段一一对应；
    反向转换见 ``SenderConfig.from_task_config()``。
    """
    min_delay: float
    max_delay: float
    burst_enabled: bool
    burst_size: int
    rest_min: float
    rest_max: float

    # 校验不在此处：types/ 一贯是纯数据类型，合法性由 config 层与
    # 表单边界保证（SenderConfig 校验后再派生本快照）。


@dataclass(frozen=True)
class TaskDefinition:
    """任务工单（入队后不可变）。

    Worker 只持有 TaskDefinition / TaskSnapshot，摸不到 TaskExecution。
    config 是入队那一刻定死的发送节奏，冻结类型，无需防御性拷贝。
    danmakus 为 tuple，结构上不可替换；发送管线须持有自己的 Danmaku 副本
    （见 SendJob 构造处的 clone），不得回填 dmid 写穿本工单。
    """
    task_id: str
    target: VideoTarget
    danmakus: tuple[Danmaku, ...]
    config: TaskConfig
    p_index: int = 0
    p_title: str = ""
    xml_path: Path | None = None
    duration_ms: int = 0

    @property
    def total(self) -> int:
        return len(self.danmakus)

    @property
    def is_config_complete(self) -> bool:
        """配置是否齐备可发：弹幕与视频目标都在。"""
        return self.total > 0 and self.target.is_assigned

    @property
    def missing_config_text(self) -> str:
        """缺失配置项的一句话说明；齐备时返回空字符串。

        表格提示、任务详情与 Worker 跳过原因共用这套文案，
        保证「缺什么」在各界面与日志里说法一致。
        """
        parts: list[str] = []
        if self.total <= 0:
            parts.append("未导入弹幕")
        if not self.target.is_assigned:
            parts.append("未指定视频目标")
        return "，且".join(parts)


@dataclass
class TaskExecution:
    """任务运行时（仅主线程 QueueState 可写）"""
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0


@dataclass
class Task:
    """队列里的一项：不可变工单 + 可变运行时"""
    definition: TaskDefinition
    execution: TaskExecution


@dataclass(frozen=True)
class TaskSnapshot:
    """Worker 启动时的一次性采样：status 在采样时定死，与后续主线程落账隔离。"""
    definition: TaskDefinition
    status: TaskStatus


class TaskView:
    """任务只读视图（live 门面）。

    属性实时读自 Task，表格 refresh_row 无需换对象即可看到新值。
    禁止缓存字段值做业务判断，更禁止经此写入——变更一律走 QueueState API。
    """
    __slots__ = ("_task",)

    def __init__(self, task: Task) -> None:
        self._task = task

    @property
    def task_id(self) -> str:
        return self._task.definition.task_id

    @property
    def target(self) -> VideoTarget:
        return self._task.definition.target

    @property
    def danmakus(self) -> tuple[Danmaku, ...]:
        return self._task.definition.danmakus

    @property
    def config(self) -> TaskConfig:
        """发送节奏参数（冻结，直接给出即可）。"""
        return self._task.definition.config

    @property
    def p_index(self) -> int:
        return self._task.definition.p_index

    @property
    def p_title(self) -> str:
        return self._task.definition.p_title

    @property
    def xml_path(self) -> Path | None:
        return self._task.definition.xml_path

    @property
    def duration_ms(self) -> int:
        return self._task.definition.duration_ms

    @property
    def total(self) -> int:
        return self._task.definition.total

    @property
    def is_config_complete(self) -> bool:
        """配置是否齐备可发：弹幕与视频目标都在。"""
        return self._task.definition.is_config_complete

    @property
    def missing_config_text(self) -> str:
        """缺失配置项的一句话说明；齐备时返回空字符串。"""
        return self._task.definition.missing_config_text

    @property
    def status(self) -> TaskStatus:
        return self._task.execution.status

    @property
    def error_msg(self) -> str:
        return self._task.execution.error_msg

    @property
    def attempted(self) -> int:
        return self._task.execution.attempted

    def to_draft(self) -> "TaskDraft":
        """拷贝为可变编辑沙盒（详情弹窗 / 构建弹窗用）"""
        definition = self._task.definition
        execution = self._task.execution
        return TaskDraft(
            target=replace(definition.target),
            danmakus=list(definition.danmakus),
            config_snapshot=definition.config,
            task_id=definition.task_id,
            p_index=definition.p_index,
            p_title=definition.p_title,
            xml_path=definition.xml_path,
            duration_ms=definition.duration_ms,
            status=execution.status,
            error_msg=execution.error_msg,
            attempted=execution.attempted,
        )

    def snapshot(self) -> TaskSnapshot:
        """定死当前 status 的不可变采样（Worker / 跨线程读取用）"""
        return TaskSnapshot(definition=self._task.definition, status=self._task.execution.status)


@dataclass
class TaskDraft:
    """构造期 / 编辑沙盒 DTO。

    仅用于「组装 → 入队」与「详情弹窗编辑」。入队后由 QueueState 拆成
    TaskDefinition + TaskExecution，本对象不再代表队列中的真实任务。
    """
    target: VideoTarget
    danmakus: list[Danmaku]
    config_snapshot: TaskConfig
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    p_index: int = 0
    p_title: str = ""
    xml_path: Path | None = None
    duration_ms: int = 0  # 视频时长（毫秒），用于弹幕时间越界校验
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0
    total: int = field(init=False)

    def __post_init__(self):
        self.total = len(self.danmakus)

    @property
    def is_config_complete(self) -> bool:
        """配置是否齐备可发：弹幕与视频目标都在。"""
        return self.total > 0 and self.target.is_assigned

    @property
    def missing_config_text(self) -> str:
        """缺失配置项的一句话说明；齐备时返回空字符串。"""
        parts: list[str] = []
        if self.total <= 0:
            parts.append("未导入弹幕")
        if not self.target.is_assigned:
            parts.append("未指定视频目标")
        return "，且".join(parts)

    @property
    def initial_status(self) -> TaskStatus:
        """按配置完整性给出的新建状态：齐备为待发，否则为未配置。"""
        return TaskStatus.PENDING if self.is_config_complete else TaskStatus.UNCONFIGURED

    def to_definition(self) -> TaskDefinition:
        """打成不可变工单（target 拷贝，config 本就冻结，弹幕收成 tuple）"""
        return TaskDefinition(
            task_id=self.task_id,
            target=replace(self.target),
            danmakus=tuple(self.danmakus),
            config=self.config_snapshot,
            p_index=self.p_index,
            p_title=self.p_title,
            xml_path=self.xml_path,
            duration_ms=self.duration_ms,
        )
