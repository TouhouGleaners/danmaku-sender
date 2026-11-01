"""表格与树视图的列规格。

列规格由调用方以具名值给出，在装配处校验与模型角色的对应关系并转成 QML 列属性字典，配置错误在装配处抛出。
"""
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractItemModel


@dataclass(frozen=True)
class ColumnSpec:
    """视图列规格。

    Attributes:
        role (str): 行数据角色名。
        title (str): 表头文字；树视图的列不使用。
        width (int | None): 列宽；None 表示弹性列。
        align (str): 对齐方式，取值为 left / right。
        color_role (str | None): 文字色角色名（十六进制色）；None 表示用正文色。
    """

    role: str
    title: str = ""
    width: int | None = None
    align: str = "left"
    color_role: str | None = None

    @staticmethod
    def to_qml_columns(model: QAbstractItemModel, specs: Sequence["ColumnSpec"]) -> list[dict[str, Any]]:
        """校验列规格与模型角色的对应关系，并转成 QML 列属性字典。

        Args:
            model (QAbstractItemModel): 提供行数据的模型，须按角色出数。
            specs (Sequence[ColumnSpec]): 列规格序列；弹性列（width 为 None）须在首位。

        Returns:
            list[dict[str, Any]]: QML 列属性字典序列。

        Raises:
            ValueError: 引用了模型未公开的角色、弹性列不在首位或 align 取值非法。
        """
        names = set(model.roleNames().values())
        missing = sorted(
            {spec.role for spec in specs if spec.role.encode() not in names}
            | {
                spec.color_role
                for spec in specs
                if spec.color_role and spec.color_role.encode() not in names
            }
        )
        if missing:
            raise ValueError(f"列规格引用了模型未公开的角色: {missing}")

        fills = [index for index, spec in enumerate(specs) if spec.width is None]
        if fills and fills != [0]:
            raise ValueError("弹性列（width 为 None）须是第一列")

        bad_align = sorted({spec.align for spec in specs if spec.align not in ("left", "right")})
        if bad_align:
            raise ValueError(f"列规格的 align 取值非法: {bad_align}，仅支持 left / right")

        return [
            {
                "role": spec.role,
                "title": spec.title,
                "width": spec.width,
                "align": spec.align,
                "colorRole": spec.color_role,
            }
            for spec in specs
        ]
