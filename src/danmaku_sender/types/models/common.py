from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import TypedDict

from .danmaku import Danmaku


class RelativePosition(Enum):
    """相对参考项的位置：在参考项之上还是之下。

    Attributes:
        ABOVE (str): 参考项之上，列表更靠前、时间更早。
        BELOW (str): 参考项之下，列表更靠后、时间更晚。
    """
    ABOVE = "上方"
    BELOW = "下方"


class DanmakuStatus(IntEnum):
    PENDING = 0   # 待验证
    VERIFIED = 1  # 已存活
    LOST = 2      # 已丢失


class StartReadiness(Enum):
    """子系统能否启动；READY 表示可启动，其余成员是尚不满足的条件。

    Attributes:
        READY (str): 条件齐备，可启动。
        ALREADY_RUNNING (str): 已在运行，或上一个 Worker 尚在收尾。
        MISSING_CREDENTIALS (str): 身份凭据缺失。
        NO_RUNNABLE_TASKS (str): 队列中没有任务。
    """
    READY = "ready"
    ALREADY_RUNNING = "already_running"
    MISSING_CREDENTIALS = "missing_credentials"
    NO_RUNNABLE_TASKS = "no_runnable_tasks"


class SendMode(Enum):
    """发送工作流模式。

    Attributes:
        SEND_ONLY (str): 仅发送。
        SEND_AND_MONITOR (str): 发送并监视：发送期间一并核销已发出的弹幕。
    """
    SEND_ONLY = "send_only"
    SEND_AND_MONITOR = "send_and_monitor"


@dataclass(frozen=True, kw_only=True)
class VideoTarget:
    """发送/核销的目标：以 BVID+CID 定位的某个分P。未指定的项为 None。

    Attributes:
        bvid (str | None): 视频 BVID，未指定为 None。
        cid (int | None): 分P的 CID，未指定为 None。
    """
    bvid: str | None = None
    cid: int | None = None

    @property
    def is_assigned(self) -> bool:
        """是否已指定有效目标：BVID 与分P 都在才算。"""
        return self.bvid is not None and self.cid is not None


@dataclass(frozen=True)
class TaskMeta:
    """任务的描述性资料：展示、校验与溯源。

    Attributes:
        video_title (str): 视频标题。
        part_page (int | None): 第几 P（1-based），未指定为 None。
        part_title (str): 分P标题。
        part_duration_ms (int | None): 分P时长（毫秒），未知为 None。
        xml_path (Path | None): 弹幕文件来自哪。
    """
    video_title: str = ""
    part_page: int | None = None
    part_title: str = ""
    part_duration_ms: int | None = None
    xml_path: Path | None = None


class MonitorStats(TypedDict):
    """监控统计数据结构"""
    total: int
    verified: int
    pending: int
    lost: int


class VerifyResult(TypedDict):
    """弹幕验证结果"""
    verified: int
    lost: int
    total_checked: int


class AuthCookies(TypedDict):
    """身份凭证 Cookie 结构"""
    SESSDATA: str
    bili_jct: str


class UnsentDanmakusRecord(TypedDict):
    """未发送弹幕记录"""
    dm: Danmaku
    reason: str


class PendingCidRecord(TypedDict):
    """待验证 CID 记录"""
    bvid: str
    cid: int


class PendingDanmakuRecord(TypedDict):
    """待验证弹幕记录"""
    dmid: str
    msg: str
    progress: int
    ctime: float


class TaskRecordRow(TypedDict):
    """一条任务的持久记录行。

    Attributes:
        task_id (str): 任务标识。
        bvid (str): 目标视频 BV 号。
        cid (int): 目标分P标识。
        video_title (str | None): 视频标题。
        part_page (int | None): 第几 P（1-based），未指定为 None。
        part_title (str | None): 分P标题。
        xml_path (str | None): 弹幕文件来自哪。
        created_at (float): 任务开始执行的时刻（Unix 时间戳）。
        status (str): 任务状态，取 ``TaskStatus.name``。
    """
    task_id: str
    bvid: str
    cid: int
    video_title: str | None
    part_page: int | None
    part_title: str | None
    xml_path: str | None
    created_at: float
    status: str


class TaskSearchHit(TaskRecordRow):
    """搜索命中的一条任务记录。

    Attributes:
        title_hit (bool): 任务标题或 BV 号是否命中关键词。
        msg_hits (int): 任务弹幕中命中关键词的条数。
    """
    title_hit: bool
    msg_hits: int
