"""共享测试夹具与辅助函数"""
import os

import pytest
from PySide6.QtWidgets import QApplication

from danmaku_sender.infra.persistence.queue_store import (
    _QueueFailure,
    _QueueItem,
    _QueueTask,
)
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.editor_types import EditorItem


@pytest.fixture(scope="session")
def qapp():
    """创建 QApplication。无头 CI 没有显示服务器，必须先切到 offscreen。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # QQuickWidget 在 offscreen 平台没有 GPU 加速，走软件渲染后端
    os.environ.setdefault("QSG_RHI_BACKEND", "software")
    app = QApplication.instance() or QApplication([])
    yield app


def make_danmaku(msg: str = "弹幕", progress: int = 1000, **kwargs) -> Danmaku:
    """快捷构造弹幕（非 fixture，直接 import 使用）"""
    return Danmaku(msg=msg, progress=progress, **kwargs)


def edit_working(item: EditorItem, **changes) -> EditorItem:
    """替换 EditorItem.working（Danmaku 不可变，测试里改字段用这个）"""
    item.working = item.working.replace(**changes)
    return item


def queue_task_rows() -> list[_QueueTask]:
    """直查 queue_task 全部行（按 position 升序）：断言 position、burst_count 这类不进领域模型的列。"""
    return list(_QueueTask.select().order_by(_QueueTask.position, _QueueTask.task_id))


def queue_item_count(task_id: str) -> int:
    """直查指定任务的弹幕行数：断言级联清空这类表级语义。"""
    return _QueueItem.select().where(_QueueItem.task_id == task_id).count()


def queue_failure_rows(task_id: str) -> list[tuple[int, str]]:
    """直查失败记录行：按 idx 升序给出 (索引, 原因)。"""
    rows = _QueueFailure.select().where(_QueueFailure.task_id == task_id).order_by(_QueueFailure.idx)
    return [(r.idx, r.reason) for r in rows]
