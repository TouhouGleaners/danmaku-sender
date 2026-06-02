"""共享测试夹具与辅助函数"""
from danmaku_sender.core.models.danmaku import Danmaku


def make_danmaku(msg: str = "弹幕", progress: int = 1000, **kwargs) -> Danmaku:
    """快捷构造弹幕（非 fixture，直接 import 使用）"""
    return Danmaku(msg=msg, progress=progress, **kwargs)
