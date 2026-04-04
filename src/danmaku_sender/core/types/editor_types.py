import uuid
from enum import Enum, auto
from typing import Any, TypedDict
from dataclasses import dataclass, field

from ..entities.danmaku import Danmaku


class EditorField(Enum):
    """编辑器可改动的字段枚举"""
    MSG = "msg"
    COLOR = "color"
    FONT_SIZE = "fontsize"
    MODE = "mode"
    PROGRESS = "progress"
    IS_DELETED = "is_deleted"  # 逻辑删除标记

    def get_value(self, item: 'EditorItem') -> Any:
        """获取 Danmaku 实例中对应的属性值，集中管理映射关系"""
        if self == EditorField.IS_DELETED:
            return item.is_deleted
        return getattr(item.working, self.value)

    def set_value(self, item: 'EditorItem', val: Any) -> None:
        """设置 Danmaku 实例中对应的属性值"""
        if self == EditorField.IS_DELETED:
            item.is_deleted = val
        else:
            setattr(item.working, self.value, val)


@dataclass
class EditorItem:
    """
    弹幕节点容器

    内聚了单条弹幕在编辑周期内的所有状态
    """
    head: Danmaku                 # HEAD 快照：检出时的不可变状态
    working: Danmaku              # 工作区：当前正在编辑的状态
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    is_deleted: bool = False      # 逻辑删除标记
    error_msg: str = ""           # 校验错误信息
    head_had_error: bool = False  # 检出时是否携带有错误 (用于计算修复量)


@dataclass(frozen=True)
class AtomicChange:
    """原子变更记录：描述单条弹幕单次属性的变化"""
    item_id: str          # 暂存区索引
    field: EditorField    # 修改字段
    previous_value: Any   # 该变化发生前的原始值


class ViewItem(TypedDict):
    """传递给 UI 表格的视图数据字典"""
    id: str
    time_ms: int
    content: str
    error_msg: str
    is_valid: bool


class InsertPosition(Enum):
    """弹幕插入位置枚举"""
    ABOVE = auto()
    BELOW = auto()