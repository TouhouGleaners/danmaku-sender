import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from threading import Event

from danmaku_sender.config import SenderConfig
from danmaku_sender.types.models.common import UnsentDanmakusRecord, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskConfig
from danmaku_sender.types.models.result import DanmakuSendResult


@dataclass
class SendJob:
    """单次发送所需的全部输入。

    Attributes:
        task_id (str): 归属任务。
        target (VideoTarget): 发送目标。
        danmakus (Sequence[Danmaku]): 待发弹幕。
        config (TaskConfig): 本任务的发送节奏。
        queue_config (SenderConfig.QueueConfig): 整队的调度规则。
        stop_event (Event): 中止信号。
        allow_duplicates (bool): 允许重复发送；为 True 时本任务不查重，清单照发。
        start_index (int): 断点续传的起点（弹幕下标，0 = 从头发）。
        progress_callback (Callable[[int, int, float], None] | None): 进度回调，收已发数、总数与剩余秒数。
        result_callback (Callable[[Danmaku, DanmakuSendResult], None] | None): 单条结果回调。
    """
    task_id: str
    target: VideoTarget
    danmakus: Sequence[Danmaku]
    config: TaskConfig
    queue_config: SenderConfig.QueueConfig
    stop_event: Event
    allow_duplicates: bool = False

    # 断点续传的起点（弹幕下标）。启动队列时按快照游标定好再传进来，流水线不回头读策略。
    start_index: int = 0

    progress_callback: Callable[[int, int, float], None] | None = None
    result_callback: Callable[[Danmaku, DanmakuSendResult], None] | None = None


@dataclass
class SendingContext:
    """一次发送的运行记录，结束后作为报告返回给调用方。

    Attributes:
        total (int): 弹幕总数。
        target (VideoTarget): 发送目标。
        attempted_count (int): 已尝试发包的数量。
        success_count (int): 已发出的数量。
        skipped_count (int): 查重跳过的数量。
        start_time (float): 开始时刻。
        fatal_error_occurred (bool): 是否因致命错误中止。
        fatal_error_msg (str): 中止原因。
        is_manually_stopped (bool): 是否被用户手动停止。
        unsent_records (list[UnsentDanmakusRecord]): 未发出的弹幕及原因。
        evidence_failures (list[tuple[Danmaku, str]]): 已发出但未入账的弹幕及原因。
    """
    total: int
    target: VideoTarget

    attempted_count: int = 0
    success_count: int = 0
    skipped_count: int = 0

    start_time: float = field(default_factory=time.time)
    fatal_error_occurred: bool = False
    fatal_error_msg: str = ""
    is_manually_stopped: bool = False

    unsent_records: list[UnsentDanmakusRecord] = field(default_factory=list)
    evidence_failures: list[tuple[Danmaku, str]] = field(default_factory=list)

    @property
    def elapsed_minutes(self) -> float:
        """已运行的分钟数。

        Returns:
            float: 距 start_time 的分钟数。
        """
        return (time.time() - self.start_time) / 60

    def add_unsent(self, danmakus: Danmaku | Sequence[Danmaku], reason: str) -> None:
        """记录未发出的弹幕及原因。

        Args:
            danmakus (Danmaku | Sequence[Danmaku]): 单条或多条未发出的弹幕。
            reason (str): 未发出的原因。
        """
        if isinstance(danmakus, Danmaku):
            self.unsent_records.append({'dm': danmakus, 'reason': reason})
        else:
            for dm in danmakus:
                self.unsent_records.append({'dm': dm, 'reason': reason})
