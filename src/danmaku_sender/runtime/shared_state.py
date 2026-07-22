import logging
from PySide6.QtCore import QObject, Signal


class SharedState(QObject):
    """可观察的共享状态容器。

    属性赋值时自动发射 changed 信号，无需手动 emit。
    用于多个 UI 页面共享的运行时状态。

    用法:
        class VideoData(SharedState):
            bvid: str = ""
            selected_cid: int = 0

        video = VideoData()
        video.changed.connect(lambda field: print(f"{field} changed"))
        video.bvid = "BV123"  # 自动触发信号
    """
    changed = Signal(str)  # 变更的字段名

    def __init__(self):
        self._initializing = True
        super().__init__()
        self._initializing = False

    def subscribe(self, field_name: str, callback):
        """兼容 UIBinder 的 Subscribable 协议"""
        def _wrapper(changed_field):
            if changed_field == field_name:
                callback(getattr(self, field_name))
        # 保存引用以便 unsubscribe
        if not hasattr(self, "_subscriptions"):
            self._subscriptions = {}
        self._subscriptions[(field_name, id(callback))] = (callback, _wrapper)
        self.changed.connect(_wrapper)

    def unsubscribe(self, field_name: str, callback):
        """兼容 UIBinder 的 Subscribable 协议"""
        if hasattr(self, "_subscriptions"):
            key = (field_name, id(callback))
            if key in self._subscriptions:
                _, wrapper = self._subscriptions.pop(key)
                self.changed.disconnect(wrapper)

    def __setattr__(self, name, value):
        # 初始化阶段或私有/Qt 属性直接写入
        if getattr(self, "_initializing", True) or name.startswith("_") or name == "changed":
            super().__setattr__(name, value)
            return

        old = getattr(self, name, None)
        super().__setattr__(name, value)
        if old is not value:
            self.changed.emit(name)
