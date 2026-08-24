import uuid
from dataclasses import dataclass, field
from enum import Enum

from .common import VideoTarget
from .danmaku import Danmaku

from danmaku_sender.config import SenderConfig


class TaskStatus(Enum):
    """队列任务状态"""
    UNCONFIGURED = "未配置"
    PENDING = "等待中"
    RUNNING = "发送中"
    PAUSED = "已暂停"
    COMPLETED = "已完成"
    FAILED = "失败"
    SKIPPED = "已跳过"


@dataclass
class QueueTask:
    """队列任务工单

    每个任务包含完整的发送上下文快照，添加到队列后不再依赖 VideoState。
    """
    target: VideoTarget
    danmakus: list[Danmaku]
    config_snapshot: SenderConfig
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    p_index: int = 0
    p_title: str = ""
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0
    total: int = field(init=False)

    def __post_init__(self):
        self.total = len(self.danmakus)
