"""SenderController 的任务级历史落账。

任务进入发送管线时写 task_record，终态时更新状态，供按任务对账。
"""

import pytest
from PySide6.QtCore import QObject, Signal

from danmaku_sender.config import SenderConfig, Settings
from danmaku_sender.controller.sender import controller as sender_controller_mod
from danmaku_sender.controller.sender.controller import SenderController
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.service.sender.context import SendingContext
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDraft, TaskStatus

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)


class StubSendWorker(QObject):
    """不启动线程的发送 Worker 替身：只验落账，不碰网络。

    信号集与 QueueSendWorker 对齐，否则 start_queue 的 connect 会失败。
    """

    taskStarted = Signal(str, int)
    taskCompleted = Signal(str, object)
    taskFailed = Signal(str, str, object)
    taskSkipped = Signal(str, str)
    queueCompleted = Signal()
    queueAborted = Signal()
    queueProgressUpdated = Signal(int, int, float)
    taskProgressUpdated = Signal(str, int, int, float)
    ending = Signal(object)
    finished = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__()

    def start(self) -> None:
        pass

    def isRunning(self) -> bool:
        return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(sender_controller_mod, "QueueSendWorker", StubSendWorker)
    state = AppState()
    settings = Settings()
    hm = HistoryManager(tmp_path / "history.db")
    controller = SenderController(state, settings, hm)
    return state, hm, controller


def _enqueue(state: AppState, task_id: str) -> str:
    draft = TaskDraft(
        target=TARGET,
        meta=TaskMeta(video_title="标题"),
        danmakus=[Danmaku(msg="a", progress=1000)],
        config=SenderConfig(min_delay=0.1, max_delay=0.1).to_task_config(),
        task_id=task_id,
    )
    state.workspace.queue_state.add_task(draft)
    return task_id


class TestTaskRecordLifecycle:
    def test_start_writes_running(self, env):
        state, hm, controller = env
        _enqueue(state, "任务-A")

        controller._on_task_started("任务-A", 0)

        row = hm.get_task("任务-A")
        assert row is not None
        assert row["status"] == "RUNNING"
        assert row["video_title"] == "标题"

    def test_completed_updates_status(self, env):
        state, hm, controller = env
        task_id = _enqueue(state, "任务-A")
        controller._on_task_started(task_id, 0)

        controller._on_task_completed(task_id, SendingContext(total=1, target=TARGET))

        assert hm.get_task(task_id)["status"] == "COMPLETED"

    def test_paused_when_manually_stopped(self, env):
        state, hm, controller = env
        task_id = _enqueue(state, "任务-A")
        controller._on_task_started(task_id, 0)

        ctx = SendingContext(total=1, target=TARGET)
        ctx.is_manually_stopped = True
        controller._on_task_completed(task_id, ctx)

        assert hm.get_task(task_id)["status"] == "PAUSED"

    def test_failed_writes_terminal_status(self, env):
        state, hm, controller = env
        task_id = _enqueue(state, "任务-失败")

        controller._on_task_started(task_id, 0)
        controller._on_task_failed(task_id, "网络错误", SendingContext(total=1, target=TARGET))

        assert hm.get_task(task_id)["status"] == "FAILED"

    def test_skipped_writes_no_record(self, env):
        """SKIPPED 从未发包、无存证可对账，不写任务记录"""
        state, hm, controller = env
        task_id = _enqueue(state, "任务-跳过")

        controller._on_task_skipped(task_id, "未指定视频目标")

        assert hm.get_task(task_id) is None

    def test_skipped_keeps_existing_record(self, env):
        """跑过后来被跳过的任务，保留原终态，不覆盖成 SKIPPED"""
        state, hm, controller = env
        task_id = _enqueue(state, "任务-A")
        controller._on_task_started(task_id, 0)
        controller._on_task_completed(task_id, SendingContext(total=1, target=TARGET))

        controller._on_task_skipped(task_id, "未指定视频目标")

        assert hm.get_task(task_id)["status"] == "COMPLETED"

    def test_missing_task_skips_write(self, env):
        """队列里已不存在的任务跳过落账，不抛异常"""
        _, hm, controller = env
        controller._persist_task_record("ghost", TaskStatus.RUNNING)
        assert hm.get_task("ghost") is None
