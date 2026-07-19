from typing import Callable

from pydantic import BaseModel, ConfigDict, Field


class MonitorConfig(BaseModel):
    """监视器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)

    refresh_interval: int = Field(default=60, ge=10)

    # 复用全局设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True

    stats_baseline: float = Field(default=0.0, exclude=True)

    # 字段变更通知注册表
    # 当某个字段值变更时，__setattr__ 会遍历并调用该字段下的所有回调。
    # 由 UIBinder.bind() 自动注册，实现 model → widget 的反向同步。
    # 结构: { field_name: [callback(value), ...] }
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
