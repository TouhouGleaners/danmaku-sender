"""支持字段变更事件订阅的 Pydantic 基类

配合 UIBinder 实现 Model → Widget 的反向同步。
"""

from typing import Any, Callable

from pydantic import BaseModel, PrivateAttr


class ObservableModel(BaseModel):
    """支持属性变更事件订阅的 Pydantic 基类

    使用方式：
        class MyConfig(ObservableModel):
            name: str = "default"

        config = MyConfig()
        config.subscribe("name", lambda v: print(f"changed: {v}"))
        config.name = "new"  # 触发回调
    """

    _observers: dict[str, list[Callable]] = PrivateAttr(default_factory=dict)

    def __setattr__(self, name: str, value: Any) -> None:
        old_value = getattr(self, name, None)
        super().__setattr__(name, value)

        # 仅在值实际变更且观察者已初始化时通知
        if old_value != value and hasattr(self, '_observers'):
            for cb in self._observers.get(name, []):
                cb(value)

    def subscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """订阅特定字段的变化"""
        if field_name not in self._observers:
            self._observers[field_name] = []
        self._observers[field_name].append(callback)

    def unsubscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """取消订阅"""
        if field_name in self._observers and callback in self._observers[field_name]:
            self._observers[field_name].remove(callback)
