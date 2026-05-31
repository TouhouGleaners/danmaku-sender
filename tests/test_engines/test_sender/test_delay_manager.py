"""DelayManager 单元测试"""
from threading import Event
from danmaku_sender.core.engines.sender.delay_manager import DelayManager


class TestCalcEta:
    """calc_eta 静态方法 — 纯算术，最有价值的测试目标"""

    def test_zero_progress(self):
        eta = DelayManager.calc_eta(attempted=0, total=10, burst_size=0, avg_normal=8.0, avg_rest=40.0)
        # remaining_waits = 10 - max(1,0) = 9, burst_size<=1 → burst_size=1 → 9 * 8 = 72
        assert eta == 72.0

    def test_first_attempt(self):
        eta = DelayManager.calc_eta(attempted=1, total=10, burst_size=0, avg_normal=8.0, avg_rest=40.0)
        assert eta == 72.0  # same as attempted=0

    def test_half_done(self):
        eta = DelayManager.calc_eta(attempted=5, total=10, burst_size=0, avg_normal=8.0, avg_rest=40.0)
        # remaining = 10 - 5 = 5 → 5 * 8 = 40
        assert eta == 40.0

    def test_all_done(self):
        eta = DelayManager.calc_eta(attempted=10, total=10, burst_size=0, avg_normal=8.0, avg_rest=40.0)
        assert eta == 0.0

    def test_over_attempted(self):
        eta = DelayManager.calc_eta(attempted=15, total=10, burst_size=0, avg_normal=8.0, avg_rest=40.0)
        assert eta == 0.0

    def test_single_item(self):
        eta = DelayManager.calc_eta(attempted=0, total=1, burst_size=0, avg_normal=8.0, avg_rest=40.0)
        # remaining = 1 - max(1,0) = 0
        assert eta == 0.0

    def test_burst_mode_simple(self):
        """burst_size=2, total=4, 每发2条休息一次"""
        eta = DelayManager.calc_eta(attempted=0, total=4, burst_size=2, avg_normal=8.0, avg_rest=40.0)
        # waits in [1, 3]: 1, 2, 3
        # rest: 2 (index % 2 == 0) → rest_count=1
        # normal: 3-1 = 2
        # eta = 2*8 + 1*40 = 56
        assert eta == 56.0

    def test_burst_size_1_behaves_as_normal(self):
        """burst_size=1 时退化为纯普通延时"""
        eta = DelayManager.calc_eta(attempted=0, total=5, burst_size=1, avg_normal=8.0, avg_rest=40.0)
        assert eta == 4 * 8.0  # 4 waits * 8s

    def test_burst_size_zero_behaves_as_normal(self):
        """burst_size=0 时退化为纯普通延时"""
        eta = DelayManager.calc_eta(attempted=0, total=5, burst_size=0, avg_normal=8.0, avg_rest=40.0)
        assert eta == 4 * 8.0

    def test_negative_burst_size_behaves_as_normal(self):
        eta = DelayManager.calc_eta(attempted=0, total=5, burst_size=-1, avg_normal=8.0, avg_rest=40.0)
        assert eta == 4 * 8.0

    def test_large_burst_no_rests(self):
        """burst_size > total - 1 时不会触发任何休息"""
        eta = DelayManager.calc_eta(attempted=0, total=5, burst_size=100, avg_normal=8.0, avg_rest=40.0)
        assert eta == 4 * 8.0


class TestWaitAndCheckStop:
    """wait_and_check_stop 的行为"""

    def test_immediate_stop(self):
        dm = DelayManager(normal_min=1.0, normal_max=1.0)
        stop = Event()
        stop.set()
        assert dm.wait_and_check_stop(stop) is True

    def test_normal_delay_no_stop(self):
        dm = DelayManager(normal_min=0.01, normal_max=0.01)
        stop = Event()
        result = dm.wait_and_check_stop(stop)
        assert result is False
        assert dm._current_count == 1

    def test_burst_rest_triggered(self):
        dm = DelayManager(normal_min=0.01, normal_max=0.01, burst_size=2, rest_min=0.01, rest_max=0.01)
        stop = Event()
        dm.wait_and_check_stop(stop)  # count=1, normal
        dm.wait_and_check_stop(stop)  # count=2, burst rest
        assert dm._current_count == 2
