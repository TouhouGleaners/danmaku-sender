from pydantic import Field

from .base import AtomicModel


class MonitorConfig(AtomicModel):
    """监视器的配置数据"""

    refresh_interval: int = Field(default=60, ge=10)
