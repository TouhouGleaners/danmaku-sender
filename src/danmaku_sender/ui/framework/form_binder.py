"""表单绑定工具：将 PySide 控件与 Pydantic 模型字段关联。

按表单的提交方式选择绑定器：

- :class:`LiveFormBinder`（实时修改）：没有「保存」按钮，控件变更
  立即写入模型（如设置页）。页面 ``showEvent`` 时调用 ``fill()`` 刷新。
- :class:`DraftFormBinder`（草稿修改）：有「保存」按钮，控件即草稿，
  确认时才写入模型（如任务详情对话框）。打开时 ``fill()``，
  确认时 ``collect()``。

公共函数 :func:`mark_invalid` / :func:`clear_invalid` 提供统一的
控件无效态视觉反馈，两个绑定器内部也会调用。
"""

import logging
from collections.abc import Callable
from typing import Any, NamedTuple

from pydantic import BaseModel, ValidationError
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
    if widget.property("invalid") == is_invalid:
        if is_invalid:
            widget.setToolTip(f"⚠️ 输入无效:\n{error_msg}")
        return

    widget.setProperty("invalid", is_invalid)
    widget.style().unpolish(widget)
    widget.style().polish(widget)

    if is_invalid:
        widget.setToolTip(f"⚠️ 输入无效:\n{error_msg}")
    else:
        widget.setToolTip("")


def _set_widget_value(
    widget: QWidget,
    value: Any,
    to_widget: Callable[[Any], Any] | None = None,
) -> None:
    """将单个值写入控件。

    不屏蔽控件信号，用户连接的信号槽照常触发。若该控件已绑定写回，
    调用方需在写入前置位 LiveFormBinder._filling，避免写回模型。

    Args:
        widget: 目标控件。
        value: 写入的值；若提供 ``to_widget`` 则先做转换。
        to_widget: 模型字段值转控件值的可选转换函数。
    """
    if to_widget is not None:
        value = to_widget(value)
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
    else:
        logger.warning(f"form_binder 尚不支持处理类型为 {type(widget)} 的控件")


def _read_widget_value(widget: QWidget) -> Any:
    """读取控件当前值。

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


def _pick_signal(widget: QWidget, realtime: bool) -> SignalInstance | None:
    """按控件类型返回用于触发写回的信号。

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
    logger.warning(f"form_binder 尚不支持处理类型为 {type(widget)} 的控件")
    return None


class _LiveField(NamedTuple):
    """LiveFormBinder 的内部绑定记录。"""

    widget: QWidget
    model: Any
    field_name: str
    to_widget: Callable[[Any], Any] | None
    signal: SignalInstance
    slot: Callable[..., None]


class _DraftField(NamedTuple):
    """DraftFormBinder 的内部映射记录。"""

    widget: QWidget
    field_name: str
    to_widget: Callable[[Any], Any] | None
    to_model: Callable[[Any], Any] | None


class LiveFormBinder:
    """实时修改表单的绑定器：控件变更立即写入模型。

    每个实例对应一张表单面板，绑定记录保存在实例上，随表单对象
    一同销毁，调用方无需手动解绑。

    Typical usage example::

        form = LiveFormBinder()
        form.bind(self.min_delay_spin, config, "min_delay")

        def showEvent(self, event):
            super().showEvent(event)
            form.fill()
    """

    def __init__(self) -> None:
        self._fields: list[_LiveField] = []
        # 程序向控件写值期间为 True，写回回调直接返回。
        # 不屏蔽控件信号，以免打断用户连接的联动槽。
        self._filling: bool = False

    def bind(
        self,
        widget: QWidget,
        model: Any,
        field_name: str,
        *,
        realtime: bool = False,
        after_write: Callable[[str, Any], None] | None = None,
        to_model: Callable[[Any], Any] | None = None,
        to_widget: Callable[[Any], Any] | None = None,
    ) -> "LiveFormBinder":
        """绑定控件到模型字段，并注册控件变更时的自动写回。

        同一控件重复调用会替换原有绑定（一个控件只对应一个字段）。
        控件值与字段类型不一致时（如 ``list[str]`` 与文本框），
        通过 ``to_model`` / ``to_widget`` 转换。

        Args:
            widget: 目标控件。
            model: 数据模型实例。
            field_name: 模型上的字段名。
            realtime: 仅对 ``QLineEdit`` 有效。True 表示输入即写回，
                False 表示失焦或回车时写回。
            after_write: 写回成功后的回调 ``(field_name, new_value)``，
                用于需要立即生效的副作用（如应用主题）。
                仅在控件触发的写回时调用，程序直接修改模型不会触发。
            to_model: 控件值转模型字段值。抛出异常时控件会被标红。
            to_widget: 模型字段值转控件值。

        Returns:
            self，支持链式调用。
        """
        if not hasattr(model, field_name):
            logger.error(f"bind 失败: 模型 {type(model).__name__} 不存在字段 '{field_name}'")
            return self

        self._unbind_widget(widget)
        signal = _pick_signal(widget, realtime)
        if signal is None:
            return self

        def _write_back(*args: Any) -> None:
            # fill / 初始挂载触发的信号不写回，避免覆盖模型或误触发 after_write
            if self._filling:
                return

            raw_val = _read_widget_value(widget)
            try:
                new_val = to_model(raw_val) if to_model is not None else raw_val
            except Exception as e:
                logger.warning(f"控件值转换失败 [{field_name}]: {e}")
                mark_invalid(widget, str(e))
                return

            try:
                setattr(model, field_name, new_val)
                clear_invalid(widget)
                if after_write is not None:
                    after_write(field_name, new_val)
            except ValidationError as e:
                error_msg = "\n".join(err.get("msg", "格式错误") for err in e.errors())
                logger.warning(f"赋值触发模型校验失败 [{field_name}={new_val}]: {error_msg}")
                mark_invalid(widget, error_msg)

        _set_widget_value(widget, getattr(model, field_name), to_widget)
        signal.connect(_write_back)
        self._fields.append(_LiveField(widget, model, field_name, to_widget, signal, _write_back))
        return self

    def fill(self) -> None:
        """将模型当前值填充到所有已绑定控件。

        页面 ``showEvent`` 时调用，保证打开页面时控件显示最新值。
        填充期间抑制写回（置位 ``_filling``），但不影响用户连接的
        信号槽，因此控件间联动无需在填充后额外刷新。
        """
        self._filling = True
        try:
            for f in self._fields:
                try:
                    _set_widget_value(f.widget, getattr(f.model, f.field_name), f.to_widget)
                    clear_invalid(f.widget)
                except Exception as e:
                    logger.warning(f"fill 失败 [{f.field_name}]: {e}")
        finally:
            self._filling = False

    def _unbind_widget(self, widget: QWidget) -> None:
        """断开并移除指定控件的既有绑定。

        Args:
            widget: 需要解除绑定的控件。
        """
        for i in reversed(range(len(self._fields))):
            field = self._fields[i]
            if field.widget is widget:
                try:
                    field.signal.disconnect(field.slot)
                except (RuntimeError, TypeError):
                    pass
                del self._fields[i]


class DraftFormBinder[T: BaseModel]:
    """草稿修改表单的绑定器：确认保存时才将控件值写入模型。

    控件本身即草稿。打开时 :meth:`fill` 填充初始值，用户确认时
    :meth:`collect` 读取并校验。取消操作直接关闭窗口即可，
    模型自始至终不会被修改。

    Args:
        model_class: 确认保存时构造的 Pydantic 模型类。

    Typical usage example::

        form = DraftFormBinder(SenderConfig)
        form.map(self.min_delay_spin, "min_delay")
        form.fill(task.config)

        try:
            config = form.collect()
        except ValidationError as e:
            form.show_errors(e)
    """

    def __init__(self, model_class: type[T]) -> None:
        self._model_class: type[T] = model_class
        self._fields: list[_DraftField] = []
        self._base: T | None = None

    def map(
        self,
        widget: QWidget,
        field_name: str,
        *,
        to_model: Callable[[Any], Any] | None = None,
        to_widget: Callable[[Any], Any] | None = None,
    ) -> "DraftFormBinder[T]":
        """登记控件与模型字段的对应关系。

        不连接信号、不修改模型。该映射供 :meth:`fill`、:meth:`collect`
        和 :meth:`show_errors` 使用。

        Args:
            widget: 目标控件。
            field_name: 模型上的字段名。
            to_model: 控件值转模型字段值，供 :meth:`collect` 使用。
            to_widget: 模型字段值转控件值，供 :meth:`fill` 使用。

        Returns:
            self，支持链式调用。
        """
        if field_name not in self._model_class.model_fields:
            logger.error(
                f"map 失败: {self._model_class.__name__} 不存在字段 '{field_name}'"
            )
            return self

        self._unmap_widget(widget)
        self._fields.append(_DraftField(widget, field_name, to_widget, to_model))
        return self

    def fill(self, model: T) -> None:
        """将模型值填充到已登记的控件，并记录该模型作为 :meth:`collect` 的基准。

        基准的作用：对话框未展示的字段（如任务详情未提供的配置项）
        在 :meth:`collect` 时保持原值，不会被重置为默认值。

        Args:
            model: 提供初始值的模型实例。
        """
        self._base = model
        for f in self._fields:
            _set_widget_value(f.widget, getattr(model, f.field_name), f.to_widget)
            clear_invalid(f.widget)

    def collect(self) -> T:
        """读取控件值，覆盖到基准模型的字段上，构造并校验模型实例。

        Returns:
            校验通过的模型实例。

        Raises:
            ValidationError: 字段或模型校验失败。可传给 :meth:`show_errors`
                定位到具体控件。
            ValueError: ``to_model`` 转换失败。对应控件已被标红。
        """
        data: dict[str, Any] = {}
        if self._base is not None:
            data.update(self._base.model_dump())

        for f in self._fields:
            raw_val = _read_widget_value(f.widget)
            try:
                data[f.field_name] = f.to_model(raw_val) if f.to_model is not None else raw_val
            except Exception as e:
                logger.warning(f"控件值转换失败 [{f.field_name}]: {e}")
                mark_invalid(f.widget, str(e))
                raise ValueError(f"{f.field_name}: {e}") from e

        return self._model_class.model_validate(data)

    def show_errors(self, error: ValidationError) -> list[str]:
        """将校验错误标红到对应控件。

        能通过字段名定位的错误（``loc`` 含字段名）标红对应控件；
        无法定位的错误（如跨字段校验、模型级校验）不标红，
        通过返回值交由调用方决定如何提示。

        Args:
            error: :meth:`collect` 抛出的校验异常。

        Returns:
            无法定位到控件的错误消息列表，已去掉 pydantic 的
            ``"Value error, "`` 前缀。
        """
        rest: list[str] = []
        for err in error.errors():
            loc = err.get("loc") or ()
            name = str(loc[0]) if loc else ""
            msg = err.get("msg", "格式错误")
            widget = next((f.widget for f in self._fields if f.field_name == name), None)
            if widget is not None:
                mark_invalid(widget, msg)
            else:
                rest.append(msg.removeprefix("Value error, "))
        return rest

    def _unmap_widget(self, widget: QWidget) -> None:
        """移除指定控件的既有映射。

        Args:
            widget: 需要移除映射的控件。
        """
        self._fields = [f for f in self._fields if f.widget is not widget]
