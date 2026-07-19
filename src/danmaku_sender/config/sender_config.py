from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SenderConfig(BaseModel):
    """发送器的配置数据"""
    model_config = ConfigDict(validate_assignment=True)

    # 延迟设置
    min_delay: float = Field(default=8.0, ge=0.1)
    max_delay: float = Field(default=8.5, ge=0.1)

    # 爆发模式
    burst_size: int = Field(default=3, ge=0)
    rest_min: float = Field(default=40.0, ge=0.0)
    rest_max: float = Field(default=45.0, ge=0.0)

    # 自动停止
    stop_after_count: int = Field(default=0, ge=0)
    stop_after_time: int = Field(default=0, ge=0)

    # 系统设置
    prevent_sleep: bool = True
    use_system_proxy: bool = True

    # 断点续传
    skip_sent: bool = True

    # 字段变更通知注册表
    # 当某个字段值变更时，__setattr__ 会遍历并调用该字段下的所有回调。
    # 由 UIBinder.bind() 自动注册，实现 model → widget 的反向同步。
    # 结构: { field_name: [callback(value), ...] }
    _watchers: dict[str, list[Callable]] = {}

    @model_validator(mode='after')
    def check_logic(self) -> 'SenderConfig':
        """业务逻辑级校验：最小不能大于最大"""
        if self.min_delay > self.max_delay:
            raise ValueError("最小延迟不能大于最大延迟")
        if self.burst_size > 1 and self.rest_min > self.rest_max:
            raise ValueError("爆发休息的最小值不能大于最大值")
        return self

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
