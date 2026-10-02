"""监视器 Worker → Controller 的 cid 传递。

Qt 信号参数里的 int 是 C++ 的 32 位有符号，B 站新视频的 cid 会溢出绕回；
cid 必须以 object 传递。断言落在控制器的对外信号上，覆盖
「Worker 信号 → 控制器槽 → 控制器信号」整条中继——截断最先发生在 Worker 侧。
"""

import threading

import pytest

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.controller.monitor.controller import MonitorController
from danmaku_sender.controller.monitor.workers import QueueMonitorWorker
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.runtime.state.app_state import AppState

# 落在符号位上（低 32 位 >= 2^31）就会绕成负数，两种跨度都要覆盖：
# 真实 cid（> 2^32，跨周期取低位）与 2^31~2^32 之间的边界值
WRAPPING_CIDS = [
    41382447884,
    3000000000,
]


def _wired_pair(tmp_path):
    """按 start_queue_monitor 的接线把 Worker 与 Controller 接起来。"""
    controller = MonitorController(AppState(), HistoryManager(tmp_path / "history.db"))
    worker = QueueMonitorWorker(
        ApiAuthConfig(sessdata="x", bili_jct="y", use_system_proxy=False),
        controller.history_manager,
        threading.Event(),
    )
    worker.targetStatsUpdated.connect(controller._on_target_stats)
    worker.targetVerifyFailed.connect(controller._on_target_verify_failed)
    return controller, worker


@pytest.mark.parametrize("cid", WRAPPING_CIDS)
def test_big_cid_survives_stats_relay(tmp_path, cid):
    controller, worker = _wired_pair(tmp_path)
    received: list[tuple[str, int]] = []
    controller.targetStatsUpdated.connect(lambda b, c, _s: received.append((b, c)))

    worker.targetStatsUpdated.emit("BV1", cid, {"total": 1})

    assert received == [("BV1", cid)]


@pytest.mark.parametrize("cid", WRAPPING_CIDS)
def test_big_cid_survives_verify_failed_relay(tmp_path, cid):
    controller, worker = _wired_pair(tmp_path)
    received: list[tuple[str, int]] = []
    controller.targetVerifyFailed.connect(lambda b, c: received.append((b, c)))

    worker.targetVerifyFailed.emit("BV1", cid)

    assert received == [("BV1", cid)]
