import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event

from danmaku_sender.config import SendPolicy
from danmaku_sender.types.models.common import UnsentDanmakusRecord, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskConfig
from danmaku_sender.types.models.result import DanmakuSendResult

# 弹幕指纹：(内容, 进度, 模式, 字号, 颜色)
DanmakuFingerprint = tuple[str, int, int, int, int]


@dataclass
class SendJob:
    """单次发送所需的全部输入。

    Attributes:
        task_id (str): 归属任务。
        target (VideoTarget): 发送目标。
        danmakus (list[Danmaku]): 待发弹幕。
        config (TaskConfig): 本任务的发送节奏。
        policy (SendPolicy): 整队的发送策略。
        stop_event (Event): 中止信号。
        progress_callback (Callable[[int, int], None] | None): 进度回调，收已发数与总数。
        result_callback (Callable[[Danmaku, DanmakuSendResult], None] | None): 单条结果回调。
    """
    task_id: str
    target: VideoTarget
    danmakus: list[Danmaku]
    config: TaskConfig
    policy: SendPolicy
    stop_event: Event

    progress_callback: Callable[[int, int], None] | None = None
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
        auto_stop_reason (str): 触发自动停止的原因。
        fatal_error_occurred (bool): 是否因致命错误中止。
        fatal_error_msg (str): 中止原因。
        is_manually_stopped (bool): 是否被用户手动停止。
        unsent_records (list[UnsentDanmakusRecord]): 未发出的弹幕及原因。
        evidence_failures (list[tuple[Danmaku, str]]): 已发出但未入账的弹幕及原因。
        local_counter (dict[DanmakuFingerprint, int]): 各指纹在本次发送中出现的次数。
        db_count_cache (dict[DanmakuFingerprint, int]): 各指纹在账本中的记录次数。
    """
    total: int
    target: VideoTarget

    attempted_count: int = 0
    success_count: int = 0
    skipped_count: int = 0

    start_time: float = field(default_factory=time.time)
    auto_stop_reason: str = ""
    fatal_error_occurred: bool = False
    fatal_error_msg: str = ""
    is_manually_stopped: bool = False

    unsent_records: list[UnsentDanmakusRecord] = field(default_factory=list)
    evidence_failures: list[tuple[Danmaku, str]] = field(default_factory=list)

    local_counter: dict[DanmakuFingerprint, int] = field(default_factory=dict)
    db_count_cache: dict[DanmakuFingerprint, int] = field(default_factory=dict)

    @property
    def elapsed_minutes(self) -> float:
        """已运行的分钟数。

        Returns:
            float: 距 start_time 的分钟数。
        """
        return (time.time() - self.start_time) / 60

    def add_unsent(self, danmakus: Danmaku | list[Danmaku], reason: str) -> None:
        """记录未发出的弹幕及原因。

        Args:
            danmakus (Danmaku | list[Danmaku]): 单条或多条未发出的弹幕。
            reason (str): 未发出的原因。
        """
        if isinstance(danmakus, Danmaku):
            self.unsent_records.append({'dm': danmakus, 'reason': reason})
        else:
            for dm in danmakus:
                self.unsent_records.append({'dm': dm, 'reason': reason})
