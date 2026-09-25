"""草稿修改表单的绑定器：确认保存时才将控件值写入模型。"""

import logging
import weakref
from collections.abc import Callable
from typing import Any, ClassVar, NamedTuple

from pydantic import BaseModel, ValidationError
from PySide6.QtWidgets import QWidget

from danmaku_sender.config import AtomicModel

from .base import _WidgetAdapter, clear_invalid, mark_invalid

logger = logging.getLogger(__name__)


class _DraftField(NamedTuple):
    """DraftFormBinder 的内部映射记录。

    不持有 widget 的强引用（widget 是注册表的 key）。
    """

    field_name: str
    to_widget: Callable[[Any], Any] | None
    to_model: Callable[[Any], Any] | None


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
    _bases: ClassVar[weakref.WeakKeyDictionary[QWidget, AtomicModel]] = weakref.WeakKeyDictionary()

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
    def fill(cls, parent: QWidget, model: AtomicModel) -> None:
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
            # 取完整字段值：model_dump() 不含 exclude=True 的字段，
            # 那些字段会被当成默认值参与跨字段校验
            data.update(base.field_values())

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
