from dataclasses import asdict

from pydantic import Field, model_validator

from danmaku_sender.types.models.queue import TaskConfig

from .base import AtomicModel


class SenderConfig(AtomicModel):
    """发送节奏参数（全局设置，可变）。

    描述**单个任务**内弹幕的发送方式（延迟、爆发、休息），入队时派生成
    :class:`TaskConfig` 快照。队列级策略（跳过已发送、任务间隔）
    见 :class:`SendPolicy`。

    Attributes:
        min_delay (float): 相邻两条弹幕的最小间隔（秒）。
        max_delay (float): 相邻两条弹幕的最大间隔（秒）。
        burst_enabled (bool): 是否启用爆发模式。
        burst_size (int): 爆发模式每轮连续发送的条数。
        rest_min (float): 爆发模式每轮之间的最短休息（秒）。
        rest_max (float): 爆发模式每轮之间的最长休息（秒）。
    """

    # 延迟设置
    min_delay: float = Field(default=8.0, ge=0.1)
    max_delay: float = Field(default=8.5, ge=0.1)

    # 爆发模式
    burst_enabled: bool = False
    burst_size: int = Field(default=3, ge=2)
    rest_min: float = Field(default=40.0, ge=0.0)
    rest_max: float = Field(default=45.0, ge=0.0)

    @model_validator(mode='after')
    def check_logic(self) -> 'SenderConfig':
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
    def from_task_config(cls, cfg: TaskConfig) -> "SenderConfig":
        """从工单参数还原为可编辑的配置（供表单编辑）。"""
        return cls.model_validate(asdict(cfg))
