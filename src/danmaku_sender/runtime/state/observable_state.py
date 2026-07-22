from contextlib import contextmanager
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, SignalInstance


class ObservableState(QObject):
    """
    属性赋值自动发射 changed(str) 信号的状态基类。

    就地修改容器不触发信号，需调用 notify() 或重新赋值。
    初始化时用 init_context() 抑制假信号。
    """
    changed = Signal(str)

    def __init__(self) -> None:
        self.__dict__["_initializing"] = False
        self.__dict__["_subscriptions"] = {}
        super().__init__()

    @contextmanager
    def init_context(self):
        """初始化上下文管理器，自动抑制信号。"""
        self._initializing = True
        try:
            yield
        finally:
            self._initializing = False

    def notify(self, field_name: str) -> None:
        """手动发射某字段的变更信号，用于就地修改容器后。"""
        self.changed.emit(field_name)

    def subscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """兼容 UIBinder 的 Subscribable 协议"""
        def _wrapper(changed_field: str) -> None:
            if changed_field == field_name:
                callback(getattr(self, field_name))
        self._subscriptions[(field_name, callback)] = _wrapper
        self.changed.connect(_wrapper)

    def unsubscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """兼容 UIBinder 的 Subscribable 协议"""
        key = (field_name, callback)
        if key in self._subscriptions:
            wrapper = self._subscriptions.pop(key)
            self.changed.disconnect(wrapper)

    def __setattr__(self, name: str, value: Any) -> None:
        if self._initializing:
            super().__setattr__(name, value)
            return

        if name.startswith("_") or isinstance(value, (Signal, SignalInstance)):
            super().__setattr__(name, value)
            return

        old = getattr(self, name, None)
        super().__setattr__(name, value)
        if old != value:
            self.changed.emit(name)
