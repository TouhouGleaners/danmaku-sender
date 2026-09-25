"""实时修改表单的绑定器：控件变更立即写入模型。"""

import logging
import weakref
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, ClassVar, NamedTuple

from pydantic import BaseModel, ValidationError
from PySide6.QtWidgets import QWidget

from .base import _WidgetAdapter, clear_invalid, mark_invalid

logger = logging.getLogger(__name__)


class _LiveField(NamedTuple):
    """LiveFormBinder 的内部绑定元数据。

    **禁止**把写回闭包或 after_write 以强引用存进来：回调常捕获所在窗口（如 ``lambda: self.xxx``），
    而本注册表是类级弱引用表（永生根），一旦 value 强引用 key 就形成「注册表 → 回调 → 窗口 → 控件」的强引用链，
    条目永远无法回收。
    弱引用表一旦被 key 的强引用回环锁住，「key 死则条目亡」的约定就失效了。

    slot_ref 是写回闭包的**弱引用**，仅供重绑时定位并 disconnect 旧连接。
    弱引用不延长闭包寿命，不会重建上述强引用链。
    写回闭包本体由 Qt 信号连接持有（disconnect 或控件销毁后即可回收）。

    to_model / to_widget 是纯函数形式的类型转换，会被强引用保存；
    **同样不得捕获所在窗口**，否则重建上述强引用链。请用模块级函数（如
    ``parse_keywords``）而不是 ``lambda: self.xxx``。
    """

    model: BaseModel
    field_name: str
    to_widget: Callable[[Any], Any] | None
    to_model: Callable[[Any], Any] | None
    token: object
    realtime: bool
    slot_ref: weakref.ReferenceType[Callable[..., None]]


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
        model: BaseModel,
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
        # 用 model_fields 而非 hasattr：后者会放行方法名（如 "model_dump"），
        # 后续按字段落账时会把方法本身覆盖掉
        if field_name not in type(model).model_fields:
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

            # 同一模型下的控件一起试算、整表落账。
            # 单字段写会丢掉兄弟控件的待定输入：例如 min 先被拒、max 改对后，
            # min 的输入就找不回来了。互约束（min ≤ max）下单字段也判不了合法性。
            siblings = [(s, f) for s, f in list(cls._bindings.items()) if f.model is model]
            data = model.model_dump()
            for sibling, f in siblings:
                try:
                    raw_val = _WidgetAdapter.read(sibling)
                    data[f.field_name] = f.to_model(raw_val) if f.to_model is not None else raw_val
                except Exception as e:
                    logger.warning(f"控件值转换失败 [{f.field_name}]: {e}")
                    mark_invalid(sibling, str(e))
                    return

            new_val = data[field_name]
            try:
                fresh = type(model).model_validate(data)
            except ValidationError as e:
                error_msg = "\n".join(err.get("msg", "格式错误") for err in e.errors())
                logger.warning(f"表单整体校验失败 [{field_name}={new_val}]: {error_msg}")
                mark_invalid(w, error_msg)
                return

            # fresh 已整体合法，逐字段落账；走 object.__setattr__ 跳过
            # __setattr__ 的再校验（中间态会再次失败）。
            # 只落 data 里收集到的字段：exclude=True 等不参与 model_dump 的
            # 字段不在 data 中，不能让 fresh 的默认值把它们冲掉。
            for name in data:
                object.__setattr__(model, name, getattr(fresh, name))
            for sibling, _f in siblings:
                clear_invalid(sibling)
            if after_write is not None:
                after_write(field_name, new_val)

        # slot 只以弱引用进注册表，强引用由 Qt 信号连接持有
        cls._bindings[widget] = _LiveField(
            model, field_name, to_widget, to_model, token, realtime, weakref.ref(_write_back)
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
