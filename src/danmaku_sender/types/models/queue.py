import uuid
from dataclasses import dataclass, field
from enum import IntEnum

from .common import VideoTarget
from .danmaku import Danmaku

from danmaku_sender.config import SenderConfig


class TaskStatus(IntEnum):
    """队列任务状态"""
    PENDING = 0     # 等待中
    RUNNING = 1     # 执行中
    COMPLETED = 2   # 已完成
    FAILED = 3      # 失败
    SKIPPED = 4     # 已跳过


@dataclass
class QueueTask:
    """队列任务工单

    每个任务包含完整的发送上下文快照，添加到队列后不再依赖 VideoState。
    """
    target: VideoTarget
    danmakus: list[Danmaku]
    config_snapshot: SenderConfig
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    part_name: str = ""
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0
    total: int = field(init=False)

    def __post_init__(self):
        self.total = len(self.danmakus)
