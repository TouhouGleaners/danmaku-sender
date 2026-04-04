import time
from threading import Event
from typing import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from ...entities.danmaku import Danmaku
from ...types.result import DanmakuSendResult
from ...types.common import VideoTarget
from ...services.danmaku_exporter import UnsentDanmakusRecord
from ...state import SenderConfig


# 弹幕指纹类型别名：(内容, 进度, 模式, 字号, 颜色)
# 用于在断点续传时，精准判断两条弹幕是否在物理表现上完全一致
DanmakuFingerprint = tuple[str, int, int, int, int]


class SendFlowAction(Enum):
    """
    发送流程控制动作枚举
    指示调度器在收到一次发送结果后，下一步该作何反应
    """
    CONTINUE = auto()     # 结果正常，继续发送下一条
    STOP_FATAL = auto()   # 遇到严重权限/网络错误，立即停止


@dataclass
class SendJob:
    """
    发送任务工单 (Parameter Object)

    将单次流水线所需的 [目标]、[数据]、[配置]、[回调] 打包为单一实体传入。
    """
    target: VideoTarget
    danmakus: list[Danmaku]
    config: SenderConfig
    stop_event: Event

    # 事件回调挂载点
    progress_callback: Callable[[int, int], None] | None = None
    result_callback: Callable[[Danmaku, DanmakuSendResult], None] | None = None


@dataclass
class SendingContext:
    """
    发送上下文 (Context Container)

    设计意图：在整个流水线运行期间，携带和收集运行状态（成功数、失败原因、耗时等）。
    流水线结束后，将作为最终的统计报告返回给外层调用方。
    """
    total: int                  # 任务总数
    config: SenderConfig        # 运行配置快照
    target: VideoTarget         # 目标视频信息

    # 计数器
    attempted_count: int = 0    # 已尝试发包的数量
    success_count: int = 0      # 成功发送的数量
    skipped_count: int = 0      # 因断点续传跳过的数量

    # 生命周期与终止状态
    start_time: float = field(default_factory=time.time)
    auto_stop_reason: str = ""          # 如果触发了自动停止，记录具体原因
    fatal_error_occurred: bool = False  # 是否因致命错误而崩塌

    # 失败弹幕回收站，供后续导出 XML 使用
    unsent_records: list[UnsentDanmakusRecord] = field(default_factory=list)

    # 智能去重(断点续传)的内部缓存池，避免高频查库
    # Key: 指纹 -> Value: 出现次数
    local_counter: dict[DanmakuFingerprint, int] = field(default_factory=dict)
    # Key: 指纹 -> Value: 数据库中记录的次数
    db_count_cache: dict[DanmakuFingerprint, int] = field(default_factory=dict)

    @property
    def elapsed_minutes(self) -> float:
        """获取任务已运行的分钟数"""
        return (time.time() - self.start_time) / 60

    def add_unsent(self, danmakus: Danmaku | list[Danmaku], reason: str):
        """记录发送失败/被跳过的弹幕及原因，装入回收站"""
        if isinstance(danmakus, Danmaku):
            self.unsent_records.append({'dm': danmakus, 'reason': reason})
        else:
            for dm in danmakus:
                self.unsent_records.append({'dm': dm, 'reason': reason})