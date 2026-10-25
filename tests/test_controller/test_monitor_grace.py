"""发送自然结束后的收尾宽限。

宽限是单次倒数，新一轮发送启动即作废；若残留倒数未撤，到期会在新一队列
仍在发送时停掉监视。
"""

from danmaku_sender.config import Settings
from danmaku_sender.controller.monitor.controller import MonitorController
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import SendMode


def test_new_send_cancels_pending_grace(tmp_path, qapp):
    controller = MonitorController(AppState(), Settings(), HistoryManager(tmp_path / "history.db"))
    controller.settings.send_policy.mode = SendMode.SEND_AND_MONITOR
    controller.start_grace_period()
    assert controller._grace_timer.isActive()

    # 队列为空 → 不启动监视，仍须撤销残留倒数
    controller.on_send_started()

    assert not controller._grace_timer.isActive()
