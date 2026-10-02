"""监视器信号的 cid 传递。

Qt 信号参数里的 int 是 C++ 的 32 位有符号，B 站新视频的 cid 会溢出绕回；
cid 必须以 object 传递，此处钉住「过信号后仍是原值」。
"""

import pytest

from danmaku_sender.controller.monitor.controller import MonitorController
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState

# 落在符号位上（低 32 位 >= 2^31）就会绕成负数，两种跨度都要覆盖：
# 刚过 2^32 的真实 cid，以及 2^31~2^32 之间的边界值
WRAPPING_CIDS = [
    41382447884,  # 真实 cid，> 2^32，低 32 位 2727742220 落在符号位
    3000000000,  # 2^31 ~ 2^32 之间
]


@pytest.mark.parametrize("cid", WRAPPING_CIDS)
def test_big_cid_survives_stats_signal(tmp_path, cid):
    controller = MonitorController(AppState(), HistoryManager(tmp_path / "history.db"))
    received: list[tuple[str, int]] = []
    controller.targetStatsUpdated.connect(lambda b, c, _s: received.append((b, c)))

    controller.targetStatsUpdated.emit("BV1", cid, {"total": 1})

    assert received == [("BV1", cid)]


@pytest.mark.parametrize("cid", WRAPPING_CIDS)
def test_big_cid_survives_verify_failed_signal(tmp_path, cid):
    controller = MonitorController(AppState(), HistoryManager(tmp_path / "history.db"))
    received: list[tuple[str, int]] = []
    controller.targetVerifyFailed.connect(lambda b, c: received.append((b, c)))

    controller.targetVerifyFailed.emit("BV1", cid)

    assert received == [("BV1", cid)]
