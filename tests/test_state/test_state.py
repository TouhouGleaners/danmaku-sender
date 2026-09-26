"""状态与配置模型单元测试 — GlobalConfig, SenderConfig, SendPolicy, MonitorConfig, ValidationConfig, QueueState"""
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from danmaku_sender.config import (
    GlobalConfig,
    MonitorConfig,
    SenderConfig,
    SendPolicy,
    ValidationConfig,
)
from danmaku_sender.runtime.state.queue_state import QueueState
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import QueueTask, TaskStatus


class TestGlobalConfig:
    """GlobalConfig 全局系统设置"""

    def test_default_values(self):
        cfg = GlobalConfig()
        assert cfg.prevent_sleep is True
        assert cfg.use_system_proxy is True

    def test_custom_values(self):
        cfg = GlobalConfig(prevent_sleep=False, use_system_proxy=False)
        assert cfg.prevent_sleep is False
        assert cfg.use_system_proxy is False


class TestSenderConfig:
    """SenderConfig Pydantic 模型"""

    def test_default_values(self):
        cfg = SenderConfig()
        assert cfg.min_delay == 8.0
        assert cfg.max_delay == 8.5
        assert cfg.burst_size == 3
        assert cfg.rest_min == 40.0
        assert cfg.rest_max == 45.0

    def test_valid_custom_values(self):
        cfg = SenderConfig(min_delay=5.0, max_delay=10.0)
        assert cfg.min_delay == 5.0
        assert cfg.max_delay == 10.0

    def test_to_task_config_is_snapshot(self):
        """入队后修改 SenderConfig 不得影响已派生的工单参数。

        工单参数在入队时定死；改全局发送节奏只对新建任务生效。
        """
        cfg = SenderConfig(min_delay=8.0, max_delay=8.5)
        snapshot = cfg.to_task_config()

        cfg.max_delay = 10.5
        cfg.min_delay = 10.0

        assert (cfg.min_delay, cfg.max_delay) == (10.0, 10.5), "全局设置应已更新"
        assert (snapshot.min_delay, snapshot.max_delay) == (8.0, 8.5), "工单参数不受影响"

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
        config_snapshot=SenderConfig().to_task_config(),
        status=status,
    )


class TestSendPolicy:
    """SendPolicy 队列发送策略"""

    def test_default_values(self):
        policy = SendPolicy()
        assert policy.delay_between_tasks == 30.0
        assert policy.stop_after_count == 0
        assert policy.stop_after_time == 0
        assert policy.skip_sent is True


class TestQueueState:
    """QueueState 队列操作与信号"""

    def test_add_and_lookup(self):
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        assert not qs.is_empty
        assert qs.pending_count == 1
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.task_id == t.task_id

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
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status == TaskStatus.RUNNING
        assert view.error_msg == "err"
        assert events == [(t.task_id, TaskStatus.RUNNING)]

    def test_current_index_signal(self):
        qs = QueueState()
        fired = []
        qs.currentTaskChanged.connect(lambda i: fired.append(i))
        qs.current_index = 2
        assert qs.current_index == 2
        assert fired == [2]

    def test_view_is_live_facade(self):
        """TaskView 读到的是当前值，落账后无需换对象"""
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status == TaskStatus.PENDING
        qs.update_task_status(t.task_id, TaskStatus.RUNNING)
        assert view.status == TaskStatus.RUNNING

    def test_snapshot_freezes_status(self):
        """快照采样后，主线程落账不再影响已发出的快照"""
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        snap = qs.snapshots({TaskStatus.PENDING})[0]
        assert snap.status == TaskStatus.PENDING
        qs.update_task_status(t.task_id, TaskStatus.RUNNING)
        assert snap.status == TaskStatus.PENDING
        assert qs.snapshots({TaskStatus.RUNNING})[0].status == TaskStatus.RUNNING

    def test_snapshot_excludes_other_statuses(self):
        qs = QueueState()
        qs.add_task(make_task(1, TaskStatus.PENDING))
        qs.add_task(make_task(2, TaskStatus.COMPLETED))
        assert len(qs.snapshots({TaskStatus.PENDING})) == 1
        assert len(qs.snapshots({TaskStatus.PENDING, TaskStatus.COMPLETED})) == 2

    def test_assign_danmakus_replaces_spec(self):
        qs = QueueState()
        t = make_task(1, TaskStatus.UNCONFIGURED)
        qs.add_task(t)
        dms = [Danmaku(msg="hi", progress=0)]
        qs.assign_danmakus(t.task_id, dms, xml_path="a.xml")
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.total == 1
        assert view.xml_path == "a.xml"
        assert view.status == TaskStatus.PENDING  # UNCONFIGURED → PENDING

    def test_apply_edit_refused_when_running(self):
        """发送中拒绝结构编辑（UI 闸门之外的结构保证）"""
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        qs.update_task_status(t.task_id, TaskStatus.RUNNING)
        draft = make_task(99)
        draft.p_title = "hacked"
        assert qs.apply_edit(t.task_id, draft) is False
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.p_title != "hacked"

    def test_apply_edit_rebuilds_spec(self):
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        draft = view.to_draft()
        draft.p_title = "新标题"
        draft.danmakus = [Danmaku(msg="x", progress=1000)]
        draft.total = 1
        assert qs.apply_edit(t.task_id, draft) is True
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.p_title == "新标题"
        assert view.total == 1
        assert view.task_id == t.task_id  # id 不被沙盒覆盖

    def test_reorder_tasks_by_ids(self):
        qs = QueueState()
        t1, t2, t3 = make_task(1), make_task(2), make_task(3)
        for t in (t1, t2, t3):
            qs.add_task(t)
        qs.reorder_tasks([t3.task_id, t1.task_id, t2.task_id])
        assert [v.target.cid for v in qs.tasks] == [3, 1, 2]

    def test_reorder_tasks_rejects_mismatch(self):
        qs = QueueState()
        t1 = make_task(1)
        qs.add_task(t1)
        qs.reorder_tasks(["nope"])
        assert [v.target.cid for v in qs.tasks] == [1]

    def test_view_config_is_frozen(self):
        """工单参数是冻结类型：经 TaskView.config 改写在类型层就不可能"""
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.config.min_delay == 8.0
        with pytest.raises(FrozenInstanceError):
            view.config.min_delay = 99.0  # type: ignore[misc]

    def test_spec_danmakus_are_frozen(self):
        """Danmaku 不可变：写穿 TaskSpec 在类型层就不可能"""
        import dataclasses

        qs = QueueState()
        dm = Danmaku(msg="hi", progress=0)
        t = make_task(1)
        t.danmakus = [dm]
        t.total = 1
        qs.add_task(t)

        snap = qs.snapshots({TaskStatus.PENDING})[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.spec.danmakus[0].msg = "hacked"  # type: ignore[misc]
