from typing import Callable

from pydantic import BaseModel, ConfigDict, Field


class MonitorConfig(BaseModel):
    """监视器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)

    # 字段变更通知
    _watchers: dict[str, list[Callable]] = {}

    def __setattr__(self, name: str, value) -> None:
        super().__setattr__(name, value)
        if name in type(self).model_fields:
            for cb in self._watchers.get(name, []):
                cb(value)

    def watch(self, field: str, callback: Callable) -> None:
        """注册字段变更回调"""
        self._watchers.setdefault(field, []).append(callback)

    def unwatch(self, field: str, callback: Callable) -> None:
        """注销字段变更回调"""
        try:
            self._watchers[field].remove(callback)
        except (KeyError, ValueError):
            pass

    refresh_interval: int = Field(default=60, ge=10)

    # 复用全局设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True

    stats_baseline: float = Field(default=0.0, exclude=True)
