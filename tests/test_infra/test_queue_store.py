"""QueueStore 存取测试 — 领域对象持久化、写入分家与事务语义"""

from pathlib import Path

import pytest

from danmaku_sender.infra.persistence.queue_store import FailureRow, QueueStore
from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.common import TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    Task,
    TaskConfig,
    TaskDefinition,
    TaskExecution,
    TaskStatus,
)


def make_danmakus(*msgs: str) -> tuple[Danmaku, ...]:
    """按顺序构造弹幕清单；出现时间按索引递增。"""
    return tuple(Danmaku(msg=m, progress=idx * 1000) for idx, m in enumerate(msgs))


def make_task(
    task_id: str,
    *,
    bvid: str | None = "BV1xx",
    cid: int | None = 1001,
    title: str = "标题",
    part_page: int | None = 2,
    part_title: str = "下篇",
    duration_ms: int | None = 30000,
    source_path: str | None = "a.xml",
    status: TaskStatus = TaskStatus.PENDING,
    cursor: int = 0,
    error: str = "",
    msgs: tuple[str, ...] = (),
) -> Task:
    """构造领域任务，弹幕清单随 ``msgs`` 带入。"""
    return Task(
        definition=TaskDefinition(
            task_id=task_id,
            target=VideoTarget(bvid=bvid, cid=cid),
            meta=TaskMeta(
                video_title=title,
                part_page=part_page,
                part_title=part_title,
                part_duration_ms=duration_ms,
                xml_path=Path(source_path) if source_path else None,
            ),
            danmakus=make_danmakus(*msgs),
            config=TaskConfig(
                min_delay=9.5,
                max_delay=10.5,
                burst_enabled=True,
                burst_size=5,
                rest_min=30.0,
                rest_max=35.0,
            ),
        ),
        execution=TaskExecution(status=status, error_msg=error, attempted=cursor),
    )


@pytest.fixture
def store(tmp_path):
    opened = QueueStore(tmp_path / "queue.db")
    yield opened
    opened.close()


class TestRoundTrip:
    def test_task_round_trips(self, store):
        task = make_task("t1")
        store.add_task(task)
        assert store.load_all() == [task]

    def test_none_target_round_trips(self, store):
        task = make_task("t1", bvid=None, cid=None)
        store.add_task(task)
        assert store.load_all() == [task]

    def test_status_round_trips_as_enum(self, store):
        store.add_task(make_task("t1", status=TaskStatus.PAUSED))
        assert store.load_tasks()[0].status is TaskStatus.PAUSED

    def test_half_target_is_rejected(self, store):
        with pytest.raises(QueueStorageError):
            store.add_task(make_task("t1", cid=None))
        assert store.load_all() == []

    def test_items_round_trip_in_order(self, store):
        store.add_task(make_task("t1", msgs=("c", "a", "b")))
        assert [dm.msg for dm in store.load_all()[0].definition.danmakus] == ["c", "a", "b"]
        assert [it.msg for it in store.load_items("t1")] == ["c", "a", "b"]

    def test_failures_round_trip(self, store):
        store.add_task(make_task("t1", msgs=("a", "b")))
        store.record_result("t1", 1, status=TaskStatus.RUNNING, cursor=2, burst_count=0, error=None, failure_reason="限流")
        store.record_result("t1", 0, status=TaskStatus.RUNNING, cursor=1, burst_count=0, error=None, failure_reason="网络异常")
        assert store.load_failures("t1") == [
            FailureRow(idx=0, reason="网络异常"),
            FailureRow(idx=1, reason="限流"),
        ]

    def test_reopen_reads_back(self, tmp_path):
        db_path = tmp_path / "queue.db"
        store = QueueStore(db_path)
        store.add_task(make_task("t1", msgs=("a",)))
        store.update_task_state("t1", status=TaskStatus.PAUSED, cursor=9, burst_count=1, error=None)
        store.close()

        reopened = QueueStore(db_path)
        try:
            task = reopened.load_all()[0]
            assert (task.execution.status, task.execution.attempted) == (TaskStatus.PAUSED, 9)
            assert [dm.msg for dm in task.definition.danmakus] == ["a"]
        finally:
            reopened.close()


class TestUpdateTask:
    def test_update_writes_structure_and_state(self, store):
        """整行更新：结构与运行状态都听新值"""
        store.add_task(make_task("t1", msgs=("a",)))
        store.update_task_state("t1", status=TaskStatus.RUNNING, cursor=7, burst_count=2, error=None)

        store.update_task(make_task("t1", title="新标题", status=TaskStatus.PAUSED, cursor=3))

        row = store.load_tasks()[0]
        assert row.video_title == "新标题"
        assert (row.status, row.cursor) == (TaskStatus.PAUSED, 3), "状态与进度按新值写入"

    def test_update_without_replace_keeps_payload_and_failures(self, store):
        store.add_task(make_task("t1", msgs=("a", "b")))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络异常", failure_reason="网络异常")

        store.update_task(make_task("t1", title="新标题", msgs=("a", "b")))

        assert [it.msg for it in store.load_items("t1")] == ["a", "b"]
        assert store.load_failures("t1") == [FailureRow(idx=0, reason="网络异常")]

    def test_replacing_items_resets_run(self, store):
        """换清单即新的一趟：载荷整换、失败记录清空，状态与进度听本次传入"""
        store.add_task(make_task("t1", msgs=("a", "b")))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=3, error="账号被封停", failure_reason="网络异常")

        store.update_task(make_task("t1", status=TaskStatus.PENDING, msgs=("x", "y", "z")), items_replaced=True)

        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.burst_count, row.error) == (TaskStatus.PENDING, 0, 0, None)
        assert store.load_failures("t1") == []
        assert [it.msg for it in store.load_items("t1")] == ["x", "y", "z"]

    def test_update_missing_row_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.update_task(make_task("ghost"))


class TestRecordResult:
    def test_failure_is_recorded_atomically(self, store):
        store.add_task(make_task("t1", msgs=("a",)))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络异常", failure_reason="网络异常")
        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.error) == (TaskStatus.FAILED, 1, "网络异常")
        assert store.load_failures("t1") == [FailureRow(idx=0, reason="网络异常")]

    def test_success_clears_stale_failure(self, store):
        """重试成功即清掉该条的旧失败记录"""
        store.add_task(make_task("t1", msgs=("a",)))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络异常", failure_reason="网络异常")
        store.record_result("t1", 0, status=TaskStatus.COMPLETED, cursor=1, burst_count=0, error=None, failure_reason=None)
        assert store.load_failures("t1") == []

    def test_record_result_missing_row_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.record_result("ghost", 0, status=TaskStatus.PENDING, cursor=1, burst_count=0, error=None, failure_reason=None)


class TestTaskStateUpdate:
    def test_update_state_is_explicit_and_complete(self, store):
        store.add_task(make_task("t1"))
        store.update_task_state("t1", status=TaskStatus.RUNNING, cursor=4, burst_count=2, error="账号被封停")
        assert store.load_tasks()[0].error == "账号被封停", "非空错误确实写入"

        store.update_task_state("t1", status=TaskStatus.FAILED, cursor=5, burst_count=0, error=None)
        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.burst_count) == (TaskStatus.FAILED, 5, 0)
        assert row.error is None, "显式传 None 即清空错误"

    def test_update_state_never_touches_structure(self, store):
        store.add_task(make_task("t1", msgs=("a", "b")))
        store.update_task_state("t1", status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络异常")
        assert store.load_tasks()[0].video_title == "标题"
        assert len(store.load_items("t1")) == 2

    def test_update_state_missing_row_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.update_task_state("ghost", status=TaskStatus.PENDING, cursor=0, burst_count=0, error=None)


class TestResetTasks:
    def test_reset_zeroes_run_and_clears_failures(self, store):
        store.add_task(make_task("t1", msgs=("a",)))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=2, error="网络异常", failure_reason="网络异常")

        store.reset_tasks(["t1"], status=TaskStatus.PENDING, error=None)

        row = store.load_tasks()[0]
        assert (row.status, row.cursor, row.burst_count, row.error) == (TaskStatus.PENDING, 0, 0, None)
        assert store.load_failures("t1") == []

    def test_reset_missing_row_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.reset_tasks(["ghost"], status=TaskStatus.PENDING, error=None)


class TestQueueOrder:
    def test_reorder_rewrites_positions(self, store):
        for task_id in ("t1", "t2", "t3"):
            store.add_task(make_task(task_id))
        store.reorder_tasks(["t3", "t1", "t2"])
        assert [r.task_id for r in store.load_tasks()] == ["t3", "t1", "t2"]
        assert [r.position for r in store.load_tasks()] == [0, 1, 2]

    def test_reorder_rejects_partial_or_unknown_ids(self, store):
        store.add_task(make_task("t1"))
        store.add_task(make_task("t2"))
        with pytest.raises(QueueStorageError):
            store.reorder_tasks(["t1"])
        with pytest.raises(QueueStorageError):
            store.reorder_tasks(["t1", "ghost"])
        assert [r.task_id for r in store.load_tasks()] == ["t1", "t2"], "被拒的重排不得改动队列"

    def test_insert_shifts_following_rows(self, store):
        store.add_task(make_task("t1"))
        store.add_task(make_task("t3"))
        store.insert_task(make_task("t2"), at=1)
        assert [r.task_id for r in store.load_tasks()] == ["t1", "t2", "t3"]
        assert [r.position for r in store.load_tasks()] == [0, 1, 2]

    def test_delete_compacts_positions(self, store):
        """删中间任务后顺序压实，追加不会撞位置"""
        for task_id in ("t1", "t2", "t3"):
            store.add_task(make_task(task_id))
        store.delete_tasks(["t2"])
        assert [r.position for r in store.load_tasks()] == [0, 1]
        store.add_task(make_task("t4"))
        assert [r.task_id for r in store.load_tasks()] == ["t1", "t3", "t4"]


class TestDelete:
    def test_delete_cascades_all_rows(self, store):
        store.add_task(make_task("t1", msgs=("a", "b")))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="限流", failure_reason="限流")
        store.add_task(make_task("t2"))

        store.delete_tasks(["t1"])

        assert [r.task_id for r in store.load_tasks()] == ["t2"]
        assert store.load_items("t1") == []
        assert store.load_failures("t1") == []

    def test_delete_missing_is_noop(self, store):
        store.delete_tasks(["ghost"])


class TestLoadAll:
    def test_load_all_assembles_complete_tasks(self, store):
        """弹幕随行装齐，状态按库里的原值读出，顺序按 position"""
        store.add_task(make_task("t1", status=TaskStatus.PAUSED, cursor=3, msgs=("a", "b", "c")))
        store.add_task(make_task("t2", title="二号"))

        tasks = store.load_all()

        assert [t.definition.task_id for t in tasks] == ["t1", "t2"]
        assert [dm.msg for dm in tasks[0].definition.danmakus] == ["a", "b", "c"]
        assert (tasks[0].execution.status, tasks[0].execution.attempted) == (TaskStatus.PAUSED, 3)
        assert tasks[1].definition.meta.video_title == "二号"

    def test_load_all_round_trips_danmaku_fields(self, store):
        store.add_task(make_task("t1", msgs=("a",)))
        dm = store.load_all()[0].definition.danmakus[0]
        assert (dm.msg, dm.progress, dm.mode, dm.fontsize, dm.color) == ("a", 0, 1, 25, 16777215)

    def test_load_all_keeps_empty_list_empty(self, store):
        """清单本来就是空的任务不硬塞弹幕"""
        store.add_task(make_task("t1"))
        assert store.load_all()[0].definition.danmakus == ()

    def test_load_all_keeps_unassigned_target(self, store):
        store.add_task(make_task("t1", bvid=None, cid=None))
        task = store.load_all()[0]
        assert (task.definition.target.bvid, task.definition.target.cid) == (None, None)


class TestReissue:
    def test_reissue_swaps_id_and_keeps_slot(self, store):
        store.add_task(make_task("t1", title="旧", msgs=("a",)))
        store.add_task(make_task("t2"))

        store.reissue_task("t1", make_task("t9", title="新", msgs=("x", "y")))

        rows = store.load_tasks()
        assert [r.task_id for r in rows] == ["t9", "t2"]
        assert rows[0].position == 0
        assert rows[0].video_title == "新"
        assert [it.msg for it in store.load_items("t9")] == ["x", "y"]
        assert store.load_items("t1") == []

    def test_reissue_clears_failures(self, store):
        """换任务后失败记录不随旧行带走"""
        store.add_task(make_task("t1", msgs=("a",)))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络异常", failure_reason="网络异常")

        store.reissue_task("t1", make_task("t9", cursor=0, msgs=("a",)))

        assert store.load_failures("t1") == []
        assert store.load_failures("t9") == []

    def test_reissue_missing_old_raises(self, store):
        with pytest.raises(QueueStorageError):
            store.reissue_task("ghost", make_task("t9", msgs=("a",)))
        assert store.load_all() == [], "被拒的换发不得落任何行"


class TestClearAll:
    def test_clear_all_empties_every_table(self, store):
        store.add_task(make_task("t1", msgs=("a", "b")))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="限流", failure_reason="限流")
        store.add_task(make_task("t2"))

        store.clear_all()

        assert store.load_tasks() == []
        assert store.load_items("t1") == []
        assert store.load_failures("t1") == []


class TestReopen:
    def test_reopen_same_path_after_close(self, tmp_path):
        """关了再开同一路径，数据还在、写入照常"""
        db_path = tmp_path / "queue.db"
        first = QueueStore(db_path)
        first.add_task(make_task("t1"))
        first.close()

        second = QueueStore(db_path)
        try:
            second.add_task(make_task("t2"))
            assert [r.task_id for r in second.load_tasks()] == ["t1", "t2"]
        finally:
            second.close()


class TestOpenWithRecovery:
    def test_corrupt_db_backs_up_and_reopens_empty(self, tmp_path):
        db_path = tmp_path / "queue.db"
        db_path.write_bytes(b"this is not a database")

        store = QueueStore.open_with_recovery(db_path)

        assert store.load_all() == []
        assert list(tmp_path.glob("queue.db.corrupt-*"))
        store.close()

    def test_second_corruption_still_backs_up_and_reopens(self, tmp_path):
        """第二次损坏照样备份重开：备份名不与旧备份相撞"""
        db_path = tmp_path / "queue.db"
        db_path.write_bytes(b"garbage one")
        first = QueueStore.open_with_recovery(db_path)
        first.close()
        db_path.write_bytes(b"garbage two")

        second = QueueStore.open_with_recovery(db_path)

        assert second.load_all() == []
        assert len(list(tmp_path.glob("queue.db.corrupt-*"))) == 2
        second.close()

    def test_unreadable_but_valid_db_is_not_clobbered(self, tmp_path, monkeypatch):
        """文件头完好却读不动的库按临时故障处理：保留原文件并向上抛出，不备份不重建"""
        db_path = tmp_path / "queue.db"
        first = QueueStore(db_path)
        first.add_task(make_task("t1"))
        first.close()

        def flaky_load_all(self):
            raise QueueStorageError("临时锁定")

        monkeypatch.setattr(QueueStore, "load_all", flaky_load_all)

        with pytest.raises(QueueStorageError):
            QueueStore.open_with_recovery(db_path)

        assert not list(tmp_path.glob("queue.db.corrupt-*"))
        assert db_path.exists()

    def test_backup_failure_raises_instead_of_reopening_corrupt(self, tmp_path, monkeypatch):
        """坏库挪不走时不得重开原路径，显式报错"""
        db_path = tmp_path / "queue.db"
        db_path.write_bytes(b"garbage")
        monkeypatch.setattr(
            "danmaku_sender.infra.persistence.queue_store.backup_corrupt_file",
            lambda path, suffix=".corrupt": None,
        )

        with pytest.raises(QueueStorageError):
            QueueStore.open_with_recovery(db_path)

    def test_backup_takes_wal_and_shm_along(self, tmp_path):
        """备份要连 -wal / -shm 一起改名，否则重建时 SQLite 会重放旧 WAL"""
        for suffix in ("", "-wal", "-shm"):
            (tmp_path / f"queue.db{suffix}").write_bytes(b"junk")

        QueueStore._backup_corrupt(tmp_path / "queue.db")

        remaining = sorted(p.name for p in tmp_path.iterdir())
        assert len(remaining) == 3
        for suffix in ("", "-wal", "-shm"):
            assert not (tmp_path / f"queue.db{suffix}").exists()
            assert any(name.startswith(f"queue.db{suffix}.corrupt") for name in remaining), remaining
