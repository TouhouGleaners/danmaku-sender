"""表单与模型绑定基础设施 (Form Binder)

将 PySide 控件与 Pydantic 模型字段安全连接。

按表单的提交方式选择绑定器：
  - LiveFormBinder:（实时修改）：没有「保存」按钮，控件变更立即写入模型（如设置页）。
    页面 ``showEvent`` 时调用 ``fill()`` 刷新。
  - DraftFormBinder:（草稿修改）：有「保存」按钮，控件即草稿，确认时才写入模型（如任务详情对话框）。
    打开时 ``fill()``，确认时 ``collect()``。
"""

import logging
import weakref
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, ClassVar, NamedTuple

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
    # 未设置过 invalid 时 property 返回 None；必须按 bool 比较，
    # 否则首次 clear_invalid 会误入下面的分支、抹掉控件的永久 tooltip
    if bool(widget.property("invalid")) == is_invalid:
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


class _LiveField(NamedTuple):
    """LiveFormBinder 的内部绑定元数据。

    **禁止**把写回闭包或 after_write 以强引用存进来：回调常捕获所在窗口（如 ``lambda: self.xxx``），
    而本注册表是类级弱引用表（永生根），一旦 value 强引用 key 就形成「注册表 → 回调 → 窗口 → 控件」的强引用链，
    条目永远无法回收。
    弱引用表一旦被 key 的强引用回环锁住，「key 死则条目亡」的约定就失效了。

    slot_ref 是写回闭包的**弱引用**，仅供重绑时定位并 disconnect 旧连接。
    弱引用不延长闭包寿命，不会重建上述强引用链。
    写回闭包本体由 Qt 信号连接持有（disconnect 或控件销毁后即可回收）。
    """

    model: Any
    field_name: str
    to_widget: Callable[[Any], Any] | None
    token: object
    realtime: bool
    slot_ref: weakref.ReferenceType[Callable[..., None]]


class _DraftField(NamedTuple):
    """DraftFormBinder 的内部映射记录。

    不持有 widget 的强引用（widget 是注册表的 key）。
    """

    field_name: str
    to_widget: Callable[[Any], Any] | None
    to_model: Callable[[Any], Any] | None


class LiveFormBinder:
    """实时修改表单的绑定器：控件变更立即写入模型。

    无需实例化，直接以类方法调用。
    绑定记录由内部弱引用表维护，控件销毁时条目自动移除。

    Typical usage example::

        LiveFormBinder.bind(self.min_delay_spin, config, "min_delay")
        LiveFormBinder.bind(self.max_delay_spin, config, "max_delay")

        def showEvent(self, event):
            super().showEvent(event)
            LiveFormBinder.fill(self)
    """

    # 控件 → 绑定元数据（fill 反读 + 重绑时定位旧 slot 断连）。
    # key 为弱引用；value 不得
    # 强引用 key 或能到达 key 的对象（回调、窗口等），否则条目无法回收。
    _bindings: ClassVar[weakref.WeakKeyDictionary[QWidget, _LiveField]] = weakref.WeakKeyDictionary()
    # 每个控件的填充深度（>0 时该控件的写回回调直接返回）。
    # 按控件计数而非全局标志：fill 表单 A 时联动槽可能改动表单 B 的控件，
    # B 的写回必须照常发生，不能被 A 的填充状态误伤。
    _fill_depth: ClassVar[weakref.WeakKeyDictionary[QWidget, int]] = weakref.WeakKeyDictionary()

    @classmethod
    @contextmanager
    def _filling(cls, widget: QWidget) -> Generator[None, None, None]:
        """在写入控件值期间抑制该控件的写回。

        深度可重入（fill 期间联动槽可能再次触发 fill），归零才放行写回。
        只抑制当前控件，不影响其他控件的写回。

        Args:
            widget: 正在灌值的控件。
        """
        cls._fill_depth[widget] = cls._fill_depth.get(widget, 0) + 1
        try:
            yield
        finally:
            depth = cls._fill_depth.get(widget, 0) - 1
            if depth > 0:
                cls._fill_depth[widget] = depth
            else:
                cls._fill_depth.pop(widget, None)

    @classmethod
    def bind(
        cls,
        widget: QWidget,
        model: Any,
        field_name: str,
        *,
        realtime: bool = False,
        after_write: Callable[[str, Any], None] | None = None,
        to_model: Callable[[Any], Any] | None = None,
        to_widget: Callable[[Any], Any] | None = None,
    ) -> None:
        """绑定控件到模型字段，并注册控件变更时的自动写回。

        同一控件重复调用会替换原有绑定（一个控件只对应一个字段）。
        控件值与字段类型不一致时（如 ``list[str]`` 与文本框），通过 ``to_model`` / ``to_widget`` 转换。

        Args:
            widget: 目标控件。
            model: 数据模型实例。
            field_name: 模型上的字段名。
            realtime: 仅对 ``QLineEdit`` 有效。True 表示输入即写回，False 表示失焦或回车时写回。
            after_write: 写回成功后的回调 ``(field_name, new_value)``，用于需要立即生效的副作用（如应用主题）。
                仅在控件触发的写回时调用，程序直接修改模型不会触发。
            to_model: 控件值转模型字段值。抛出异常时控件会被标红。
            to_widget: 模型字段值转控件值。
        """
        if not hasattr(model, field_name):
            logger.error(f"bind 失败: 模型 {type(model).__name__} 不存在字段 '{field_name}'")
            return

        cls._unbind_widget(widget)
        signal = _WidgetAdapter.pick_signal(widget, realtime)
        if signal is None:
            return

        token = object()
        # 只弱引用控件：写回闭包若强引用 widget，会与注册表 key 形成环，条目无法回收
        wref = weakref.ref(widget)

        def _write_back(*args: Any) -> None:
            w = wref()
            if w is None:
                return
            # 该控件正处于灌值期间则不写回，避免覆盖模型或误触发 after_write
            if cls._fill_depth.get(w, 0) > 0:
                return
            # 该控件已被重新 bind 到别的字段，或元数据已移除：本闭包作废
            meta = cls._bindings.get(w)
            if meta is None or meta.token is not token:
                return

            raw_val = _WidgetAdapter.read(w)
            try:
                new_val = to_model(raw_val) if to_model is not None else raw_val
            except Exception as e:
                logger.warning(f"控件值转换失败 [{field_name}]: {e}")
                mark_invalid(w, str(e))
                return

            try:
                setattr(model, field_name, new_val)
                clear_invalid(w)
                if after_write is not None:
                    after_write(field_name, new_val)
            except ValidationError as e:
                error_msg = "\n".join(err.get("msg", "格式错误") for err in e.errors())
                logger.warning(f"赋值触发模型校验失败 [{field_name}={new_val}]: {error_msg}")
                mark_invalid(w, error_msg)

        # slot 只以弱引用进注册表，强引用由 Qt 信号连接持有
        cls._bindings[widget] = _LiveField(
            model, field_name, to_widget, token, realtime, weakref.ref(_write_back)
        )
        try:
            # 先连接再灌值：灌值触发的联动里若重绑同一控件，_unbind_widget
            # 能找到并断开本闭包。反过来「先灌值后连接」会让旧闭包在重绑后
            # 又被 connect 回去，只能靠 token 变成死槽、逐渐累积。
            signal.connect(_write_back)
            # 初始灌值按 fill 的语义压入深度，避免触发任何绑定写回
            with cls._filling(widget):
                _WidgetAdapter.write(widget, getattr(model, field_name), to_widget)
        except Exception:
            # 初始化失败不得留下「有元数据、无连接」的伪绑定
            current = cls._bindings.get(widget)
            if current is not None and current.token is token:
                cls._unbind_widget(widget)
            raise

    @classmethod
    def fill(cls, parent: QWidget) -> None:
        """将 parent 子树内所有已绑定控件从模型重读一遍。

        页面 ``showEvent`` 时调用，保证打开页面时控件显示最新值。
        填充期间抑制写回，但不影响用户连接的信号槽，因此控件间联动无需在填充后额外刷新。

        Args:
            parent: 表单面板或页面；其自身与所有子孙控件中的绑定都会被刷新。
        """
        targets: list[QWidget] = [parent, *parent.findChildren(QWidget)]
        for w in targets:
            f = cls._bindings.get(w)
            if f is None:
                continue
            with cls._filling(w):
                try:
                    _WidgetAdapter.write(w, getattr(f.model, f.field_name), f.to_widget)
                    clear_invalid(w)
                except Exception as e:
                    logger.warning(f"fill 失败 [{f.field_name}]: {e}")

    @classmethod
    def _unbind_widget(cls, widget: QWidget) -> None:
        """断开并移除指定控件的既有绑定。

        必须 disconnect 旧写回闭包：仅靠 token 让旧槽「不误写」是不够的，
        旧连接仍会攥住旧闭包及其捕获的 model / after_write / 旧窗口，并在重复重绑时无限累积。

        Args:
            widget: 需要解除绑定的控件。
        """
        old = cls._bindings.pop(widget, None)
        if old is None:
            return
        slot = old.slot_ref()
        if slot is None:
            return
        signal = _WidgetAdapter.pick_signal(widget, old.realtime)
        if signal is not None:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass


class DraftFormBinder:
    """草稿修改表单的绑定器：确认保存时才将控件值写入模型。

    无需实例化，直接以类方法调用。
    控件本身即草稿：打开时 :meth:`fill` 填充初始值，用户确认时 :meth:`collect` 读取并校验。
    取消操作直接关闭窗口即可，模型自始至终不会被修改。

    一张表单面板对应一组绑定（按 parent 子树收集），同一面板不要混放两张草稿表单。

    Typical usage example::

        DraftFormBinder.map(self.min_delay_spin, "min_delay")
        DraftFormBinder.map(self.max_delay_spin, "max_delay")

        # 打开对话框时
        DraftFormBinder.fill(self, task.config)

        # 用户点击保存
        try:
            config = DraftFormBinder.collect(self, SenderConfig)
        except ValidationError as e:
            rest = DraftFormBinder.show_errors(self, e)
    """

    # 控件 → 字段映射。key 为弱引用，控件销毁后条目自动移除。
    _fields: ClassVar[weakref.WeakKeyDictionary[QWidget, _DraftField]] = weakref.WeakKeyDictionary()
    # 表单面板 → fill 时的基准模型。collect 时未展示字段按基准保留。
    _bases: ClassVar[weakref.WeakKeyDictionary[QWidget, BaseModel]] = weakref.WeakKeyDictionary()

    @classmethod
    def map(
        cls,
        widget: QWidget,
        field_name: str,
        *,
        to_model: Callable[[Any], Any] | None = None,
        to_widget: Callable[[Any], Any] | None = None,
    ) -> None:
        """登记控件与模型字段的对应关系。

        不连接信号、不修改模型。该映射供 :meth:`fill`、:meth:`collect` 和 :meth:`show_errors` 使用。同一控件重复调用会替换原有映射。

        Args:
            widget: 目标控件。
            field_name: 模型上的字段名。
            to_model: 控件值转模型字段值，供 :meth:`collect` 使用。
            to_widget: 模型字段值转控件值，供 :meth:`fill` 使用。
        """
        cls._fields[widget] = _DraftField(field_name, to_widget, to_model)

    @classmethod
    def fill(cls, parent: QWidget, model: BaseModel) -> None:
        """将模型值填充到 parent 子树内已登记的控件，并记录该模型为基准。

        基准的作用：对话框未展示的字段（如任务详情未提供的配置项）在 :meth:`collect` 时保持原值，不会被重置为默认值。

        Args:
            parent: 表单面板或对话框。
            model: 提供初始值的模型实例。
        """
        cls._bases[parent] = model
        for w in cls._iter_fields(parent):
            f = cls._fields[w]
            try:
                _WidgetAdapter.write(w, getattr(model, f.field_name), f.to_widget)
                clear_invalid(w)
            except Exception as e:
                logger.warning(f"fill 失败 [{f.field_name}]: {e}")

    @classmethod
    def collect[T: BaseModel](cls, parent: QWidget, model_class: type[T]) -> T:
        """读取控件值，覆盖到基准模型的字段上，构造并校验模型实例。

        Args:
            parent: 表单面板或对话框。
            model_class: 构造目标使用的 Pydantic 模型类。

        Returns:
            校验通过的模型实例。

        Raises:
            ValidationError: 字段或模型校验失败。可传给 :meth:`show_errors` 定位到具体控件。
            ValueError: ``to_model`` 转换失败。对应控件已被标红。
        """
        data: dict[str, Any] = {}
        base = cls._bases.get(parent)
        if base is not None:
            data.update(base.model_dump())

        for w in cls._iter_fields(parent):
            f = cls._fields[w]
            if f.field_name not in model_class.model_fields:
                logger.error(
                    f"collect 跳过: {model_class.__name__} 不存在字段 '{f.field_name}'"
                )
                continue
            raw_val = _WidgetAdapter.read(w)
            try:
                data[f.field_name] = f.to_model(raw_val) if f.to_model is not None else raw_val
            except Exception as e:
                logger.warning(f"控件值转换失败 [{f.field_name}]: {e}")
                mark_invalid(w, str(e))
                # 与字段校验错误统一为 ValidationError，调用方不必分叉捕获
                raise ValidationError.from_exception_data(
                    model_class.__name__,
                    [
                        {
                            "type": "value_error",
                            "loc": (f.field_name,),
                            "input": raw_val,
                            "ctx": {"error": e},
                        }
                    ],
                ) from e

        return model_class.model_validate(data)

    @classmethod
    def show_errors(cls, parent: QWidget, error: ValidationError) -> list[str]:
        """将校验错误标红到 parent 子树内的对应控件。

        能通过字段名定位的错误（``loc`` 含字段名）标红对应控件。
        无法定位的错误（如跨字段校验、模型级校验）不标红，通过返回值交由调用方决定如何提示。

        Args:
            parent: 表单面板或对话框。
            error: :meth:`collect` 抛出的校验异常。

        Returns:
            无法定位到控件的错误消息列表，已去掉 pydantic 的 ``"Value error, "`` 前缀。
        """
        rest: list[str] = []
        for err in error.errors():
            loc = err.get("loc") or ()
            name = str(loc[0]) if loc else ""
            msg = err.get("msg", "格式错误")
            widget = next(
                (w for w in cls._iter_fields(parent) if cls._fields[w].field_name == name),
                None,
            )
            if widget is not None:
                mark_invalid(widget, msg)
            else:
                rest.append(msg.removeprefix("Value error, "))
        return rest

    @classmethod
    def _iter_fields(cls, parent: QWidget) -> list[QWidget]:
        """返回 parent 子树内已登记映射的控件（含 parent 自身）。"""
        targets: list[QWidget] = [parent, *parent.findChildren(QWidget)]
        return [w for w in targets if w in cls._fields]
