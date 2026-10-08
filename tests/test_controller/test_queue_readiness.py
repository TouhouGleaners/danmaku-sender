"""SenderController.queue_readiness 的判定口径。

凭证缺失与队列无可执行任务是两种独立的未满足条件；PAUSED 属于可启动范围。
"""

from danmaku_sender.controller.sender import QueueReadiness, SenderController
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.queue import TaskDraft, TaskStatus


def _task(state: AppState, status: TaskStatus) -> TaskDraft:
    return TaskDraft(
        target=VideoTarget(bvid="BV1", cid=1),
        danmakus=[],
        config=state.sender_config.to_task_config(),
        status=status,
    )


def _controller(tmp_path) -> tuple[SenderController, AppState]:
    state = AppState()
    return SenderController(state, HistoryManager(tmp_path / "history.db")), state


def test_missing_credentials(tmp_path):
    controller, _ = _controller(tmp_path)
    assert controller.queue_readiness is QueueReadiness.MISSING_CREDENTIALS


def test_paused_queue_is_ready(tmp_path):
    controller, state = _controller(tmp_path)
    state.sessdata, state.bili_jct = "x", "y"
    state.queue_state.add_task(_task(state, TaskStatus.PAUSED))

    assert controller.queue_readiness is QueueReadiness.READY


def test_no_runnable_tasks(tmp_path):
    controller, state = _controller(tmp_path)
    state.sessdata, state.bili_jct = "x", "y"

    assert controller.queue_readiness is QueueReadiness.NO_RUNNABLE_TASKS
