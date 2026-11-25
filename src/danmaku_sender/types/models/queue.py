from dataclasses import dataclass
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
class TaskInfo:
    """那个分P的资料快照（查回）：随地址同生共死。

    换地址时整份换掉（语义由 apply_edit 等换目标处捆绑）。

    Attributes:
        video_title (str): 视频标题。
        part_page (int | None): 第几 P（1-based），未指定为 None。
        part_title (str): 分P标题。
        duration_ms (int | None): 分P总时长（毫秒），未知为 None。
    """
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
            发送链路尚未接此开关，仍走整队规则；接线归「允许重复发送按任务」切片。
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
    """队列任务条目：一张不可变的单，各字段各管一摊。

    全字段只读，所有变更均通过构造新实例替换；跨线程传递时天然隔离，无需额外拷贝。

    Attributes:
        task_id (str): 任务标识。
        target (VideoTarget | None): 发往哪的地址（填入）；未配置目标时为 None。
        info (TaskInfo): 那个分P的资料快照（查回）。
        pack (DanmakuPack): 弹幕包。
        options (SendOptions): 发送选项。
        state (TaskState): 运行状态。
    """
    task_id: str
    target: VideoTarget | None
    info: TaskInfo
    pack: DanmakuPack
    options: SendOptions
    state: TaskState

    # ── 常用读法 ───────────────────────────────

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
        if self.target is None:
            return "未指定视频目标"
        return self.info.video_title or self.target.bvid

    @property
    def is_config_complete(self) -> bool:
        """配置是否齐备可发：弹幕与视频目标都在。"""
        return self.target is not None and self.total > 0

    @property
    def missing_config_text(self) -> str:
        """缺失配置项的一句话说明；齐备时返回空字符串。

        表格提示、任务详情与 Worker 跳过原因共用这套文案，
        保证「缺什么」在各界面与日志里说法一致。
        """
        parts: list[str] = []
        if self.total <= 0:
            parts.append("未导入弹幕")
        if self.target is None:
            parts.append("未指定视频目标")
        return "，且".join(parts)
