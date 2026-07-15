"""
发送引擎模块 (Sender Engine)

本模块遵循单一职责原则 (SRP) 和参数对象模式 (Parameter Object Pattern) 设计。
- SendPipeline: 发送管线编排器，封装完整生命周期（组装、执行、记录、摘要）。
- DanmakuScheduler: 负责控制流、限流、断点续传与中断响应。
- DanmakuExecutor: 负责纯粹的网络 I/O 与发包处理。
- SendJob & SendingContext: 负责携带与记录整个发送生命周期的数据状态。
"""

from .pipeline import SendPipeline
from .scheduler import DanmakuScheduler
from .executor import DanmakuExecutor
from .context import SendingContext, SendJob
from .delay_manager import DelayManager


__all__ = [
    "SendPipeline",
    "DanmakuScheduler",
    "DanmakuExecutor",
    "SendingContext",
    "SendJob",
    "DelayManager",
]
