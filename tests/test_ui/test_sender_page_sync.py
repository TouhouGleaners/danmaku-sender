"""SenderPage 表格行与任务副本的同步。

任务副本全冻结：QueueState 每次变更都换新实例，行里必须换上新值；
只通知重绘会画出旧值，查详情也会打开旧快照。
"""

import pytest

from danmaku_sender.config import SenderConfig, Settings
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDraft, TaskStatus
from danmaku_sender.ui.views.sender.page import SenderPage


@pytest.fixture
def page(qapp, tmp_path):
    state = AppState()
    settings = Settings()
    hm = HistoryManager(tmp_path / "history.db")
    store = QueueStore(tmp_path / "queue.db")
    widget = SenderPage(state, settings, hm, store)
    yield widget
    widget.deleteLater()
    qapp.processEvents()


def _enqueue(page: SenderPage) -> str:
    """入队一条配置齐备的任务，返回 task_id。"""
    draft = TaskDraft(
        target=VideoTarget(bvid="BV1xx411c7mD", cid=1001),
        meta=TaskMeta(video_title="标题"),
        danmakus=[Danmaku(msg="a", progress=0), Danmaku(msg="b", progress=1000)],
        config=SenderConfig.PacingConfig().to_task_config(),
    )
    page.sender_controller.add_task(draft)
    return draft.task_id


class TestRowSync:
    def test_progress_update_swaps_row_value(self, page):
        """进度变更后行里是新任务副本——冻结任务换实例，只重绘会画旧值"""
        task_id = _enqueue(page)
        row = page._queue_model.get_row_by_id(task_id)
        before = page._queue_model.get_task_at(row)
        assert before is not None

        page.state.workspace.queue_state.update_task_progress(task_id, 3, 10)

        after = page._queue_model.get_task_at(row)
        assert after is not None
        assert after is not before, "行里必须是换过的新实例"
        assert after.attempted == 3

    def test_status_update_swaps_row_value(self, page):
        task_id = _enqueue(page)
        row = page._queue_model.get_row_by_id(task_id)
        before = page._queue_model.get_task_at(row)
        assert before is not None

        page.state.workspace.queue_state.update_task_status(task_id, TaskStatus.RUNNING)

        after = page._queue_model.get_task_at(row)
        assert after is not None
        assert after is not before, "行里必须是换过的新实例"
        assert after.status is TaskStatus.RUNNING

    def test_data_update_swaps_row_value(self, page):
        """编辑不改顺序时行里也要换新值（弹幕数等随之刷新）"""
        task_id = _enqueue(page)
        row = page._queue_model.get_row_by_id(task_id)

        page.sender_controller.assign_danmakus(task_id, [Danmaku(msg="x", progress=0)])

        after = page._queue_model.get_task_at(row)
        assert after is not None
        assert after.total == 1
