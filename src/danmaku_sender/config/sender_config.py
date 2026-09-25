from dataclasses import asdict

from pydantic import Field, model_validator

from danmaku_sender.types.models.queue import TaskConfig

from .base import AtomicModel


class SenderConfig(AtomicModel):
    """发送节奏参数（全局设置，可变）。

    描述**单个任务**里弹幕怎么发（延迟、爆发、休息），入队时派生成
    :class:`TaskConfig` 快照。队列级策略（跳过已发送、任务间隔、
    自动终止）见 :class:`SendPolicy`。
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
        """业务逻辑级校验：最小不能大于最大"""
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
        """从工单参数还原为可编辑的配置（表单编辑用）。"""
        return cls.model_validate(asdict(cfg))
