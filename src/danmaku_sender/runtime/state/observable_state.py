from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, SignalInstance


class ObservableState(QObject):
    """可观察的状态容器。

    属性赋值时自动发射 changed 信号，无需手动 emit。
    用于多个 UI 页面共享的运行时状态。

    子类在 __init__ 中应设置 _initializing = True，
    完成所有赋值后再设为 False，以抑制初始化期间的假信号。

    用法:
        class VideoState(ObservableState):
            bvid: str = ""
            selected_cid: int = 0

            def __init__(self):
                self._initializing = True
                super().__init__()
                self.loaded_danmakus = []
                self._initializing = False

        video = VideoState()
        video.changed.connect(lambda field: print(f"{field} changed"))
        video.bvid = "BV123"  # 自动触发信号
    """
    changed = Signal(str)

    def __init__(self):
        # 不管理 _initializing，由子类控制
        super().__init__()

    def subscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """兼容 UIBinder 的 Subscribable 协议"""
        def _wrapper(changed_field: str) -> None:
            if changed_field == field_name:
                callback(getattr(self, field_name))
        if not hasattr(self, "_subscriptions"):
            self._subscriptions: dict[tuple[str, Callable], Callable] = {}
        self._subscriptions[(field_name, callback)] = _wrapper
        self.changed.connect(_wrapper)

    def unsubscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """兼容 UIBinder 的 Subscribable 协议"""
        if hasattr(self, "_subscriptions"):
            key = (field_name, callback)
            if key in self._subscriptions:
                wrapper = self._subscriptions.pop(key)
                self.changed.disconnect(wrapper)

    def __setattr__(self, name: str, value: Any) -> None:
        # 初始化阶段直接写入
        if getattr(self, "_initializing", False):
            super().__setattr__(name, value)
            return

        # 私有属性和 Signal 直接写入
        if name.startswith("_") or isinstance(value, (Signal, SignalInstance)):
            super().__setattr__(name, value)
            return

        old = getattr(self, name, None)
        super().__setattr__(name, value)
        if old != value:
            self.changed.emit(name)
