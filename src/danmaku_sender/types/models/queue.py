import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

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

    过渡期保留：Task 已换抽屉存储（见 :class:`Task`），本类经 ``Task.definition``
    垫片拼装返回，随拆桥一并退役。

    Attributes:
        task_id (str): 任务唯一标识。
        target (VideoTarget): 发送目标；未指定时为空壳。
        meta (TaskMeta): 任务描述性资料。
        danmakus (tuple[Danmaku, ...]): 弹幕清单。
        config (TaskConfig): 发送节奏。
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
        """缺失配置项的一句话说明；齐备时返回空字符串。"""
        parts: list[str] = []
        if self.total <= 0:
            parts.append("未导入弹幕")
        if not self.target.is_assigned:
            parts.append("未指定视频目标")
        return "，且".join(parts)


@dataclass(frozen=True)
class TaskExecution:
    """任务运行时。

    过渡期保留：Task 已换抽屉存储（见 :class:`Task`），本类经 ``Task.execution``
    垫片拼装返回，随拆桥一并退役。

    Attributes:
        status (TaskStatus): 当前任务状态。
        error_msg (str): 失败或中止原因；空字符串表示没有错误。
        attempted (int): 续传游标，已结算的条数（含失败与查重跳过）。
    """
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0


@dataclass(frozen=True, kw_only=True)
class TargetSlot:
    """选定的分P：寻址键与展示资料同生共死。

    换目标整槽换掉；任务未配置目标时整个抽屉为 None，不造空壳。

    Attributes:
        target (VideoTarget): 纯寻址键，只做寻址与相等比较。
        video_title (str): 视频标题。
        part_page (int | None): 第几 P（1-based），未指定为 None。
        part_title (str): 分P标题。
        duration_ms (int | None): 分P总时长（毫秒），未知为 None。
    """
    target: VideoTarget
    video_title: str = ""
    part_page: int | None = None
    part_title: str = ""
    duration_ms: int | None = None


@dataclass(frozen=True, kw_only=True)
class DanmakuPack:
    """发什么：弹幕清单及其来源。

    换清单 / 换文件只动这格。

    Attributes:
        items (tuple[Danmaku, ...]): 弹幕清单，按发送顺序。
        source_path (Path | None): 导入的弹幕文件路径；无文件来源时为 None。
    """
    items: tuple[Danmaku, ...] = ()
    source_path: Path | None = None

    @property
    def total(self) -> int:
        return len(self.items)


@dataclass(frozen=True, kw_only=True)
class SendOptions:
    """怎么发：节奏与查重开关，对应发送配置对话框的整页。

    Attributes:
        pacing (TaskConfig): 发送节奏。
        allow_duplicates (bool): 是否允许重复发送（为 True 时发送前不查重）。
    """
    pacing: TaskConfig
    allow_duplicates: bool = False


@dataclass(frozen=True, kw_only=True)
class TaskState:
    """发到哪了：一趟发送的运行状态，逐条结算换新。

    Attributes:
        status (TaskStatus): 当前任务状态。
        cursor (int): 续传游标，已结算的条数（含失败与查重跳过）。
        error_msg (str): 失败或中止原因；空字符串表示没有错误。
    """
    status: TaskStatus = TaskStatus.PENDING
    cursor: int = 0
    error_msg: str = ""


@dataclass(frozen=True, kw_only=True)
class Task:
    """队列任务条目：一张不可变的单，四个抽屉各管一摊。

    全字段只读，所有变更均通过构造新实例替换；跨线程传递时天然隔离，无需额外拷贝。

    Attributes:
        task_id (str): 任务标识。
        slot (TargetSlot | None): 选定的分P；未配置目标时为 None。
        pack (DanmakuPack): 弹幕包。
        options (SendOptions): 发送选项。
        state (TaskState): 运行状态。
    """
    task_id: str
    slot: TargetSlot | None
    pack: DanmakuPack
    options: SendOptions
    state: TaskState

    # ── 快捷读法 ──────────────────────────────────

    @property
    def target(self) -> VideoTarget:
        """目标寻址键；未配置目标时为空壳（拆桥时改空值语义）。"""
        return VideoTarget() if self.slot is None else self.slot.target

    @property
    def meta(self) -> TaskMeta:
        """展示与溯源资料的拼装视图（槽 + 弹幕包来源）。"""
        slot = self.slot
        return TaskMeta(
            video_title="" if slot is None else slot.video_title,
            part_page=None if slot is None else slot.part_page,
            part_title="" if slot is None else slot.part_title,
            part_duration_ms=None if slot is None else slot.duration_ms,
            xml_path=self.pack.source_path,
        )

    @property
    def danmakus(self) -> tuple[Danmaku, ...]:
        return self.pack.items

    @property
    def config(self) -> TaskConfig:
        """发送节奏参数（冻结，直接给出即可）。"""
        return self.options.pacing

    @property
    def total(self) -> int:
        return self.pack.total

    @property
    def status(self) -> TaskStatus:
        return self.state.status

    @property
    def error_msg(self) -> str:
        return self.state.error_msg

    @property
    def cursor(self) -> int:
        """续传游标，已结算的条数。"""
        return self.state.cursor

    @property
    def display_string(self) -> str:
        """日志显示：视频标题 → BVID → 未指定。"""
        if self.slot is None:
            return "未指定视频目标"
        return self.slot.video_title or self.slot.target.bvid or "未指定视频目标"

    @property
    def is_config_complete(self) -> bool:
        """配置是否齐备可发：弹幕与视频目标都在。"""
        return self.slot is not None and self.total > 0

    @property
    def missing_config_text(self) -> str:
        """缺失配置项的一句话说明；齐备时返回空字符串。

        表格提示、任务详情与 Worker 跳过原因共用这套文案，
        保证「缺什么」在各界面与日志里说法一致。
        """
        parts: list[str] = []
        if self.total <= 0:
            parts.append("未导入弹幕")
        if self.slot is None:
            parts.append("未指定视频目标")
        return "，且".join(parts)

    # ── 过渡垫片（拆桥时随 TaskDefinition / TaskExecution 一并退役） ──

    @property
    def definition(self) -> TaskDefinition:
        """过渡垫片：抽屉拼回旧的任务定义，供未迁调用点读取。"""
        slot = self.slot
        return TaskDefinition(
            task_id=self.task_id,
            target=VideoTarget() if slot is None else slot.target,
            meta=self.meta,
            danmakus=self.pack.items,
            config=self.options.pacing,
        )

    @property
    def execution(self) -> TaskExecution:
        """过渡垫片：抽屉拼回旧的运行状态，供未迁调用点读取。"""
        return TaskExecution(
            status=self.state.status,
            error_msg=self.state.error_msg,
            attempted=self.state.cursor,
        )

    @property
    def attempted(self) -> int:
        """过渡垫片：续传游标（旧名）。"""
        return self.state.cursor

    def to_draft(self) -> "TaskDraft":
        """拷贝为可变编辑沙盒（详情弹窗 / 构建弹窗用）"""
        slot = self.slot
        return TaskDraft(
            target=VideoTarget() if slot is None else replace(slot.target),
            meta=TaskMeta(
                video_title="" if slot is None else slot.video_title,
                part_page=None if slot is None else slot.part_page,
                part_title="" if slot is None else slot.part_title,
                part_duration_ms=None if slot is None else slot.duration_ms,
                xml_path=self.pack.source_path,
            ),
            danmakus=list(self.pack.items),
            config=self.options.pacing,
            task_id=self.task_id,
            status=self.state.status,
            error_msg=self.state.error_msg,
            attempted=self.state.cursor,
        )


@dataclass(kw_only=True)
class TaskDraft:
    """构造期 / 编辑沙盒 DTO。

    仅用于「组装 → 入队」与「详情弹窗编辑」。入队后由 QueueState 拆成
    四个抽屉（见 :class:`Task`），本对象不再代表队列中的真实任务。
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

    def to_task(self) -> Task:
        """打成不可变任务：目标资料进槽、来源进弹幕包、节奏与开关进选项。"""
        meta = self.meta
        return Task(
            task_id=self.task_id,
            slot=None if not self.target.is_assigned else TargetSlot(
                target=replace(self.target),
                video_title=meta.video_title,
                part_page=meta.part_page,
                part_title=meta.part_title,
                duration_ms=meta.part_duration_ms,
            ),
            pack=DanmakuPack(items=tuple(self.danmakus), source_path=meta.xml_path),
            options=SendOptions(pacing=self.config),
            state=TaskState(
                status=self.status,
                cursor=self.attempted,
                error_msg=self.error_msg,
            ),
        )
