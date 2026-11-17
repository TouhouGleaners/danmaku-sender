"""QueueStore 行存取测试 — 真列落位、结构写与状态写分家、事务与单实例"""

import pytest

from danmaku_sender.infra.persistence.queue_store import (
    FailureRow,
    ItemRow,
    QueueStore,
    TaskRow,
)
from danmaku_sender.types.exceptions.exceptions import QueueStorageError


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
        "status": "PENDING",
    }
    defaults.update(overrides)
    return TaskRow(**defaults)


def make_items(*msgs: str) -> list[ItemRow]:
    return [ItemRow(idx=i, msg=m, progress=i * 1000, mode=1, fontsize=25, color=16777215) for i, m in enumerate(msgs)]


@pytest.fixture
def store(tmp_path):
    opened = QueueStore(tmp_path / "queue.db")
    yield opened
    opened.close()


class TestRoundTrip:
    def test_task_round_trips(self, store):
        row = make_task("t1", 0)
        store.save_task(row, make_items("a", "b"))
        assert store.load_tasks() == [row]

    def test_none_target_round_trips(self, store):
        row = make_task("t1", 0, bvid=None, cid=None)
        store.save_task(row, [])
        assert store.load_tasks() == [row]

    def test_items_load_in_index_order(self, store):
        store.save_task(make_task("t1", 0), make_items("c", "a", "b"))
        assert [it.msg for it in store.load_items("t1")] == ["c", "a", "b"]

    def test_failures_round_trip(self, store):
        store.save_task(make_task("t1", 0), make_items("a", "b"))
        store.add_failure("t1", FailureRow(idx=1, reason="限流"))
        store.add_failure("t1", FailureRow(idx=0, reason="网络异常"))
        assert store.load_failures("t1") == [
            FailureRow(idx=0, reason="网络异常"),
            FailureRow(idx=1, reason="限流"),
        ]

    def test_reopen_reads_back(self, tmp_path):
        db_path = tmp_path / "queue.db"
        store = QueueStore(db_path)
        store.save_task(make_task("t1", 0, cursor=9), make_items("a"))
        store.close()

        reopened = QueueStore(db_path)
        assert reopened.load_tasks() == [make_task("t1", 0, cursor=9)]
        reopened.close()


class TestStructureSave:
    def test_save_replaces_items(self, store):
        store.save_task(make_task("t1", 0), make_items("a", "b", "c"))
        store.save_task(make_task("t1", 0), make_items("x", "y"))
        assert [it.msg for it in store.load_items("t1")] == ["x", "y"]

    def test_save_preserves_hot_columns(self, store):
        """过期的结构保存不得让进度倒退——热列保持库中现值"""
        store.save_task(make_task("t1", 0, cursor=0), make_items("a", "b"))
        store.update_state("t1", status="RUNNING", cursor=7, burst_count=2, error=None)

        stale = make_task("t1", 0, cursor=0, status="PENDING")
        store.save_task(stale, make_items("a", "b"))

        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.burst_count) == ("RUNNING", 7, 2)

    def test_new_row_uses_initial_state(self, store):
        """新建行带落初值；覆盖保存时才保留库中现值"""
        store.save_task(make_task("t1", 0, status="PAUSED", cursor=4), [])
        assert store.load_tasks()[0].status == "PAUSED"
        assert store.load_tasks()[0].cursor == 4


class TestHotUpdate:
    def test_update_state_is_explicit_and_complete(self, store):
        store.save_task(make_task("t1", 0), make_items("a"))
        store.update_state("t1", status="RUNNING", cursor=4, burst_count=2, error="账号被封停")
        store.update_state("t1", status="FAILED", cursor=5, burst_count=0, error=None)
        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.burst_count) == ("FAILED", 5, 0)
        assert row.error is None, "显式传 None 即清空错误"

    def test_update_state_never_touches_structure(self, store):
        store.save_task(make_task("t1", 0), make_items("a", "b"))
        store.update_state("t1", status="FAILED", cursor=1, burst_count=0, error="网络异常")
        assert store.load_tasks()[0].video_title == "标题"
        assert len(store.load_items("t1")) == 2

    def test_update_state_missing_row_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.update_state("ghost", status="PENDING", cursor=0, burst_count=0, error=None)

    def test_add_failure_overwrites_same_index(self, store):
        store.save_task(make_task("t1", 0), make_items("a"))
        store.add_failure("t1", FailureRow(idx=0, reason="限流"))
        store.add_failure("t1", FailureRow(idx=0, reason="网络异常"))
        assert store.load_failures("t1") == [FailureRow(idx=0, reason="网络异常")]


class TestQueueOrder:
    def test_reorder_rewrites_positions(self, store):
        store.save_task(make_task("t1", 0), [])
        store.save_task(make_task("t2", 1), [])
        store.save_task(make_task("t3", 2), [])
        store.reorder(["t3", "t1", "t2"])
        assert [r.task_id for r in store.load_tasks()] == ["t3", "t1", "t2"]
        assert [r.position for r in store.load_tasks()] == [0, 1, 2]


class TestDelete:
    def test_delete_cascades_all_rows(self, store):
        store.save_task(make_task("t1", 0), make_items("a", "b"))
        store.add_failure("t1", FailureRow(idx=0, reason="限流"))
        store.save_task(make_task("t2", 1), make_items("c"))
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

    def test_reopen_after_close_is_allowed(self, tmp_path):
        db_path = tmp_path / "queue.db"
        store = QueueStore(db_path)
        store.close()
        reopened = QueueStore(db_path)
        reopened.close()
