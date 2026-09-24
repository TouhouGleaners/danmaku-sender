"""表单绑定的共享基层：控件读写适配与无效态反馈。

两个绑定器都依赖本模块；本模块不依赖绑定器。
"""

import logging
import weakref
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)

logger = logging.getLogger(__name__)

# 标红前保存的常驻 tooltip，清除无效态时还回去。
# 只存 str、不引用 key 本身，弱引用表条目随控件销毁自动移除。
_saved_tooltips: weakref.WeakKeyDictionary[QWidget, str] = weakref.WeakKeyDictionary()


def mark_invalid(widget: QWidget, error_msg: str) -> None:
    """将控件标记为无效状态（动态属性 + QSS 重绘 + tooltip）。

    Args:
        widget: 目标控件。
        error_msg: 提示给用户的错误说明，会显示在 tooltip 中。
    """
    _set_widget_invalid_state(widget, True, error_msg)


def clear_invalid(widget: QWidget) -> None:
    """清除控件的无效标记。

    Args:
        widget: 目标控件。
    """
    _set_widget_invalid_state(widget, False)


def _set_widget_invalid_state(widget: QWidget, is_invalid: bool, error_msg: str = "") -> None:
    """更新控件的无效视觉状态。

    Args:
        widget: 目标控件。
        is_invalid: 是否标记为无效。
        error_msg: 无效时显示的错误说明。
    """
    # 未设置过 invalid 时 property 返回 None；必须按 bool 比较，
    # 否则首次 clear_invalid 会误入下面的分支、抹掉控件的永久 tooltip
    if bool(widget.property("invalid")) == is_invalid:
        if is_invalid:
            widget.setToolTip(f"⚠️ 输入无效:\n{error_msg}")
        return

    # 先存常驻提示再改 invalid 属性：改完之后无法再判断「是否首次标红」
    if is_invalid and not bool(widget.property("invalid")):
        _saved_tooltips[widget] = widget.toolTip()

    widget.setProperty("invalid", is_invalid)
    widget.style().unpolish(widget)
    widget.style().polish(widget)

    if is_invalid:
        widget.setToolTip(f"⚠️ 输入无效:\n{error_msg}")
    else:
        widget.setToolTip(_saved_tooltips.pop(widget, ""))


class _WidgetAdapter:
    """内聚所有 Qt 控件读、写、发信号逻辑的纯静态适配器。"""

    @staticmethod
    def read(widget: QWidget) -> Any:
        """从控件安全读取当前值。

        Args:
            widget: 目标控件。

        Returns:
            控件当前值；控件类型不受支持时返回 ``None``。
        """
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        return None

    @staticmethod
    def write(
        widget: QWidget,
        value: Any,
        to_widget: Callable[[Any], Any] | None = None,
    ) -> None:
        """向控件灌入新值；若值未发生改变，主动补发 Qt 信号以保证联动槽执行。

        Args:
            widget: 目标控件。
            value: 写入的值；若提供 ``to_widget`` 则先做转换。
            to_widget: 模型字段值转控件值的可选转换函数。
        """
        if to_widget is not None:
            value = to_widget(value)

        def _apply_val[T](new: T, getter: Callable[[], T], setter: Callable[[T], None]) -> None:
            old = getter()
            setter(new)
            if old == new:
                _WidgetAdapter.emit_unchanged(widget, new)

        if isinstance(widget, QCheckBox):
            _apply_val(bool(value), widget.isChecked, widget.setChecked)
        elif isinstance(widget, QSpinBox):
            _apply_val(int(float(value)), widget.value, widget.setValue)
        elif isinstance(widget, QDoubleSpinBox):
            _apply_val(float(value), widget.value, widget.setValue)
        elif isinstance(widget, QLineEdit):
            _apply_val(str(value) if value is not None else "", widget.text, widget.setText)
        elif isinstance(widget, QComboBox):
            idx = widget.findData(value)
            if idx >= 0:
                _apply_val(idx, widget.currentIndex, widget.setCurrentIndex)
        else:
            logger.warning(f"form_binder 尚未适配控件类型: {type(widget)}")

    @staticmethod
    def emit_unchanged(widget: QWidget, value: Any) -> None:
        """值未变化时主动补发 Qt 原生值变化信号，驱动依赖本控件的外部 UI 联动。

        只补发「值变化」语义的信号，不伪造用户交互信号。
        QLineEdit 补 ``textChanged`` 而非 ``editingFinished``（后者表示用户结束编辑，程序灌值不应触发）。
        """
        if isinstance(widget, QCheckBox):
            widget.toggled.emit(widget.isChecked())
            # stateChanged 携带 Qt.CheckState（0/1/2），不是 bool
            widget.stateChanged.emit(widget.checkState().value)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.emit(widget.value())
        elif isinstance(widget, QLineEdit):
            widget.textChanged.emit(widget.text())
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.emit(widget.currentIndex())

    @staticmethod
    def pick_signal(widget: QWidget, realtime: bool) -> SignalInstance | None:
        """根据控件类型及响应模式选取写回监听信号。

        Args:
            widget: 目标控件。
            realtime: 仅对 ``QLineEdit`` 有效。True 使用 ``textChanged``
                （输入即触发），False 使用 ``editingFinished``（失焦/回车触发）。

        Returns:
            信号实例；控件类型不受支持时返回 ``None``。
        """
        if isinstance(widget, QCheckBox):
            return widget.stateChanged
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.valueChanged
        if isinstance(widget, QLineEdit):
            return widget.textChanged if realtime else widget.editingFinished
        if isinstance(widget, QComboBox):
            return widget.currentIndexChanged
        logger.warning(f"form_binder 无法识别信号的控件: {type(widget)}")
        return None
