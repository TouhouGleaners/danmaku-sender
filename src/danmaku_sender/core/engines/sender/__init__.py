"""
发送引擎模块 (Sender Engine)

本模块遵循单一职责原则 (SRP) 和参数对象模式 (Parameter Object Pattern) 设计。
- DanmakuScheduler: 负责控制流、限流、断点续传与中断响应。
- DanmakuExecutor: 负责纯粹的网络 I/O 与发包处理。
- SendJob & SendingContext: 负责携带与记录整个发送生命周期的数据状态。
"""

from .scheduler import DanmakuScheduler
from .executor import DanmakuExecutor
from .context import SendingContext, SendJob


__all__ = ["DanmakuScheduler", "DanmakuExecutor", "SendingContext", "SendJob"]