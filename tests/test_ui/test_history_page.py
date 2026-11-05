"""历史页主从布局：时间树取数与下钻。

左侧时间树负责定位，选中任务才让右侧按 task_id 取弹幕；分组节点只展开。
"""
import pytest

from danmaku_sender.config import SenderConfig, Settings
from danmaku_sender.controller.concurrency import PoolTask
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import DanmakuStatus, TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDefinition, TaskStatus
from danmaku_sender.ui.views.history.page import HistoryPage


def _definition(task_id: str) -> TaskDefinition:
    return TaskDefinition(
        task_id=task_id,
        target=VideoTarget(bvid="BV1xx", cid=1001),
        meta=TaskMeta(video_title="标题", part_page=1, part_title="分P"),
        danmakus=(Danmaku(msg="x", progress=0),),
        config=SenderConfig.PacingConfig(min_delay=0.1, max_delay=0.2).to_task_config(),
    )


def _task_row(page: HistoryPage) -> int:
    """展开树并取唯一任务叶子的行号。"""
    page._tree_rows.expand_all()
    model = page._tree_rows
    return next(row for row in range(model.rowCount()) if model.payload_at(row) is not None)


@pytest.fixture
def page(qapp, tmp_path):
    state = AppState()
    settings = Settings()
    hm = HistoryManager(tmp_path / "history.db")
    widget = HistoryPage(state, settings, hm)
    yield widget, hm
    widget.deleteLater()
    qapp.processEvents()


@pytest.fixture(autouse=True)
def sync_pool(monkeypatch):
    """把 PoolTask.submit 改为同步执行，测试内直连异步管线。"""
    monkeypatch.setattr(
        PoolTask,
        "submit",
        lambda fn, on_result, on_error, *args, **kwargs: on_result(fn(*args, **kwargs)),
    )


class TestHistoryDrillDown:
    def test_tasks_fetched_populates_tree(self, page):
        widget, hm = page
        hm.upsert_task(_definition("t1"), TaskStatus.COMPLETED)

        widget._refresh_data()

        assert widget._tree_rows.rowCount() == 1
        record, _stats = widget._tree_rows.payload_at(_task_row(widget))
        assert record == hm.get_task("t1")

    def test_selecting_task_refreshes_with_task_id(self, page):
        widget, hm = page
        hm.upsert_task(_definition("t1"), TaskStatus.COMPLETED)
        widget._refresh_data()

        calls: list = []
        widget.history_controller.query = lambda *args: calls.append(args)

        widget._bridge.treeRowPicked.emit(_task_row(widget))

        assert widget._current_task_id == "t1"
        assert calls == [("", -1, "t1")]

    def test_selecting_task_shows_summary(self, page):
        widget, hm = page
        hm.upsert_task(_definition("t1"), TaskStatus.COMPLETED)
        widget._refresh_data()

        widget._bridge.treeRowPicked.emit(_task_row(widget))

        assert widget._bridge.summaryTitle == "BV1xx  标题"
        assert widget._bridge.summaryPart == "P1  分P"
        assert widget._bridge.summaryRate == "-"
        assert widget._bridge.summaryStats == [
            {"label": "已发送", "value": "0"},
            {"label": "已存活", "value": "0"},
            {"label": "待验证", "value": "0"},
            {"label": "已丢失", "value": "0"},
        ]

    def test_selecting_group_leaves_detail_alone(self, page):
        widget, hm = page
        hm.upsert_task(_definition("t1"), TaskStatus.COMPLETED)
        widget._refresh_data()

        calls: list = []
        widget.history_controller.query = lambda *args: calls.append(args)

        widget._bridge.treeRowPicked.emit(0)

        assert widget._current_task_id is None
        assert calls == []

    def test_status_filter_maps_combo_index(self, page):
        widget, _hm = page
        widget._current_task_id = "t1"
        calls: list = []
        widget.history_controller.query = lambda *args: calls.append(args)

        widget._on_status_selected(2)

        assert widget._status_value == DanmakuStatus.VERIFIED.value
        assert calls == [("", DanmakuStatus.VERIFIED.value, "t1")]

    def test_refresh_without_task_skips_query(self, page):
        widget, _hm = page
        calls: list = []
        widget.history_controller.query = lambda *args: calls.append(args)

        widget._refresh_table()

        assert calls == []

    def test_stale_query_results_are_dropped(self, page):
        widget, _hm = page
        widget.video_controller.fetch_multiple_infos = lambda bvids: None
        widget._query_seq = 2

        widget._on_history_query_succeeded(1, [{"msg": "旧", "bvid": "BV1xx"}])
        assert widget._model.get_record_at(0) is None

        widget._on_history_query_succeeded(2, [{"msg": "新", "bvid": "BV1xx"}])
        assert widget._model.get_record_at(0) == {"msg": "新", "bvid": "BV1xx"}

    def test_out_of_order_queries_drop_old_result(self, page, monkeypatch):
        widget, _hm = page
        widget._current_task_id = "t1"
        widget.video_controller.fetch_multiple_infos = lambda bvids: None
        pending: list = []
        monkeypatch.setattr(
            PoolTask,
            "submit",
            lambda fn, on_result, on_error, *args, **kwargs: pending.append(on_result),
        )

        widget._refresh_table()
        widget._refresh_table()

        pending[1]([{"msg": "新", "bvid": "BV1xx"}])
        pending[0]([{"msg": "旧", "bvid": "BV1xx"}])

        assert widget._model.get_record_at(0) == {"msg": "新", "bvid": "BV1xx"}

    def test_out_of_order_task_loads_drop_old_result(self, page, monkeypatch):
        widget, _hm = page
        pending: list = []
        monkeypatch.setattr(
            PoolTask,
            "submit",
            lambda fn, on_result, on_error, *args, **kwargs: pending.append(on_result),
        )

        widget._refresh_data()
        widget._refresh_data()

        new_row = {
            "task_id": "t2", "bvid": "BV2xx", "cid": 2002, "video_title": "新",
            "part_page": 1, "part_title": "分P", "xml_path": None,
            "created_at": 0.0, "status": "COMPLETED",
        }
        old_row = {**new_row, "task_id": "t1", "bvid": "BV1xx", "video_title": "旧"}

        pending[1](([new_row], {}))
        pending[0](([old_row], {}))

        assert widget._tasks == [new_row]

    def test_summary_title_falls_back_without_video_title(self, page):
        widget, _hm = page
        record = {
            "task_id": "t1", "bvid": "BV1xx", "cid": 1001, "video_title": None,
            "part_page": 1, "part_title": "分P", "xml_path": None,
            "created_at": 0.0, "status": "COMPLETED",
        }
        widget._current_task_id = "t1"

        widget._show_task_identity(record, None)

        assert widget._bridge.summaryTitle == "BV1xx"
        assert widget._bridge.summaryPart == "P1  分P"


class TestRecordActions:
    def test_actions_stay_on_picked_record_after_model_refresh(self, page):
        widget, _hm = page
        shown: list = []
        widget._show_detail_dialog = shown.append

        widget._model.set_records([{"msg": "旧", "bvid": "BV1xx", "cid": 1001}])
        widget._bridge.pick_record(0)
        widget._model.set_records([{"msg": "新", "bvid": "BV2xx", "cid": 2002}])

        widget._bridge.open_record()

        assert shown == [{"msg": "旧", "bvid": "BV1xx", "cid": 1001}]


class TestEmptyState:
    def test_query_failure_shows_error_hint_and_refresh_restores(self, page):
        widget, _hm = page

        widget._on_history_failed(0, Exception("数据库锁定"))
        assert widget._bridge.emptyTitle == "查询失败"
        assert widget._bridge.emptyDescription == "点击「刷新数据」重试"
        assert widget._bridge.emptyActionText == "刷新数据"

        widget._refresh_table()
        assert widget._bridge.emptyTitle == "暂无弹幕记录"
        assert widget._bridge.emptyDescription == "在左侧选择一个任务查看它的弹幕"
        assert widget._bridge.emptyActionText == ""

    def test_stale_failure_is_dropped(self, page):
        widget, _hm = page
        widget._refresh_table()
        widget._query_seq = 2

        widget._on_history_failed(1, Exception("旧请求失败"))

        assert widget._bridge.emptyTitle == "暂无弹幕记录"

    def test_verify_failure_keeps_empty_hint_untouched(self, page):
        widget, _hm = page
        widget._refresh_table()

        widget._on_verify_failed(Exception("网络错误"))

        assert widget._bridge.emptyTitle == "暂无弹幕记录"
