"""监视器信号的 cid 传递。

Qt 信号参数里的 int 是 C++ 的 32 位有符号，B 站新视频的 cid 会溢出绕回；
cid 必须以 object 传递，此处钉住「过信号后仍是原值」。
"""

from danmaku_sender.controller.monitor.controller import MonitorController
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState

# 2^31 之上、2^32 之内会绕成负数的 cid
BIG_CID = 41382447884


def test_big_cid_survives_stats_signal(tmp_path):
    controller = MonitorController(AppState(), HistoryManager(tmp_path / "history.db"))
    received: list[tuple[str, int]] = []
    controller.targetStatsUpdated.connect(lambda b, c, _s: received.append((b, c)))

    controller.targetStatsUpdated.emit("BV1", BIG_CID, {"total": 1})

    assert received == [("BV1", BIG_CID)]


def test_big_cid_survives_verify_failed_signal(tmp_path):
    controller = MonitorController(AppState(), HistoryManager(tmp_path / "history.db"))
    received: list[tuple[str, int]] = []
    controller.targetVerifyFailed.connect(lambda b, c: received.append((b, c)))

    controller.targetVerifyFailed.emit("BV1", BIG_CID)

    assert received == [("BV1", BIG_CID)]
