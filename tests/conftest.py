"""共享测试夹具与辅助函数"""
import os

import pytest
from PySide6.QtWidgets import QApplication

from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.editor_types import EditorItem


@pytest.fixture(scope="session")
def qapp():
    """创建 QApplication。无头 CI 没有显示服务器，必须先切到 offscreen。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def make_danmaku(msg: str = "弹幕", progress: int = 1000, **kwargs) -> Danmaku:
    """快捷构造弹幕（非 fixture，直接 import 使用）"""
    return Danmaku(msg=msg, progress=progress, **kwargs)


def edit_working(item: EditorItem, **changes) -> EditorItem:
    """替换 EditorItem.working（Danmaku 不可变，测试里改字段用这个）"""
    item.working = item.working.replace(**changes)
    return item
