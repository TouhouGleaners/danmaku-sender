"""发送相关配置：单任务节奏、整队规则与运行模式。"""

from dataclasses import asdict

from pydantic import Field, model_validator

from danmaku_sender.types.models.common import SendMode
from danmaku_sender.types.models.queue import TaskConfig

from .base import AtomicModel


class SenderConfig(AtomicModel):
    """发送相关配置：一次队列运行共享。

    节奏与队列规则收拢在本类之下，调用方须经 ``SenderConfig.PacingConfig``
    / ``SenderConfig.QueueConfig`` 取类型，不得从别处单独引进来用。

    Attributes:
        mode (SendMode): 整轮运行做什么——仅发送，还是发送并监视。
        pacing (PacingConfig): 单个任务内的发送节奏。
        queue (QueueConfig): 整队的调度与查重规则。
    """

    class PacingConfig(AtomicModel):
        """单个任务内的发送节奏。

        入队时派生成 :class:`TaskConfig` 快照，此后不随设置变动。

        Attributes:
            min_delay (float): 相邻两条弹幕的最小间隔（秒）。
            max_delay (float): 相邻两条弹幕的最大间隔（秒）。
            burst_enabled (bool): 是否启用爆发模式。
            burst_size (int): 爆发模式每轮连续发送的条数。
            rest_min (float): 爆发模式每轮之间的最短休息（秒）。
            rest_max (float): 爆发模式每轮之间的最长休息（秒）。
        """

        min_delay: float = Field(default=9.5, ge=0.1)
        max_delay: float = Field(default=10.5, ge=0.1)

        burst_enabled: bool = True
        burst_size: int = Field(default=5, ge=2)
        rest_min: float = Field(default=30.0, ge=0.0)
        rest_max: float = Field(default=35.0, ge=0.0)

        @model_validator(mode='after')
        def check_logic(self) -> 'SenderConfig.PacingConfig':
            """业务规则校验：延迟与爆发休息的最小值不得大于最大值。"""
            if self.min_delay > self.max_delay:
                raise ValueError("最小延迟不能大于最大延迟")
            if self.burst_enabled and self.rest_min > self.rest_max:
                raise ValueError("爆发休息的最小值不能大于最大值")
            return self

        def to_task_config(self) -> TaskConfig:
            """派生工单参数快照（入队后不可变）。"""
            return TaskConfig(**self.model_dump())

        @classmethod
        def from_task_config(cls, cfg: TaskConfig) -> "SenderConfig.PacingConfig":
            """从工单参数还原为可编辑的配置（供表单编辑）。"""
            return cls.model_validate(asdict(cfg))

    class QueueConfig(AtomicModel):
        """整队的调度与查重规则。

        Attributes:
            allow_duplicates (bool): 允许重复发送；为 True 时发送前不比对账本。
            delay_between_tasks (float): 相邻两个任务之间的间隔（秒）。
        """

        allow_duplicates: bool = False
        delay_between_tasks: float = Field(default=30.0, ge=0.0)

    mode: SendMode = SendMode.SEND_AND_MONITOR
    pacing: PacingConfig = Field(default_factory=PacingConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
