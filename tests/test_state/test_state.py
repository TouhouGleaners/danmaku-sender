"""状态与配置模型单元测试 — SenderConfig, MonitorConfig, ValidationConfig, QueueState"""
import pytest
from pydantic import ValidationError

from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.queue import QueueTask, TaskStatus
from danmaku_sender.config import SenderConfig, MonitorConfig, ValidationConfig
from danmaku_sender.runtime.state.queue_state import QueueState


class TestSenderConfig:
    """SenderConfig Pydantic 模型"""

    def test_default_values(self):
        cfg = SenderConfig()
        assert cfg.min_delay == 8.0
        assert cfg.max_delay == 8.5
        assert cfg.burst_size == 3
        assert cfg.rest_min == 40.0
        assert cfg.rest_max == 45.0
        assert cfg.stop_after_count == 0
        assert cfg.stop_after_time == 0
        assert cfg.prevent_sleep is True
        assert cfg.use_system_proxy is True
        assert cfg.skip_sent is True

    def test_valid_custom_values(self):
        cfg = SenderConfig(min_delay=5.0, max_delay=10.0)
        assert cfg.min_delay == 5.0
        assert cfg.max_delay == 10.0

    def test_min_delay_too_small(self):
        with pytest.raises(ValidationError):
            SenderConfig(min_delay=0.0)

    def test_max_delay_too_small(self):
        with pytest.raises(ValidationError):
            SenderConfig(max_delay=0.0)

    def test_burst_size_negative(self):
        with pytest.raises(ValidationError):
            SenderConfig(burst_size=-1)

    def test_min_greater_than_max_raises(self):
        with pytest.raises(ValidationError, match="最小延迟不能大于最大延迟"):
            SenderConfig(min_delay=10.0, max_delay=5.0)

    def test_rest_min_greater_than_rest_max_raises(self):
        with pytest.raises(ValidationError, match="爆发休息的最小值不能大于最大值"):
            SenderConfig(burst_enabled=True, burst_size=3, rest_min=50.0, rest_max=30.0)

    def test_rest_range_ignored_when_burst_disabled(self):
        """burst_enabled=False 时不校验 rest_min/rest_max"""
        cfg = SenderConfig(burst_size=3, rest_min=50.0, rest_max=30.0)
        assert cfg.rest_min == 50.0

    def test_validate_assignment(self):
        """赋值时也应触发校验"""
        cfg = SenderConfig()
        with pytest.raises(ValidationError):
            cfg.min_delay = 999.0  # > max_delay=8.5


class TestMonitorConfig:
    def test_default_values(self):
        cfg = MonitorConfig()
        assert cfg.refresh_interval == 60
        assert cfg.prevent_sleep is True
        assert cfg.use_system_proxy is True

    def test_refresh_interval_too_small(self):
        with pytest.raises(ValidationError):
            MonitorConfig(refresh_interval=5)

    def test_refresh_interval_minimum(self):
        cfg = MonitorConfig(refresh_interval=10)
        assert cfg.refresh_interval == 10


class TestValidationConfig:
    def test_default_values(self):
        cfg = ValidationConfig()
        assert cfg.enabled is True
        assert cfg.blocked_keywords == []

    def test_custom_keywords(self):
        cfg = ValidationConfig(blocked_keywords=["广告", "加群"])
        assert cfg.blocked_keywords == ["广告", "加群"]

    def test_disabled(self):
        cfg = ValidationConfig(enabled=False)
        assert cfg.enabled is False


def make_task(cid: int = 1, status: TaskStatus = TaskStatus.PENDING) -> QueueTask:
    return QueueTask(
        target=VideoTarget(bvid=f"BV{cid:03d}", cid=cid, title=f"T{cid}"),
        danmakus=[],
        config_snapshot=SenderConfig(),
        status=status,
    )


class TestQueueState:
    """QueueState 队列操作与信号"""

    def test_add_and_lookup(self):
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        assert not qs.is_empty
        assert qs.pending_count == 1
        assert qs.get_task_by_id(t.task_id) is t

    def test_remove_only_pending_or_unconfigured(self):
        qs = QueueState()
        running = make_task(1, TaskStatus.RUNNING)
        pending = make_task(2)
        qs.add_task(running)
        qs.add_task(pending)
        assert qs.remove_task(running.task_id) is False
        assert qs.remove_task(pending.task_id) is True
        assert qs.get_task_by_id(pending.task_id) is None

    def test_move_task(self):
        qs = QueueState()
        t1, t2, t3 = make_task(1), make_task(2), make_task(3)
        for t in (t1, t2, t3):
            qs.add_task(t)
        assert qs.move_task(t3.task_id, -1) is True
        assert [t.target.cid for t in qs.tasks] == [1, 3, 2]
        assert qs.move_task(t1.task_id, -1) is False  # 已在顶端

    def test_move_non_movable_task(self):
        qs = QueueState()
        done = make_task(1, TaskStatus.COMPLETED)
        other = make_task(2)
        qs.add_task(done)
        qs.add_task(other)
        assert qs.move_task(done.task_id, 1) is False  # 已完成任务不可移动

    def test_clear_completed_keeps_pending_and_paused(self):
        qs = QueueState()
        for t in (
            make_task(1, TaskStatus.COMPLETED),
            make_task(2, TaskStatus.FAILED),
            make_task(3, TaskStatus.PENDING),
            make_task(4, TaskStatus.PAUSED),
        ):
            qs.add_task(t)
        qs.clear_completed()
        assert [t.status for t in qs.tasks] == [TaskStatus.PENDING, TaskStatus.PAUSED]

    def test_update_task_status(self):
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        events = []
        qs.taskStatusChanged.connect(lambda tid, s: events.append((tid, s)))
        qs.update_task_status(t.task_id, TaskStatus.RUNNING, "err")
        assert t.status == TaskStatus.RUNNING
        assert t.error_msg == "err"
        assert events == [(t.task_id, TaskStatus.RUNNING.value)]

    def test_current_index_signal(self):
        qs = QueueState()
        fired = []
        qs.currentTaskChanged.connect(lambda i: fired.append(i))
        qs.current_index = 2
        assert qs.current_index == 2
        assert fired == [2]
