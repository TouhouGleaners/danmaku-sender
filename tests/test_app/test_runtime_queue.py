"""Runtime 的队列启动恢复：崩溃残留修正、状态对齐写回与任务水合。"""

import pytest

from danmaku_sender.app.runtime import Runtime
from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    DanmakuPack,
    SendOptions,
    Task,
    TaskConfig,
    TaskInfo,
    TaskState,
    TaskStatus,
)
from tests.conftest import queue_task_rows


@pytest.fixture
def queue_db(tmp_path, monkeypatch):
    monkeypatch.setattr(AppInfo.Paths, "QUEUE_DB", tmp_path / "queue.db")
    monkeypatch.setattr(AppInfo.Paths, "HISTORY_DB", tmp_path / "history.db")
    monkeypatch.setattr("danmaku_sender.infra.storage.config_storage.CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("danmaku_sender.infra.storage.account_storage.ACCOUNTS_PATH", tmp_path / "accounts.json")
    return tmp_path / "queue.db"


def _seed_running_row(store: QueueStore) -> None:
    store.add_task(
        Task(
            task_id="t1",
            target=VideoTarget(bvid="BV1", cid=1),
            info=TaskInfo(video_title="标题"),
            pack=DanmakuPack(items=(Danmaku(msg="a", progress=0),)),
            options=SendOptions(pacing=TaskConfig(min_delay=9.5, max_delay=10.5, burst_enabled=False, burst_size=0, rest_min=0.0, rest_max=0.0)),
            state=TaskState(status=TaskStatus.RUNNING, cursor=7),
        )
    )
    store.update_task_state("t1", status=TaskStatus.RUNNING, cursor=7, burst_count=3, error=None)


def test_startup_pauses_residual_running_and_restores(qapp, queue_db):
    """强杀残留的 RUNNING 改为可续状态，游标保留，任务装回内存且修正已写回数据库"""
    store = QueueStore(queue_db)
    _seed_running_row(store)
    store.close()

    rt = Runtime()
    rt.bootstrap()

    views = rt.app_state.workspace.queue_state.tasks
    assert len(views) == 1
    assert views[0].status is TaskStatus.PAUSED
    assert views[0].cursor == 7
    assert [dm.msg for dm in views[0].danmakus] == ["a"]
    persisted = rt.queue_store.load_all()[0]
    assert persisted.status is TaskStatus.PAUSED, "修正过的状态要写回数据库"
    assert persisted.cursor == 7
    assert queue_task_rows()[0].burst_count == 0, "爆发计数不能带着过期值恢复"


def test_startup_without_tasks_leaves_queue_empty(qapp, queue_db):
    rt = Runtime()
    rt.bootstrap()
    assert rt.app_state.workspace.queue_state.is_empty


def test_corrupt_db_starts_empty_with_backup(qapp, queue_db):
    """损坏的库改名留存，以空队列启动"""
    queue_db.write_bytes(b"this is not a database")

    rt = Runtime()
    rt.bootstrap()

    assert rt.app_state.workspace.queue_state.is_empty
    assert list(queue_db.parent.glob("queue.db.corrupt-*"))
