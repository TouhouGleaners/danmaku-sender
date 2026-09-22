from pydantic import ConfigDict, Field

from danmaku_sender.types.models.evented_model import EventedModel


class MonitorConfig(EventedModel):
    """监视器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)

    refresh_interval: int = Field(default=60, ge=10)

    stats_baseline: float = Field(default=0.0, exclude=True)
