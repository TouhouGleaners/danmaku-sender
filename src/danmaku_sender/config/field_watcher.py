"""Pydantic model 字段变更通知 mixin"""

from typing import Callable


_WATCHERS_KEY = '_fw_watchers'


class FieldWatcherMixin:
    """为 Pydantic model 添加字段变更通知能力。

    使用方式：
        class MyConfig(FieldWatcherMixin, BaseModel):
            ...

        config = MyConfig()
        config.watch("field_name", lambda v: print(f"changed: {v}"))
        config.field_name = 42  # 触发回调
    """

    def __setattr__(self, name: str, value) -> None:
        super().__setattr__(name, value)
        if name in self.model_fields:
            watchers = self.__dict__.get(_WATCHERS_KEY, {}).get(name, [])
            for cb in watchers:
                cb(value)

    def watch(self, field: str, callback: Callable) -> None:
        """注册字段变更回调"""
        if _WATCHERS_KEY not in self.__dict__:
            self.__dict__[_WATCHERS_KEY] = {}
        self.__dict__[_WATCHERS_KEY].setdefault(field, []).append(callback)

    def unwatch(self, field: str, callback: Callable) -> None:
        """注销字段变更回调"""
        try:
            self.__dict__[_WATCHERS_KEY][field].remove(callback)
        except (KeyError, ValueError):
            pass
