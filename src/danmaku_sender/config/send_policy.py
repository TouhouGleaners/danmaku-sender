"""队列发送策略：一次队列运行共享，不随单个任务走。"""

from pydantic import Field

from danmaku_sender.types.models.common import SendMode

from .base import AtomicModel


class SendPolicy(AtomicModel):
    """队列发送策略。

    Attributes:
        allow_duplicates (bool): 允许重复发送；为 True 时发送前不比对账本。
        delay_between_tasks (float): 相邻两个任务之间的间隔（秒）。
        mode (SendMode): 仅发送，还是发送并监视。
    """

    allow_duplicates: bool = False
    delay_between_tasks: float = Field(default=30.0, ge=0.0)
    mode: SendMode = SendMode.SEND_AND_MONITOR
