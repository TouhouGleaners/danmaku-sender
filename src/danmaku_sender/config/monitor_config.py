from pydantic import Field

from .base import AtomicModel


class MonitorConfig(AtomicModel):
    """监视器的配置数据。

    Attributes:
        refresh_interval (int): 核销轮询间隔（秒）。
        grace_seconds (int): 发送自然结束后的收尾宽限时长（秒）。
    """

    refresh_interval: int = Field(default=60, ge=10)
    grace_seconds: int = Field(default=300, ge=0)
