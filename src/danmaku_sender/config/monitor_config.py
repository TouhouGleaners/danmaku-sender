from pydantic import BaseModel, ConfigDict, Field

from .field_watcher import FieldWatcherMixin


class MonitorConfig(FieldWatcherMixin, BaseModel):
    """监视器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)

    refresh_interval: int = Field(default=60, ge=10)

    # 复用全局设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True

    stats_baseline: float = Field(default=0.0, exclude=True)
