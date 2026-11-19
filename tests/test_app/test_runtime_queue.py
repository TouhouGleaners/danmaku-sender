"""Runtime 的队列启动恢复：崩溃残留纠偏与任务水合。"""

import pytest

from danmaku_sender.app.runtime import Runtime
from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.types.models.common import TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    Task,
    TaskConfig,
    TaskDefinition,
    TaskExecution,
    TaskStatus,
)


@pytest.fixture
def queue_db(tmp_path, monkeypatch):
    monkeypatch.setattr(AppInfo.Paths, "QUEUE_DB", tmp_path / "queue.db")
    return tmp_path / "queue.db"


def _seed_running_row(store: QueueStore) -> None:
    store.add_task(
        Task(
            definition=TaskDefinition(
                task_id="t1",
                target=VideoTarget(bvid="BV1", cid=1),
                meta=TaskMeta(video_title="标题"),
                danmakus=(Danmaku(msg="a", progress=0),),
                config=TaskConfig(min_delay=9.5, max_delay=10.5, burst_enabled=False, burst_size=0, rest_min=0.0, rest_max=0.0),
            ),
            execution=TaskExecution(status=TaskStatus.RUNNING, attempted=7),
        )
    )


def test_startup_pauses_residual_running_and_restores(qapp, queue_db):
    """强杀残留的 RUNNING 纠成可续状态，游标保留，任务装回内存"""
    store = QueueStore(queue_db)
    _seed_running_row(store)
    store.close()

    rt = Runtime()
    opened = rt._open_queue_store()

    views = rt.app_state.workspace.queue_state.tasks
    assert len(views) == 1
    assert views[0].status is TaskStatus.PAUSED
    assert views[0].attempted == 7
    assert [dm.msg for dm in views[0].danmakus] == ["a"]
    opened.close()


def test_startup_without_tasks_leaves_queue_empty(qapp, queue_db):
    rt = Runtime()
    opened = rt._open_queue_store()
    assert rt.app_state.workspace.queue_state.is_empty
    opened.close()


def test_corrupt_db_starts_empty_with_backup(qapp, queue_db):
    """损坏的库改名留存，以空队列启动"""
    queue_db.write_bytes(b"this is not a database")

    rt = Runtime()
    opened = rt._open_queue_store()

    assert rt.app_state.workspace.queue_state.is_empty
    assert list(queue_db.parent.glob("queue.db.corrupt-*"))
    opened.close()
