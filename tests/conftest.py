"""共享测试夹具与辅助函数"""
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.editor_types import EditorItem


def make_danmaku(msg: str = "弹幕", progress: int = 1000, **kwargs) -> Danmaku:
    """快捷构造弹幕（非 fixture，直接 import 使用）"""
    return Danmaku(msg=msg, progress=progress, **kwargs)


def edit_working(item: EditorItem, **changes) -> EditorItem:
    """替换 EditorItem.working（Danmaku 不可变，测试里改字段用这个）"""
    item.working = item.working.replace(**changes)
    return item
