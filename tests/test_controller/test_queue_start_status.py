"""SenderController.start_status 的判定口径。

凭证缺失与队列无可执行任务是两种独立的不可启动原因；后者须包含 PAUSED。
"""

from danmaku_sender.controller.sender import QueueStartStatus, SenderController
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.queue import QueueTask, TaskStatus


def _task(status: TaskStatus) -> QueueTask:
    return QueueTask(
        target=VideoTarget(bvid="BV1", cid=1, title="T"),
        danmakus=[],
        config_snapshot=AppState().sender_config.to_task_config(),
        status=status,
    )


def _controller(tmp_path) -> tuple[SenderController, AppState]:
    state = AppState()
    return SenderController(state, HistoryManager(tmp_path / "history.db")), state


def test_missing_credentials(tmp_path):
    controller, _ = _controller(tmp_path)
    assert controller.start_status is QueueStartStatus.NO_CREDENTIALS


def test_paused_queue_is_startable(tmp_path):
    controller, state = _controller(tmp_path)
    state.sessdata, state.bili_jct = "x", "y"
    state.queue_state.add_task(_task(TaskStatus.PAUSED))

    assert controller.start_status is QueueStartStatus.READY


def test_empty_queue_is_not_ready(tmp_path):
    controller, state = _controller(tmp_path)
    state.sessdata, state.bili_jct = "x", "y"

    assert controller.start_status is QueueStartStatus.NO_RUNNABLE_TASKS
