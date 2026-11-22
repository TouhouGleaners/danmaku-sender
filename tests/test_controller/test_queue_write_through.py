"""SenderController 的队列写穿：结构变更与运行状态先写入数据库再更新内存状态。

每条结构命令写入后，queue.db 里的行、弹幕与顺序都要与内存一致；
关库重开再水合，队列原样回来。
"""

from pathlib import Path

import pytest

from danmaku_sender.config import SenderConfig, Settings
from danmaku_sender.controller.sender.controller import SenderController
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.state import AppState
from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.common import RelativePosition, TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDraft, TaskStatus
from tests.conftest import queue_failure_rows, queue_item_count, queue_task_rows

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)
OTHER_TARGET = VideoTarget(bvid="BV2xx411c7mD", cid=2002)


@pytest.fixture
def env(tmp_path):
    state = AppState()
    settings = Settings()
    hm = HistoryManager(tmp_path / "history.db")
    store = QueueStore(tmp_path / "queue.db")
    controller = SenderController(state, settings, hm, store)
    yield state, store, controller
    store.close()


def make_draft(task_id: str, *, target: VideoTarget = TARGET, title: str = "标题", msgs=("a", "b")) -> TaskDraft:
    return TaskDraft(
        target=target,
        meta=TaskMeta(video_title=title),
        danmakus=[Danmaku(msg=m, progress=idx * 1000) for idx, m in enumerate(msgs)],
        config=SenderConfig.PacingConfig(min_delay=0.1, max_delay=0.1).to_task_config(),
        task_id=task_id,
    )


class TestStructureWriteThrough:
    def test_add_persists_row_and_items(self, env):
        _, store, controller = env
        controller.add_task(make_draft("t1"))

        task = store.load_all()[0]
        assert (task.task_id, task.meta.video_title, task.status) == ("t1", "标题", TaskStatus.PENDING)
        assert [dm.msg for dm in task.danmakus] == ["a", "b"]

    def test_insert_lands_in_slot(self, env):
        _, store, controller = env
        controller.add_task(make_draft("t1", msgs=("a",)))
        controller.add_task(make_draft("t3", msgs=("c",)))

        controller.insert_task(make_draft("t2", msgs=("b",)), ref_task_id="t1", position=RelativePosition.BELOW)

        assert [t.task_id for t in store.load_all()] == ["t1", "t2", "t3"]
        assert [r.position for r in queue_task_rows()] == [0, 1, 2]

    def test_move_and_reorder_persist_order(self, env):
        _, store, controller = env
        for task_id in ("t1", "t2", "t3"):
            controller.add_task(make_draft(task_id, msgs=(task_id,)))

        controller.move_task("t1", RelativePosition.BELOW)
        assert [t.task_id for t in store.load_all()] == ["t2", "t1", "t3"]

        controller.reorder_tasks(["t3", "t2", "t1"])
        assert [t.task_id for t in store.load_all()] == ["t3", "t2", "t1"]

    def test_remove_deletes_rows(self, env):
        _, store, controller = env
        controller.add_task(make_draft("t1"))
        controller.add_task(make_draft("t2", msgs=("x",)))

        controller.remove_task("t1")

        assert [t.task_id for t in store.load_all()] == ["t2"]
        assert queue_item_count("t1") == 0

    def test_clear_all_empties_store(self, env):
        _, store, controller = env
        controller.add_task(make_draft("t1"))
        controller.add_task(make_draft("t2", msgs=("x",)))

        controller.clear_all()

        assert store.load_all() == []


class TestEditWriteThrough:
    def test_config_only_edit_keeps_items_and_progress(self, env):
        state, store, controller = env
        controller.add_task(make_draft("t1"))
        controller._on_task_progress("t1", 1, 2, 0.0)

        view = state.workspace.queue_state.get_task_by_id("t1")
        assert view is not None
        draft = view.to_draft()
        draft.meta = TaskMeta(video_title="新标题")
        controller.apply_edit("t1", draft)

        task = store.load_all()[0]
        assert task.meta.video_title == "新标题"
        assert task.attempted == 1, "清单没变，进度不倒退"
        assert [dm.msg for dm in task.danmakus] == ["a", "b"]

    def test_new_list_resets_cursor(self, env):
        state, store, controller = env
        controller.add_task(make_draft("t1"))
        controller._on_task_progress("t1", 1, 2, 0.0)

        view = state.workspace.queue_state.get_task_by_id("t1")
        assert view is not None
        draft = view.to_draft()
        draft.danmakus = [Danmaku(msg="x", progress=0)]
        controller.apply_edit("t1", draft)

        task = store.load_all()[0]
        assert task.attempted == 0
        assert [dm.msg for dm in task.danmakus] == ["x"]

    def test_retarget_replaces_row(self, env):
        state, store, controller = env
        controller.add_task(make_draft("t1"))

        view = state.workspace.queue_state.get_task_by_id("t1")
        assert view is not None
        draft = view.to_draft()
        draft.target = OTHER_TARGET
        controller.apply_edit("t1", draft)

        tasks = store.load_all()
        assert len(tasks) == 1, "旧任务不得残留在库里"
        assert tasks[0].task_id != "t1"
        assert (tasks[0].target.bvid, tasks[0].target.cid) == ("BV2xx411c7mD", 2002)
        assert tasks[0].attempted == 0
        assert queue_item_count("t1") == 0
        assert [dm.msg for dm in tasks[0].danmakus] == ["a", "b"]

    def test_assign_same_list_keeps_payload_and_failures(self, env):
        """清单没变时弹幕与失败记录原样保留，来源文件的修改照常写入数据库"""
        _, store, controller = env
        controller.add_task(make_draft("t1"))
        store.record_result("t1", 0, status=TaskStatus.FAILED, cursor=1, burst_count=0, error="网络错误", failure_reason="网络错误")

        controller.assign_danmakus(
            "t1",
            [Danmaku(msg="a", progress=0), Danmaku(msg="b", progress=1000)],
            xml_path=Path("new.xml"),
        )

        task = store.load_all()[0]
        assert str(task.meta.xml_path) == "new.xml", "来源文件的修改要写入数据库"
        assert [dm.msg for dm in task.danmakus] == ["a", "b"]
        assert queue_failure_rows("t1"), "清单没变，失败记录不得被清掉"

    def test_assign_new_list_replaces_items(self, env):
        _, store, controller = env
        controller.add_task(make_draft("t1"))
        controller._on_task_progress("t1", 1, 2, 0.0)

        controller.assign_danmakus("t1", [Danmaku(msg="x", progress=0)])

        task = store.load_all()[0]
        assert task.attempted == 0
        assert [dm.msg for dm in task.danmakus] == ["x"]

    def test_assign_completing_config_keeps_store_in_sync(self, env):
        """补全弹幕后状态翻成待发：库里与内存同一取值"""
        state, store, controller = env
        controller.add_task(make_draft("t1", msgs=()))

        controller.assign_danmakus("t1", [Danmaku(msg="a", progress=0)])

        task = store.load_all()[0]
        view = state.workspace.queue_state.get_task_by_id("t1")
        assert task.status is TaskStatus.PENDING
        assert view is not None and view.status is TaskStatus.PENDING


class TestStoreFailure:
    def test_write_failure_raises_and_keeps_memory_untouched(self, env, monkeypatch):
        """写库失败向上抛出异常，内存保持原样"""
        state, store, controller = env

        def boom(task):
            raise QueueStorageError("磁盘写满")

        monkeypatch.setattr(store, "add_task", boom)

        with pytest.raises(QueueStorageError):
            controller.add_task(make_draft("t1"))

        assert state.workspace.queue_state.is_empty


class TestRunStateWriteThrough:
    def test_progress_mirrors_cursor(self, env):
        _, store, controller = env
        controller.add_task(make_draft("t1"))

        controller._on_task_started("t1", 0)
        controller._on_task_progress("t1", 2, 2, 0.0)

        task = store.load_all()[0]
        assert (task.status, task.attempted) == (TaskStatus.RUNNING, 2)

    def test_reset_progress_zeroes_cursor(self, env):
        _, store, controller = env
        controller.add_task(make_draft("t1"))
        controller._on_task_progress("t1", 1, 2, 0.0)

        controller.reset_progress("t1")

        assert store.load_all()[0].attempted == 0

    def test_reset_queue_removes_completed_and_revives_failed(self, env):
        _, store, controller = env
        controller.add_task(make_draft("t1", msgs=("a",)))
        controller.add_task(make_draft("t2", msgs=("x",)))
        controller._on_task_started("t1", 0)
        controller._on_task_completed("t1", None)
        controller._on_task_started("t2", 1)
        controller._on_task_failed("t2", "网络错误", None)

        controller.reset_queue()

        tasks = store.load_all()
        assert [t.task_id for t in tasks] == ["t2"]
        assert (tasks[0].status, tasks[0].attempted, tasks[0].error_msg) == (TaskStatus.PENDING, 0, "")


class TestRestartRoundTrip:
    def test_queue_survives_restart(self, tmp_path):
        db_path = tmp_path / "queue.db"
        state = AppState()
        store = QueueStore(db_path)
        controller = SenderController(state, Settings(), HistoryManager(tmp_path / "history.db"), store)
        controller.add_task(make_draft("t1"))
        controller.insert_task(make_draft("t2", msgs=("x",)), ref_task_id="t1", position=RelativePosition.BELOW)
        controller._on_task_started("t1", 0)
        controller._on_task_progress("t1", 1, 2, 0.0)
        store.close()

        reopened = QueueStore(db_path)
        try:
            recovered = reopened.load_all()
        finally:
            reopened.close()
        restored = AppState()
        restored.workspace.queue_state.restore_tasks(recovered)

        views = restored.workspace.queue_state.tasks
        assert [v.task_id for v in views] == ["t1", "t2"]
        assert [dm.msg for dm in views[0].danmakus] == ["a", "b"]
        assert (views[0].status, views[0].attempted) == (TaskStatus.RUNNING, 1)
