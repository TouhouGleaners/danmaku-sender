"""QueueMonitorWorker 会话寿命：发送后监视的截止不能被轮询间隔吞掉"""

import threading
import time

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.controller.monitor.workers import QueueMonitorWorker
from danmaku_sender.repo.history_manager import HistoryManager


def _make_worker(tmp_path, **kwargs) -> QueueMonitorWorker:
    """空账本：`_run_round` 无目标即返回，测试只量等待行为，不碰网络。"""
    return QueueMonitorWorker(
        auth_config=ApiAuthConfig(sessdata="s", bili_jct="j", use_system_proxy=False),
        history_manager=HistoryManager(tmp_path / "history.db"),
        stop_event=threading.Event(),
        prevent_sleep=False,
        **kwargs,
    )


class TestPostSendWatch:
    """发送结束后再监视 post_send_watch_seconds 自动停"""

    def test_watch_deadline_beats_poll_interval(self, tmp_path):
        """发送后监视的截止落在等待期里，不该多睡一个轮询周期再跑一轮。

        回归：原本 `stop_event.wait(poll_interval)` 不看截止时间，
        post_send_watch_seconds < poll_interval 时会拖满一整个轮询周期。
        """
        send_done = threading.Event()
        send_done.set()  # 发送已结束，发送后监视立刻起算
        worker = _make_worker(
            tmp_path, poll_interval=3.0, send_done=send_done, post_send_watch_seconds=0.3
        )

        started = time.monotonic()
        worker.run()
        elapsed = time.monotonic() - started

        assert elapsed < 1.5, f"发送后监视只该跑 0.3 秒，实际 {elapsed:.1f}s（被 3s 轮询拖了）"

    def test_no_post_send_watch_without_send_done(self, tmp_path):
        """独立监视没有发送后监视，跑到手动停为止"""
        worker = _make_worker(tmp_path, poll_interval=1.0, send_done=None, post_send_watch_seconds=0.0)
        threading.Timer(0.4, worker.stop_event.set).start()

        started = time.monotonic()
        worker.run()
        elapsed = time.monotonic() - started

        assert elapsed >= 0.35, f"不该自己退出，实际只跑了 {elapsed:.2f}s"

    def test_post_send_watch_waits_for_send_done(self, tmp_path):
        """给了 send_done 但还没 set：不该起算发送后监视——暂停不是结束"""
        send_done = threading.Event()
        worker = _make_worker(
            tmp_path, poll_interval=1.0, send_done=send_done, post_send_watch_seconds=0.0
        )
        threading.Timer(1.2, send_done.set).start()
        threading.Timer(0.5, worker.stop_event.set).start()

        started = time.monotonic()
        worker.run()
        elapsed = time.monotonic() - started

        # post_send_watch_seconds=0：若发送后监视提前起算，首轮就到期退出
        assert 0.3 <= elapsed < 1.0, f"该被手动停在 0.5s，实际 {elapsed:.2f}s"

    def test_deadline_armed_when_send_ends_during_round(self, tmp_path):
        """发送正好在一轮核销期间结束：本轮返回后就该起算，不等满轮询间隔"""
        send_done = threading.Event()
        worker = _make_worker(
            tmp_path, poll_interval=3.0, send_done=send_done, post_send_watch_seconds=0.5
        )

        def slow_round(_deadline=None):
            time.sleep(0.3)
            send_done.set()  # 本轮执行期间发送结束

        worker._run_round = slow_round  # type: ignore[method-assign]

        started = time.monotonic()
        worker.run()
        elapsed = time.monotonic() - started

        assert elapsed < 1.5, f"本轮结束后就该起算，实际 {elapsed:.1f}s（被 3s 轮询拖了）"
