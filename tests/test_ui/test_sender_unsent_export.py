"""SenderPage 未发出弹幕的登记与导出入口。

任务无论完成还是失败，未发出的弹幕都要登记进导出清单。
"""
import pytest

from danmaku_sender.config import SenderConfig
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.service.sender.context import SendingContext
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDraft
from danmaku_sender.ui.views.sender.page import SenderPage

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)


@pytest.fixture
def page(qapp, tmp_path):
    state = AppState()
    hm = HistoryManager(tmp_path / "history.db")
    widget = SenderPage(state, hm)
    yield widget
    widget.deleteLater()
    qapp.processEvents()


def make_ctx(dms: list[Danmaku]) -> SendingContext:
    ctx = SendingContext(total=len(dms), target=TARGET)
    ctx.add_unsent(dms, "异常中断: 测试")
    return ctx


def enqueue_task(state: AppState, dms: list[Danmaku]) -> str:
    """建一条带弹幕的任务，返回 task_id。"""
    draft = TaskDraft(
        target=TARGET,
        danmakus=dms,
        config=SenderConfig(min_delay=0.1, max_delay=0.1).to_task_config(),
    )
    state.queue_state.add_task(draft)
    return draft.task_id


class TestUnsentExport:
    def test_failed_task_registers_unsent(self, page):
        """失败任务的未发出弹幕要能导出"""
        dms = [Danmaku(msg="a", progress=1000), Danmaku(msg="b", progress=1001)]
        task_id = enqueue_task(page.state, dms)

        page._on_queue_task_failed(task_id, "致命错误", make_ctx(dms))

        assert task_id in page._unsent_by_task
        assert [r['dm'].msg for r in page._unsent_by_task[task_id].records] == ["a", "b"]
        assert page._btn_export_unsent.isEnabled()

    def test_completed_task_registers_unsent(self, page):
        """完成任务的未发出弹幕同样要能导出"""
        dms = [Danmaku(msg="a", progress=1000)]
        task_id = enqueue_task(page.state, dms)

        page._on_queue_task_completed(task_id, make_ctx(dms))

        assert task_id in page._unsent_by_task
        assert page._btn_export_unsent.isEnabled()

    def test_clean_run_leaves_export_disabled(self, page):
        """全部发出时导出入口保持禁用"""
        dms = [Danmaku(msg="a", progress=1000)]
        task_id = enqueue_task(page.state, dms)
        ctx = SendingContext(total=1, target=TARGET)
        ctx.success_count = 1

        page._on_queue_task_completed(task_id, ctx)

        assert page._unsent_by_task == {}
        assert not page._btn_export_unsent.isEnabled()
