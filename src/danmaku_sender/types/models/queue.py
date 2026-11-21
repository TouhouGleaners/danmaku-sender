import uuid
from dataclasses import dataclass, field, replace
from enum import Enum

from .common import TaskMeta, VideoTarget
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
    """任务的发送节奏参数（入队后不可变）。

    描述**单个任务**（一个视频）内弹幕的发送方式：延迟、爆发、休息。
    队列级策略（跳过已发送、任务间隔）作用于**整个任务队列**，
    见 :class:`danmaku_sender.config.SenderConfig.QueueConfig`。

    由 ``SenderConfig.PacingConfig.to_task_config()`` 派生，字段一一对应；
    反向转换见 ``SenderConfig.PacingConfig.from_task_config()``。

    Attributes:
        min_delay (float): 相邻两条弹幕的最小间隔（秒）。
        max_delay (float): 相邻两条弹幕的最大间隔（秒）。
        burst_enabled (bool): 是否启用爆发模式。
        burst_size (int): 爆发模式每轮连续发送的条数。
        rest_min (float): 爆发模式每轮之间的最短休息（秒）。
        rest_max (float): 爆发模式每轮之间的最长休息（秒）。
    """
    min_delay: float
    max_delay: float
    burst_enabled: bool
    burst_size: int
    rest_min: float
    rest_max: float

    # 校验不在此处：types/ 一贯是纯数据类型，合法性由 config 层与
    # 表单边界保证（SenderConfig 校验后再派生本快照）。


@dataclass(frozen=True, kw_only=True)
class TaskDefinition:
    """不可变任务定义。

    Worker 仅持有不可变任务副本，与主线程的后续变更隔离。
    config 为入队时固化的发送节奏，无需防御性拷贝。
    danmakus 为不可变元组；
    SendPipeline 需持有独立副本（见 SendJob 构造），不得向本对象回填 dmid。
    """
    task_id: str
    target: VideoTarget
    meta: TaskMeta = field(default_factory=TaskMeta)
    danmakus: tuple[Danmaku, ...] = ()
    config: TaskConfig

    @property
    def total(self) -> int:
        return len(self.danmakus)

    @property
    def display_string(self) -> str:
        """日志显示：视频标题 → BVID → 未指定。"""
        return self.meta.video_title or self.target.bvid or "未指定视频目标"

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


@dataclass(frozen=True)
class TaskExecution:
    """任务运行时（仅主线程 QueueState 可写）

    Attributes:
        status (TaskStatus): 当前任务状态。
        error_msg (str): 失败或中止原因；空字符串表示没有错误。
        attempted (int): 续传游标，已结算的条数（含失败与查重跳过）。
    """
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0


@dataclass(frozen=True)
class Task:
    """队列任务条目：由不可变任务定义与不可变运行状态组成。

    全字段只读，所有变更均通过构造新实例替换；跨线程传递时天然隔离，无需额外拷贝。
    """
    definition: TaskDefinition
    execution: TaskExecution

    # ── 任务定义的快捷读法 ───────────────────────────

    @property
    def task_id(self) -> str:
        return self.definition.task_id

    @property
    def target(self) -> VideoTarget:
        return self.definition.target

    @property
    def meta(self) -> TaskMeta:
        return self.definition.meta

    @property
    def danmakus(self) -> tuple[Danmaku, ...]:
        return self.definition.danmakus

    @property
    def config(self) -> TaskConfig:
        """发送节奏参数（冻结，直接给出即可）。"""
        return self.definition.config

    @property
    def total(self) -> int:
        return self.definition.total

    @property
    def display_string(self) -> str:
        return self.definition.display_string

    @property
    def is_config_complete(self) -> bool:
        """配置是否齐备可发：弹幕与视频目标都在。"""
        return self.definition.is_config_complete

    @property
    def missing_config_text(self) -> str:
        """缺失配置项的一句话说明；齐备时返回空字符串。"""
        return self.definition.missing_config_text

    # ── 运行时的快捷读法 ───────────────────────────

    @property
    def status(self) -> TaskStatus:
        return self.execution.status

    @property
    def error_msg(self) -> str:
        return self.execution.error_msg

    @property
    def attempted(self) -> int:
        return self.execution.attempted

    def to_draft(self) -> "TaskDraft":
        """拷贝为可变编辑沙盒（详情弹窗 / 构建弹窗用）"""
        definition = self.definition
        execution = self.execution
        return TaskDraft(
            target=replace(definition.target),
            meta=replace(definition.meta),
            danmakus=list(definition.danmakus),
            config=definition.config,
            task_id=definition.task_id,
            status=execution.status,
            error_msg=execution.error_msg,
            attempted=execution.attempted,
        )


@dataclass(kw_only=True)
class TaskDraft:
    """构造期 / 编辑沙盒 DTO。

    仅用于「组装 → 入队」与「详情弹窗编辑」。入队后由 QueueState 拆成
    TaskDefinition + TaskExecution，本对象不再代表队列中的真实任务。
    """
    target: VideoTarget = field(default_factory=VideoTarget)
    meta: TaskMeta = field(default_factory=TaskMeta)
    danmakus: list[Danmaku] = field(default_factory=list)
    config: TaskConfig
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0

    @property
    def total(self) -> int:
        return len(self.danmakus)

    @property
    def display_string(self) -> str:
        """日志显示：视频标题 → BVID → 未指定。"""
        return self.meta.video_title or self.target.bvid or "未指定视频目标"

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
        """打成不可变任务定义（target/meta 拷贝，config 本就冻结，弹幕收成 tuple）"""
        return TaskDefinition(
            task_id=self.task_id,
            target=replace(self.target),
            meta=replace(self.meta),
            danmakus=tuple(self.danmakus),
            config=self.config,
        )
