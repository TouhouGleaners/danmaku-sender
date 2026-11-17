"""QueueStore 行存取测试 — 冷热分列、顺序与覆盖语义"""

import json

import pytest

from danmaku_sender.infra.persistence.queue_store import QueueRow, QueueStore
from danmaku_sender.types.exceptions.exceptions import QueueStorageError

DEST = json.dumps({"bvid": "BV1xx", "cid": 1001, "video_title": "标题"})
PACK = json.dumps({"items": ["a", "b", "c"], "source_path": "a.xml"})
OPTIONS = json.dumps({"allow_duplicates": False})


def make_row(task_id: str, position: int, **overrides) -> QueueRow:
    defaults = {
        "task_id": task_id,
        "position": position,
        "destination_json": DEST,
        "pack_json": PACK,
        "options_json": OPTIONS,
        "status": "PENDING",
    }
    defaults.update(overrides)
    return QueueRow(**defaults)


@pytest.fixture
def store(tmp_path):
    return QueueStore(tmp_path / "queue.db")


class TestRoundTrip:
    def test_save_and_load(self, store):
        row = make_row("t1", 0)
        store.save(row)
        assert store.load_rows() == [row]

    def test_none_destination_round_trips(self, store):
        row = make_row("t1", 0, destination_json=None)
        store.save(row)
        assert store.load_rows()[0].destination_json is None

    def test_error_none_and_text_round_trip(self, store):
        store.save(make_row("t1", 0))
        assert store.load_rows()[0].error is None
        store.save(make_row("t1", 0, error="账号被封停"))
        assert store.load_rows()[0].error == "账号被封停"

    def test_rows_load_in_position_order(self, store):
        store.save(make_row("t2", 1))
        store.save(make_row("t1", 0))
        store.save(make_row("t3", 2))
        assert [r.task_id for r in store.load_rows()] == ["t1", "t2", "t3"]


class TestUpsert:
    def test_save_overwrites_same_task(self, store):
        store.save(make_row("t1", 0, cursor=0))
        store.save(make_row("t1", 5, cursor=7, status="PAUSED"))
        rows = store.load_rows()
        assert len(rows) == 1
        assert rows[0].position == 5
        assert rows[0].cursor == 7
        assert rows[0].status == "PAUSED"

    def test_save_moves_task_in_queue_order(self, store):
        store.save(make_row("t1", 0))
        store.save(make_row("t2", 1))
        store.save(make_row("t1", 2))
        assert [r.task_id for r in store.load_rows()] == ["t2", "t1"]


class TestHotColumns:
    def test_update_state_touches_hot_only(self, store):
        store.save(make_row("t1", 0, cursor=0))
        store.update_state(
            "t1",
            status="RUNNING",
            cursor=4,
            burst_count=2,
            failed_json='[[3, "限流"]]',
            error=None,
        )
        row = store.load_rows()[0]
        assert (row.status, row.cursor, row.burst_count) == ("RUNNING", 4, 2)
        assert row.failed_json == '[[3, "限流"]]'
        # 冷列原样不动
        assert row.destination_json == DEST
        assert row.pack_json == PACK
        assert row.options_json == OPTIONS
        assert row.position == 0

    def test_update_state_missing_row_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.update_state("ghost", status="PENDING", cursor=0)


class TestDelete:
    def test_delete_removes_row(self, store):
        store.save(make_row("t1", 0))
        store.save(make_row("t2", 1))
        store.delete("t1")
        assert [r.task_id for r in store.load_rows()] == ["t2"]

    def test_delete_missing_is_noop(self, store):
        store.delete("ghost")

    def test_reopen_reads_back(self, tmp_path):
        db_path = tmp_path / "queue.db"
        store = QueueStore(db_path)
        store.save(make_row("t1", 0, cursor=9))
        store.close()

        reopened = QueueStore(db_path)
        assert reopened.load_rows() == [make_row("t1", 0, cursor=9)]
