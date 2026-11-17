"""QueueStore 行存取测试 — 真列落位、写入分家、事务语义与单实例闭环"""

import pytest

from danmaku_sender.infra.persistence.queue_store import (
    FailureRow,
    ItemRow,
    QueueStore,
    TaskRow,
)
from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.queue import TaskStatus


def make_task(task_id: str, position: int, **overrides) -> TaskRow:
    defaults = {
        "task_id": task_id,
        "position": position,
        "bvid": "BV1xx",
        "cid": 1001,
        "video_title": "标题",
        "part_page": 2,
        "part_title": "下篇",
        "duration_ms": 30000,
        "source_path": "a.xml",
        "min_delay": 9.5,
        "max_delay": 10.5,
        "burst_enabled": True,
        "burst_size": 5,
        "rest_min": 30.0,
        "rest_max": 35.0,
        "allow_duplicates": False,
        "status": TaskStatus.PENDING,
    }
    defaults.update(overrides)
    return TaskRow(**defaults)


def make_items(*msgs: str, indices: tuple[int, ...] | None = None) -> list[ItemRow]:
    """构造载荷行；indices 可指定乱序下标，用于验「按下标排序」。"""
    idxs = indices if indices is not None else tuple(range(len(msgs)))
    return [
        ItemRow(idx=i, msg=m, progress=n * 1000, mode=1, fontsize=25, color=16777215)
        for n, (i, m) in enumerate(zip(idxs, msgs))
    ]


@pytest.fixture
def store(tmp_path):
    opened = QueueStore(tmp_path / "queue.db")
    yield opened
    opened.close()


class TestRoundTrip:
    def test_task_round_trips(self, store):
        row = make_task("t1", 0)
        store.save_task(row)
        assert store.load_tasks() == [row]

    def test_none_target_round_trips(self, store):
        row = make_task("t1", 0, bvid=None, cid=None)
        store.save_task(row)
        assert store.load_tasks() == [row]

    def test_status_round_trips_as_enum(self, store):
        store.save_task(make_task("t1", 0, status=TaskStatus.PAUSED))
        assert store.load_tasks()[0].status is TaskStatus.PAUSED

    def test_half_target_is_rejected(self, store):
        with pytest.raises(QueueStorageError):
            store.save_task(make_task("t1", 0, cid=None))
        assert store.load_tasks() == []

    def test_items_load_sorted_by_index(self, store):
        """载荷按下标升序读回，与写入顺序无关"""
        store.save_task(make_task("t1", 0), make_items("c", "a", "b", indices=(7, 2, 5)))
        assert [(it.idx, it.msg) for it in store.load_items("t1")] == [(2, "a"), (5, "b"), (7, "c")]

    def test_failures_round_trip(self, store):
        store.save_task(make_task("t1", 0), make_items("a", "b"))
        store.settle("t1", 1, status=TaskStatus.RUNNING, cursor=2, burst_count=0, error=None, failure_reason="限流")
        store.settle("t1", 0, status=TaskStatus.RUNNING, cursor=1, burst_count=0, error=None, failure_reason="网络异常")
        assert store.load_failures("t1") == [
            FailureRow(idx=0, reason="网络异常"),
            FailureRow(idx=1, reason="限流"),
        ]

    def test_reopen_reads_back(self, tmp_path):
        db_path = tmp_path / "queue.db"
        store = QueueStore(db_path)
        store.save_task(make_task("t1", 0), make_items("a"))
        store.update_state("t1", status=TaskStatus.PAUSED, cursor=9, burst_count=1, error=None)
        store.close()

        reopened = QueueStore(db_path)
        try:
            row = reopened.load_tasks()[0]
            assert (row.status, row.cursor, row.burst_count) == (TaskStatus.PAUSED, 9, 1)
            assert [it.msg for it in reopened.load_items("t1")] == ["a"]
        finally:
            reopened.close()


class TestStructureSave:
    def test_save_updates_structure_but_keeps_hot(self, store):
        """过期的结构保存不得让进度倒退——结构照新值、热列保持库中现值"""
        store.save_task(make_task("t1", 0), make_items("a"))
        store.update_state("t1", status=TaskStatus.RUNNING, cursor=7, burst_count=2, error=None)

        store.save_task(make_task("t1", 0, video_title="新标题"))

        row = store.load_tasks()[0]
        assert row.video_title == "新标题", "结构字段按新值更新"
        assert (row.status, row.cursor, row.burst_count) == (TaskStatus.RUNNING, 7, 2), "热列不倒退"

    def test_new_row_uses_initial_state(self, store):
        """新建行带落初值；覆盖保存时才保留库中现值"""
        store.save_task(make_task("t1", 0, status=TaskStatus.PAUSED, cursor=4))
        row = store.load_tasks()[0]
        assert row.status is TaskStatus.PAUSED
        assert row.cursor == 4


class TestItemsWrite:
    def test_items_write_takes_row_state(self, store):
        """换清单即重新入账：载荷整换、失败账清空，运行账整行听本次传入"""
        store.save_task(make_task("t1", 0), make_items("a", "b"))
        store.settle("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=3, error="账号被封停", failure_reason="网络异常")

        store.save_task(make_task("t1", 0, status=TaskStatus.PENDING, error=None), make_items("x", "y", "z"))

        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.burst_count, row.error) == (TaskStatus.PENDING, 0, 0, None)
        assert store.load_failures("t1") == []
        assert [it.msg for it in store.load_items("t1")] == ["x", "y", "z"]

    def test_save_without_items_keeps_payload(self, store):
        store.save_task(make_task("t1", 0), make_items("a", "b"))
        store.save_task(make_task("t1", 0, video_title="新标题"))
        assert [it.msg for it in store.load_items("t1")] == ["a", "b"]


class TestSettle:
    def test_failure_is_recorded_atomically(self, store):
        store.save_task(make_task("t1", 0), make_items("a"))
        store.settle("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络异常", failure_reason="网络异常")
        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.error) == (TaskStatus.FAILED, 1, "网络异常")
        assert store.load_failures("t1") == [FailureRow(idx=0, reason="网络异常")]

    def test_success_clears_stale_failure(self, store):
        """重试成功即清掉该条的旧失败账"""
        store.save_task(make_task("t1", 0), make_items("a"))
        store.settle("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络异常", failure_reason="网络异常")
        store.settle("t1", 0, status=TaskStatus.COMPLETED, cursor=1, burst_count=0, error=None, failure_reason=None)
        assert store.load_failures("t1") == []

    def test_settle_missing_row_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.settle("ghost", 0, status=TaskStatus.PENDING, cursor=1, burst_count=0, error=None, failure_reason=None)


class TestHotUpdate:
    def test_update_state_is_explicit_and_complete(self, store):
        store.save_task(make_task("t1", 0))
        store.update_state("t1", status=TaskStatus.RUNNING, cursor=4, burst_count=2, error="账号被封停")
        assert store.load_tasks()[0].error == "账号被封停", "非空错误确实落库"

        store.update_state("t1", status=TaskStatus.FAILED, cursor=5, burst_count=0, error=None)
        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.burst_count) == (TaskStatus.FAILED, 5, 0)
        assert row.error is None, "显式传 None 即清空错误"

    def test_update_state_never_touches_structure(self, store):
        store.save_task(make_task("t1", 0), make_items("a", "b"))
        store.update_state("t1", status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络异常")
        assert store.load_tasks()[0].video_title == "标题"
        assert len(store.load_items("t1")) == 2

    def test_update_state_missing_row_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.update_state("ghost", status=TaskStatus.PENDING, cursor=0, burst_count=0, error=None)


class TestQueueOrder:
    def test_reorder_rewrites_positions(self, store):
        store.save_task(make_task("t1", 0))
        store.save_task(make_task("t2", 1))
        store.save_task(make_task("t3", 2))
        store.reorder(["t3", "t1", "t2"])
        assert [r.task_id for r in store.load_tasks()] == ["t3", "t1", "t2"]
        assert [r.position for r in store.load_tasks()] == [0, 1, 2]

    def test_reorder_rejects_partial_or_unknown_ids(self, store):
        store.save_task(make_task("t1", 0))
        store.save_task(make_task("t2", 1))
        with pytest.raises(QueueStorageError):
            store.reorder(["t1"])
        with pytest.raises(QueueStorageError):
            store.reorder(["t1", "ghost"])
        assert [r.task_id for r in store.load_tasks()] == ["t1", "t2"], "被拒的重排不得改动队列"

    def test_delete_compacts_positions(self, store):
        """删中间任务后顺序压实，追加不会撞位置"""
        store.save_task(make_task("t1", 0))
        store.save_task(make_task("t2", 1))
        store.save_task(make_task("t3", 2))
        store.delete("t2")
        assert [r.position for r in store.load_tasks()] == [0, 1]
        store.save_task(make_task("t4", 2))
        assert [r.task_id for r in store.load_tasks()] == ["t1", "t3", "t4"]


class TestDelete:
    def test_delete_cascades_all_rows(self, store):
        store.save_task(make_task("t1", 0), make_items("a", "b"))
        store.settle("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="限流", failure_reason="限流")
        store.save_task(make_task("t2", 1))
        store.delete("t1")
        assert [r.task_id for r in store.load_tasks()] == ["t2"]
        assert store.load_items("t1") == []
        assert store.load_failures("t1") == []

    def test_delete_missing_is_noop(self, store):
        store.delete("ghost")


class TestSingleInstance:
    def test_second_store_on_other_path_is_refused(self, store, tmp_path):
        with pytest.raises(QueueStorageError):
            QueueStore(tmp_path / "other.db")

    def test_stale_handle_is_refused_after_reopen_same_path(self, tmp_path):
        """同路径重开后，旧句柄按身份判失效——不得写进新实例的库"""
        db_path = tmp_path / "queue.db"
        stale = QueueStore(db_path)
        stale.close()
        fresh = QueueStore(db_path)
        try:
            with pytest.raises(QueueStorageError):
                stale.save_task(make_task("t1", 0))
            with pytest.raises(QueueStorageError):
                stale.load_tasks()
            fresh.save_task(make_task("t1", 0))
            assert fresh.load_tasks()[0].task_id == "t1"
        finally:
            fresh.close()

    def test_close_on_stale_handle_keeps_live_store(self, tmp_path):
        stale = QueueStore(tmp_path / "a.db")
        stale.close()
        live = QueueStore(tmp_path / "b.db")
        try:
            stale.close()  # 旧句柄再关一次，不得关掉活实例
            live.save_task(make_task("t1", 0))
            assert live.load_tasks()[0].task_id == "t1"
        finally:
            live.close()
