from typing import Any, Callable

from PySide6.QtCore import QObject, Signal


class observed:
    """标记一个字段为可观察的。

    只有标记了 observed() 的字段赋值时会自动发射 changed 信号。
    普通属性不受影响。
    """
    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return obj.__dict__.get(self.name)

    def __set__(self, obj: Any, value: Any) -> None:
        old = obj.__dict__.get(self.name)
        obj.__dict__[self.name] = value
        if old != value:
            obj.changed.emit(self.name)


class ObservableState(QObject):
    """可观察的状态基类。

    字段用 observed() 声明，赋值时自动发射 changed(str) 信号。
    """
    changed = Signal(str)

    def notify(self, field_name: str) -> None:
        """手动发射某字段的变更信号，用于就地修改容器后。"""
        self.changed.emit(field_name)

    def subscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """兼容 UIBinder 的 Subscribable 协议。"""
        def _wrapper(changed_field: str) -> None:
            if changed_field == field_name:
                callback(getattr(self, field_name))
        self._subscriptions[(field_name, callback)] = _wrapper
        self.changed.connect(_wrapper)

    def unsubscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """兼容 UIBinder 的 Subscribable 协议。"""
        key = (field_name, callback)
        if key in self._subscriptions:
            wrapper = self._subscriptions.pop(key)
            self.changed.disconnect(wrapper)

    def __init__(self) -> None:
        self.__dict__["_subscriptions"] = {}
        super().__init__()
