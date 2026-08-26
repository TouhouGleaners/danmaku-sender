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
    xml_path: str = ""
    duration_ms: int = 0  # 视频时长（毫秒），用于弹幕时间越界校验
    status: TaskStatus = TaskStatus.PENDING
    error_msg: str = ""
    attempted: int = 0
    total: int = field(init=False)

    def __post_init__(self):
        self.total = len(self.danmakus)

    def validate(self) -> str | None:
        """验证任务数据合法性，返回错误信息，无错误返回 None"""
        if not self.target.bvid:
            return "缺少视频目标 (BVID)"
        if self.target.cid <= 0:
            return "未选择有效的分P"
        if not self.danmakus:
            return "未加载弹幕数据"
        return None

    def apply_edit(self, source: 'QueueTask'):
        """从编辑副本应用可修改的字段（保留 task_id, attempted 等运行时状态）"""
        self.target = source.target
        self.p_index = source.p_index
        self.p_title = source.p_title
        self.danmakus = source.danmakus
        self.total = source.total
        self.xml_path = source.xml_path
        self.duration_ms = source.duration_ms
        self.status = source.status
        self.config_snapshot = source.config_snapshot
