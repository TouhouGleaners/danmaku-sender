"""
发送引擎模块 (Sender Engine)

本模块遵循单一职责原则 (SRP) 和参数对象模式 (Parameter Object Pattern) 设计。
- SendPlan: 发送计划，静态编排查重判定、爆发休息与等待时长。
- SendPipeline: 发送管线编排器，封装完整生命周期（组装、执行、记录、摘要）。
- DanmakuScheduler: 照发送计划推进控制流、等待与中断响应。
- DanmakuExecutor: 负责纯粹的网络 I/O 与发包处理。
- SendJob & SendingContext: 负责携带与记录整个发送生命周期的数据状态。
"""

from .context import SendingContext, SendJob
from .executor import DanmakuExecutor
from .pipeline import SendPipeline
from .planner import SendPlan
from .scheduler import DanmakuScheduler

__all__ = [
    "DanmakuExecutor",
    "DanmakuScheduler",
    "SendJob",
    "SendPipeline",
    "SendPlan",
    "SendingContext",
]
