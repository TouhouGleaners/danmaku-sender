import logging
import weakref
from typing import Any, Callable

from pydantic import ValidationError

from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import (
    QWidget, QCheckBox, QSpinBox, QDoubleSpinBox, 
    QLineEdit, QComboBox
)

logger = logging.getLogger("UIBinder")


class UIBinder:
    """
    轻量级 MVVM 双向绑定引擎
    
    职责:
    1. 状态同步: 自动实现 Model (Pydantic/Object) 与 View (PySide6 Widget) 的数据双向同步。
    2. 生命周期管理: 内部维护绑定注册表 (_active_bindings)，每次重绑时自动解除历史信号，防止内存泄漏与重复触发。
    3. 异常反馈: 拦截 Pydantic 的 ValidationError，并通过动态属性 (invalid) 与 QSS 联动实现非侵入式的 UI 异常反馈。
    """

    # 静态绑定注册表
    # 使用弱引用字典，防止 Binder 持有 Widget 引用导致窗口无法关闭。
    # 当 Widget 被销毁时，对应的连接记录会自动从字典中移除（GC 自动清理）。
    # 结构: { Widget_Ref: [(Signal_Instance, Slot_Callable)] }
    _active_bindings: weakref.WeakKeyDictionary[QWidget, list[tuple[SignalInstance, Callable[..., None]]]] = weakref.WeakKeyDictionary()

    @staticmethod
    def _set_widget_invalid_state(widget: QWidget, is_invalid: bool, error_msg: str = "") -> None:
        """
        更新控件的异常视觉状态

        修改 Qt 动态属性并触发 QSS 样式重绘。
        """
        if widget.property("invalid") == is_invalid:
            if is_invalid:
                widget.setToolTip(f"⚠️ 输入无效:\n{error_msg}")
            return

        widget.setProperty("invalid", is_invalid)

        # 强制触发 QSS 重绘
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        
        if is_invalid:
            widget.setToolTip(f"⚠️ 输入无效:\n{error_msg}")
        else:
            widget.setToolTip("")

    @staticmethod
    def _set_widget_value(widget: QWidget, value: Any) -> None:
        """
        安全赋值

        在将 Model 数据推送到 UI 时，屏蔽控件的信号发送，防止触发反向更新导致的无限循环。
        """
        widget.blockSignals(True)
        try:
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(float(value)))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value) if value is not None else "")
            elif isinstance(widget, QComboBox):
                idx = widget.findData(value)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
        finally:
            widget.blockSignals(False)

    @staticmethod
    def bind(widget: QWidget, model: Any, field_name: str, clear_old: bool = True, realtime: bool = False) -> None:
        """
        执行双向绑定注册

        Args:
            widget: 目标 Qt 控件
            model: 绑定的数据模型
            field_name: 模型上的属性名称
            clear_old: 如果为 True，则清空该控件之前绑定的所有逻辑（默认行为）。设为 False 支持 1对N 绑定。
            realtime: 仅针对 QLineEdit，True 为按键实时更新，False 为失焦/回车更新。
        """
        if not hasattr(model, field_name):
            logger.error(f"绑定失败: 模型 {type(model).__name__} 不存在字段 '{field_name}'")
            return

        # 生命周期清理
        # 确保同一控件仅存在唯一的绑定槽函数，防止幽灵触发
        if clear_old:
            if widget in UIBinder._active_bindings:
                for old_signal, old_slot in UIBinder._active_bindings[widget]:
                    try:
                        old_signal.disconnect(old_slot)
                    except (RuntimeError, TypeError):
                        pass
                del UIBinder._active_bindings[widget]

        # 初始化控件的绑定列表
        if widget not in UIBinder._active_bindings:
            UIBinder._active_bindings[widget] = []

        # 初始数据挂载 (Model -> UI)
        current_value = getattr(model, field_name)
        UIBinder._set_widget_value(widget, current_value)

        # 构建回写代理 (UI -> Model Proxy)
        def _update_model_proxy(*args) -> None:
            new_val: Any = None
            if isinstance(widget, QCheckBox):
                new_val = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                new_val = widget.value()
            elif isinstance(widget, QLineEdit):
                new_val = widget.text().strip()
            elif isinstance(widget, QComboBox):
                new_val = widget.currentData()

            try:
                setattr(model, field_name, new_val)
                UIBinder._set_widget_invalid_state(widget, False)
            except ValidationError as e:
                error_msg = "\n".join([err.get('msg', '格式错误') for err in e.errors()])
                logger.warning(f"UI 赋值触发模型边界保护 [{field_name}={new_val}]: {error_msg}")
                UIBinder._set_widget_invalid_state(widget, True, error_msg)

        # 信号连接与注册
        signal_instance = None
        if isinstance(widget, QCheckBox):
            signal_instance = widget.stateChanged
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            signal_instance = widget.valueChanged
        elif isinstance(widget, QLineEdit):
           signal_instance = widget.textChanged if realtime else widget.editingFinished
        elif isinstance(widget, QComboBox):
            signal_instance = widget.currentIndexChanged
        else:
            logger.warning(f"UIBinder 尚不支持处理类型为 {type(widget)} 的控件")
            return

        if signal_instance is not None:
            signal_instance.connect(_update_model_proxy)
            # 存入弱引用注册表，确保安全回收
            UIBinder._active_bindings[widget].append((signal_instance, _update_model_proxy))