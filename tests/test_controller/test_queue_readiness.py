"""SenderController.queue_readiness 的判定口径。

凭证缺失与队列无可执行任务是两种独立的未满足条件；PAUSED 属于可启动范围。
"""

import uuid

from danmaku_sender.config import Settings
from danmaku_sender.controller.sender import SenderController
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import StartReadiness, VideoTarget
from danmaku_sender.types.models.queue import (
    DanmakuPack,
    SendOptions,
    Task,
    TaskInfo,
    TaskState,
    TaskStatus,
)


def _task(status: TaskStatus) -> Task:
    return Task(
        task_id=uuid.uuid4().hex,
        target=VideoTarget(bvid="BV1", cid=1),
        info=TaskInfo(),
        pack=DanmakuPack(),
        options=SendOptions(pacing=Settings().sender_config.pacing.to_task_config()),
        state=TaskState(status=status),
    )


def _controller(tmp_path) -> tuple[SenderController, AppState]:
    state = AppState()
    settings = Settings()
    history = HistoryManager(tmp_path / "history.db")
    store = QueueStore(tmp_path / "queue.db")
    return SenderController(state, settings, history, store), state


def test_missing_credentials(tmp_path):
    controller, _ = _controller(tmp_path)
    assert controller.queue_readiness is StartReadiness.MISSING_CREDENTIALS


def test_paused_queue_is_ready(tmp_path):
    controller, state = _controller(tmp_path)
    state.session.sessdata, state.session.bili_jct = "x", "y"
    state.workspace.queue_state.add_task(_task(TaskStatus.PAUSED))

    assert controller.queue_readiness is StartReadiness.READY


def test_no_runnable_tasks(tmp_path):
    controller, state = _controller(tmp_path)
    state.session.sessdata, state.session.bili_jct = "x", "y"

    assert controller.queue_readiness is StartReadiness.NO_RUNNABLE_TASKS
