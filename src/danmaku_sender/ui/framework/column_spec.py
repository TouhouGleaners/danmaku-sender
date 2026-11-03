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
        sub_role (str | None): 次行角色名（树视图标签列的第二行文字）；仅第一列可用，取值为空的行按单行显示。
        title (str): 表头文字；树视图的列不使用。
        width (int | None): 列宽；None 表示弹性列。标签列不按列宽排布：树自适应内容聚拢行右缘，表格以列宽为槽宽（None 随内容）。
        align (str): 对齐方式，取值为 left / right。
        tone_role (str | None): 小标签健康档角色名（good / warn / bad）；须与 tag 同用。
        tag (bool): 是否渲染为小标签。
    """

    role: str
    sub_role: str | None = None
    title: str = ""
    width: int | None = None
    align: str = "left"
    tone_role: str | None = None
    tag: bool = False

    # QML 行委托的保留属性名，同名角色会被委托属性遮蔽
    RESERVED_ROLE_NAMES = frozenset({"index", "model"})

    @staticmethod
    def to_qml_columns(
        model: QAbstractItemModel,
        specs: Sequence["ColumnSpec"],
        require_fill_first: bool = False,
        require_trailing_tags: bool = False,
    ) -> list[dict[str, Any]]:
        """校验列规格与模型角色的对应关系，并转成 QML 列属性字典。

        Args:
            model (QAbstractItemModel): 提供行数据的模型，须按角色出数。
            specs (Sequence[ColumnSpec]): 列规格序列。
            require_fill_first (bool): 要求弹性列（width 为 None）在首位；TreeView 的列几何只支持首位弹性列。标签列不计弹性列。
            require_trailing_tags (bool): 要求标签列在末尾连续；TreeView 把标签列聚拢行右缘，与定宽列混排会重叠。

        Returns:
            list[dict[str, Any]]: QML 列属性字典序列。

        Raises:
            ValueError: 引用了委托保留名或模型未公开的角色、width 为负、弹性列不在首位、标签列不在末尾连续、tone_role 未与 tag 同用、sub_role 不在第一列或 align 取值非法。
        """
        names = set(model.roleNames().values())
        role_refs = {spec.role for spec in specs} | {
            attr
            for spec in specs
            for attr in (spec.tone_role, spec.sub_role)
            if attr
        }
        clash = sorted(role_refs & ColumnSpec.RESERVED_ROLE_NAMES)
        if clash:
            raise ValueError(f"列规格引用了委托保留名: {clash}")
        missing = sorted({ref for ref in role_refs if ref.encode() not in names})
        if missing:
            raise ValueError(f"列规格引用了模型未公开的角色: {missing}")

        negative = sorted({spec.role for spec in specs if spec.width is not None and spec.width < 0})
        if negative:
            raise ValueError(f"列规格的 width 为负: {negative}")

        fills = [index for index, spec in enumerate(specs) if spec.width is None and not spec.tag]
        if require_fill_first and fills and fills != [0]:
            raise ValueError("弹性列（width 为 None）须是第一列")

        if require_trailing_tags:
            first_tag = next((index for index, spec in enumerate(specs) if spec.tag), None)
            if first_tag is not None and any(not spec.tag for spec in specs[first_tag:]):
                raise ValueError("标签列须在末尾连续")

        stray_tone = sorted({spec.role for spec in specs if spec.tone_role and not spec.tag})
        if stray_tone:
            raise ValueError(f"tone_role 须与 tag 同用: {stray_tone}")

        stray_sub = sorted({spec.role for spec in specs[1:] if spec.sub_role})
        if stray_sub:
            raise ValueError(f"sub_role 仅限第一列: {stray_sub}")

        bad_align = sorted({spec.align for spec in specs if spec.align not in ("left", "right")})
        if bad_align:
            raise ValueError(f"列规格的 align 取值非法: {bad_align}，仅支持 left / right")

        return [
            {
                "role": spec.role,
                "subRole": spec.sub_role,
                "title": spec.title,
                "width": spec.width,
                "align": spec.align,
                "toneRole": spec.tone_role,
                "tag": spec.tag,
            }
            for spec in specs
        ]
