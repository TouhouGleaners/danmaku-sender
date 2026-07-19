"""支持字段变更事件订阅的 Pydantic 基类

配合 UIBinder 实现 Model → Widget 的反向同步。
"""

from typing import Any, Callable

from pydantic import BaseModel, PrivateAttr


class EventedModel(BaseModel):
    """
    支持属性变更事件监听的 Pydantic 基类。

    通过覆写 __setattr__ 拦截属性赋值，并在值发生改变时触发已注册的回调函数。
    完全兼容 Pydantic 的类型验证系统，且不影响 IDE 的静态类型推导。

    使用方式：
        class MyConfig(EventedModel):
            name: str = "default"

        config = MyConfig()
        config.subscribe("name", lambda v: print(f"changed: {v}"))
        config.name = "new"  # 触发回调
    """

    # 存储字段名到回调函数列表的映射。
    # 使用 PrivateAttr 确保该字典不参与 Pydantic 的 Schema 验证和 JSON 序列化。
    _callbacks: dict[str, list[Callable[[Any], None]]] = PrivateAttr(default_factory=dict)

    def __setattr__(self, name: str, value: Any) -> None:
        """覆写赋值拦截器。在 Pydantic 完成校验并成功赋值后，触发该属性下注册的所有回调。"""
        old_value = getattr(self, name, None)
        super().__setattr__(name, value)

        # 跳过私有属性，避免内部状态变更意外触发外部回调
        if old_value != value and not name.startswith('_') and hasattr(self, '_callbacks'):
            for callback in self._callbacks.get(name, []):
                callback(value)

    def subscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """订阅特定属性的变更事件"""
        if field_name not in self._callbacks:
            self._callbacks[field_name] = []
        self._callbacks[field_name].append(callback)

    def unsubscribe(self, field_name: str, callback: Callable[[Any], None]) -> None:
        """注销特定属性的订阅"""
        if field_name in self._callbacks and callback in self._callbacks[field_name]:
            self._callbacks[field_name].remove(callback)
            if not self._callbacks[field_name]:
                del self._callbacks[field_name]
