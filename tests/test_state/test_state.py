"""状态与配置模型单元测试 — GlobalConfig, SenderConfig, SendPolicy, MonitorConfig, ValidationConfig, QueueState"""
from dataclasses import FrozenInstanceError
from pathlib import Path

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
from danmaku_sender.types.models.common import RelativePosition, VideoTarget
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


def make_task(
    cid: int = 1,
    status: TaskStatus = TaskStatus.PENDING,
    danmaku_count: int = 1,
) -> QueueTask:
    """构造一条任务。默认带弹幕，是配置齐备的正常任务。

    配置残缺的任务会被 QueueState 纠状态，所以要构造「缺弹幕」的用例
    必须显式传 ``danmaku_count=0``，别指望草稿自带的 status 能蒙混过关。
    """
    return QueueTask(
        target=VideoTarget(bvid=f"BV{cid:03d}", cid=cid, title=f"T{cid}"),
        danmakus=[Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count)],
        config_snapshot=SenderConfig().to_task_config(),
        status=status,
    )


def make_incomplete_task(
    danmaku_count: int = 0,
    status: TaskStatus = TaskStatus.UNCONFIGURED,
) -> QueueTask:
    """拖入 XML 建的任务：没定视频目标，弹幕可配。"""
    return QueueTask(
        target=VideoTarget.unset(),
        danmakus=[Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count)],
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
        assert policy.allow_duplicates is False


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

    def test_remove_refuses_only_running(self):
        """删除不看可编辑白名单，只挡发送中（其余状态都能删）"""
        qs = QueueState()
        running = make_task(1, TaskStatus.RUNNING)
        qs.add_task(running)
        qs.remove_task(running.task_id)
        assert qs.get_task_by_id(running.task_id) is not None

        for status in (
            TaskStatus.PENDING,
            TaskStatus.UNCONFIGURED,
            TaskStatus.PAUSED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.SKIPPED,
        ):
            task = make_task(2, status)
            qs.add_task(task)
            qs.remove_task(task.task_id)
            assert qs.get_task_by_id(task.task_id) is None, f"{status} 应可删除"

    def test_move_task(self):
        """上下移动：相对参考项换位，越界时顺序不变"""
        qs = QueueState()
        t1, t2, t3 = make_task(1), make_task(2), make_task(3)
        for t in (t1, t2, t3):
            qs.add_task(t)
        qs.move_task(t3.task_id, RelativePosition.ABOVE)
        assert [t.target.cid for t in qs.tasks] == [1, 3, 2]
        qs.move_task(t1.task_id, RelativePosition.ABOVE)  # 已在顶端，顺序不变
        assert [t.target.cid for t in qs.tasks] == [1, 3, 2]

    def test_move_non_movable_task(self):
        qs = QueueState()
        done = make_task(1, TaskStatus.COMPLETED)
        other = make_task(2)
        qs.add_task(done)
        qs.add_task(other)
        qs.move_task(done.task_id, RelativePosition.BELOW)  # 已完成任务不可移动
        assert [t.target.cid for t in qs.tasks] == [1, 2]

    def test_relative_position_rejects_unknown(self):
        """非法的相对位置当场拒绝，不得静默按某一支处理"""
        qs = QueueState()
        t1, t2 = make_task(1), make_task(2)
        qs.add_task(t1)
        qs.add_task(t2)
        with pytest.raises(ValueError):
            qs.move_task(t1.task_id, "上方")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            qs.insert_task(make_task(3), t1.task_id, "上方")  # type: ignore[arg-type]
        assert [t.target.cid for t in qs.tasks] == [1, 2], "被拒的调用不得改动队列"

    def test_reset_queue_semantics(self):
        """重置：移除已完成、失败转待发；跳过/未配置保留，其余不动"""
        qs = QueueState()
        for t in (
            make_task(1, TaskStatus.COMPLETED),
            make_task(2, TaskStatus.FAILED),
            make_task(3, TaskStatus.SKIPPED, danmaku_count=0),
            make_task(4, TaskStatus.UNCONFIGURED, danmaku_count=0),
            make_task(5, TaskStatus.PENDING),
            make_task(6, TaskStatus.PAUSED),
        ):
            qs.add_task(t)
        qs.reset_queue()
        assert [t.status for t in qs.tasks] == [
            TaskStatus.PENDING,
            TaskStatus.SKIPPED,
            TaskStatus.UNCONFIGURED,
            TaskStatus.PENDING,
            TaskStatus.PAUSED,
        ]
        assert [t.target.cid for t in qs.tasks] == [2, 3, 4, 5, 6]

    def test_reset_queue_clears_failed_runtime(self):
        """失败转待发要清零进度与错误信息，不能把旧账带进新一轮"""
        qs = QueueState()
        t = make_task(1, TaskStatus.FAILED)
        qs.add_task(t)
        qs.update_task_progress(t.task_id, 5, 10)
        qs.update_task_status(t.task_id, TaskStatus.FAILED, "网络错误")
        qs.reset_queue()
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status is TaskStatus.PENDING
        assert view.attempted == 0
        assert view.error_msg == ""

    def test_reset_queue_noop_when_nothing_to_do(self):
        """没有已完成/失败任务时不发信号，也不动其它状态"""
        qs = QueueState()
        qs.add_task(make_task(1, TaskStatus.PENDING))
        qs.add_task(make_task(2, TaskStatus.SKIPPED, danmaku_count=0))
        events: list[object] = []
        qs.tasksChanged.connect(lambda: events.append("tasks"))
        qs.taskStatusChanged.connect(lambda tid, s: events.append("status"))
        qs.reset_queue()
        assert events == []
        assert [t.status for t in qs.tasks] == [TaskStatus.PENDING, TaskStatus.SKIPPED]

    def test_reset_queue_emits_status_then_structure(self):
        """转待发发 taskStatusChanged，队列结构变更发 tasksChanged"""
        qs = QueueState()
        qs.add_task(make_task(1, TaskStatus.FAILED))
        qs.add_task(make_task(2, TaskStatus.COMPLETED))
        events: list[str] = []
        qs.taskStatusChanged.connect(lambda tid, s: events.append("status"))
        qs.tasksChanged.connect(lambda: events.append("tasks"))
        qs.reset_queue()
        assert events == ["status", "tasks"]

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
        t = make_task(1, TaskStatus.UNCONFIGURED, danmaku_count=0)
        qs.add_task(t)
        dms = [Danmaku(msg="hi", progress=0)]
        qs.assign_danmakus(t.task_id, dms, xml_path=Path("a.xml"))
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.total == 1
        assert view.xml_path == Path("a.xml")
        assert view.status == TaskStatus.PENDING  # UNCONFIGURED → PENDING

    def test_apply_edit_refused_when_running(self):
        """发送中拒绝结构编辑（UI 闸门之外的结构保证）"""
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        qs.update_task_status(t.task_id, TaskStatus.RUNNING)
        draft = make_task(99)
        draft.p_title = "hacked"
        qs.apply_edit(t.task_id, draft)
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
        qs.apply_edit(t.task_id, draft)
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

    def test_queue_state_has_no_lock(self):
        """QueueState 只允许主线程访问：跨线程读的 RLock 已删除。

        Worker 要数据用 snapshots() 取不可变拷贝，监视器的核销范围来自数据库。
        若有人把「Worker 自己采样」加回来，这个锁也会跟着回来。
        """
        qs = QueueState()
        assert not hasattr(qs, "_lock")

    def test_skipped_becomes_pending_on_config(self):
        """因缺配置被跳过的任务，补完配置后回到待发"""
        qs = QueueState()
        t = make_task(1, TaskStatus.SKIPPED, danmaku_count=0)
        qs.add_task(t)
        qs.assign_danmakus(t.task_id, [Danmaku(msg="hi", progress=0)], xml_path=Path("a.xml"))
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status is TaskStatus.PENDING

    def test_assign_danmakus_keeps_unconfigured_without_target(self):
        """只补弹幕不补目标，仍是未配置——齐备才转待发"""
        qs = QueueState()
        t = make_incomplete_task()
        qs.add_task(t)
        qs.assign_danmakus(t.task_id, [Danmaku(msg="hi", progress=0)], xml_path=Path("a.xml"))
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.total == 1
        assert view.status is TaskStatus.UNCONFIGURED

    def test_assign_danmakus_keeps_skipped_without_target(self):
        """跳过原因与状态都不动：配置还没齐"""
        qs = QueueState()
        t = make_incomplete_task(status=TaskStatus.SKIPPED)
        qs.add_task(t)
        qs.update_task_status(t.task_id, TaskStatus.SKIPPED, "未指定视频目标")
        qs.assign_danmakus(t.task_id, [Danmaku(msg="hi", progress=0)], xml_path=Path("a.xml"))
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status is TaskStatus.SKIPPED
        assert view.error_msg == "未指定视频目标"

    def test_apply_edit_completes_drop_created_task(self):
        """拖入建的任务在详情里补上视频目标后转待发，跳过原因清空"""
        qs = QueueState()
        t = make_incomplete_task(danmaku_count=1)
        qs.add_task(t)
        qs.update_task_status(t.task_id, TaskStatus.UNCONFIGURED, "未指定视频目标")
        draft = qs.get_task_by_id(t.task_id).to_draft()
        draft.target = VideoTarget(bvid="BV1xx411c7mD", cid=1001, title="我的视频")
        qs.apply_edit(t.task_id, draft)
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status is TaskStatus.PENDING
        assert view.error_msg == ""

    def test_apply_edit_demotes_when_danmakus_stripped(self):
        """配置被拆掉的待发任务降回未配置"""
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        qs.assign_danmakus(t.task_id, [Danmaku(msg="hi", progress=0)], xml_path=Path("a.xml"))
        draft = qs.get_task_by_id(t.task_id).to_draft()
        draft.danmakus = []
        draft.total = 0
        qs.apply_edit(t.task_id, draft)
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status is TaskStatus.UNCONFIGURED

    def test_apply_edit_demotes_when_target_stripped(self):
        qs = QueueState()
        t = make_task(1)
        qs.add_task(t)
        qs.assign_danmakus(t.task_id, [Danmaku(msg="hi", progress=0)], xml_path=Path("a.xml"))
        draft = qs.get_task_by_id(t.task_id).to_draft()
        draft.target = VideoTarget.unset()
        qs.apply_edit(t.task_id, draft)
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status is TaskStatus.UNCONFIGURED

    def test_apply_edit_completes_skipped_task(self):
        """跳过任务经编辑补完后同样回到待发（B5 的编辑路径）"""
        qs = QueueState()
        t = make_incomplete_task(danmaku_count=1, status=TaskStatus.SKIPPED)
        qs.add_task(t)
        qs.update_task_status(t.task_id, TaskStatus.SKIPPED, "未指定视频目标")
        draft = qs.get_task_by_id(t.task_id).to_draft()
        draft.target = VideoTarget(bvid="BV1xx411c7mD", cid=1001, title="我的视频")
        qs.apply_edit(t.task_id, draft)
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status is TaskStatus.PENDING

    def test_apply_edit_keeps_skipped_when_incomplete(self):
        qs = QueueState()
        t = make_incomplete_task(danmaku_count=1, status=TaskStatus.SKIPPED)
        qs.add_task(t)
        qs.update_task_status(t.task_id, TaskStatus.SKIPPED, "未指定视频目标")
        draft = qs.get_task_by_id(t.task_id).to_draft()
        draft.p_title = "改个标题"
        qs.apply_edit(t.task_id, draft)
        view = qs.get_task_by_id(t.task_id)
        assert view is not None
        assert view.status is TaskStatus.SKIPPED
        assert view.p_title == "改个标题"

    def test_apply_edit_emits_status_then_data_on_flip(self):
        """状态翻转：先 taskStatusChanged 再 taskDataChanged"""
        qs = QueueState()
        t = make_incomplete_task(danmaku_count=1)
        qs.add_task(t)
        events: list[str] = []
        qs.taskStatusChanged.connect(lambda tid, s: events.append("status"))
        qs.taskDataChanged.connect(lambda tid: events.append("data"))
        draft = qs.get_task_by_id(t.task_id).to_draft()
        draft.target = VideoTarget(bvid="BV1xx411c7mD", cid=1001, title="我的视频")
        qs.apply_edit(t.task_id, draft)
        assert events == ["status", "data"]

    def test_apply_edit_emits_data_only_without_flip(self):
        qs = QueueState()
        t = make_incomplete_task(danmaku_count=1)
        qs.add_task(t)
        events: list[str] = []
        qs.taskStatusChanged.connect(lambda tid, s: events.append("status"))
        qs.taskDataChanged.connect(lambda tid: events.append("data"))
        draft = qs.get_task_by_id(t.task_id).to_draft()
        draft.p_title = "改个标题"
        qs.apply_edit(t.task_id, draft)
        assert events == ["data"]

    def test_sendable_danmaku_count_excludes_unconfigured(self):
        """未配置任务的弹幕不进发送进度分母"""
        qs = QueueState()
        ready = make_task(1)
        ready.danmakus = [Danmaku(msg="a", progress=0), Danmaku(msg="b", progress=1)]
        ready.total = 2
        qs.add_task(ready)
        qs.add_task(make_incomplete_task(danmaku_count=5))
        assert qs.total_danmaku_count == 7
        assert qs.sendable_danmaku_count == 2

    def test_sendable_danmaku_count_excludes_skipped_incomplete(self):
        """被跳过的残缺任务同样不进分母：状态翻走了，弹幕照样发不出去"""
        qs = QueueState()
        ready = make_task(1)
        qs.add_task(ready)
        skipped_incomplete = make_incomplete_task(danmaku_count=5, status=TaskStatus.SKIPPED)
        qs.add_task(skipped_incomplete)
        assert qs.get_task_by_id(skipped_incomplete.task_id).status is TaskStatus.SKIPPED
        assert qs.sendable_danmaku_count == 1

    def test_add_task_never_leaves_incomplete_pending(self):
        """入队时按配置完整性对齐状态，不信任草稿自带的 status"""
        qs = QueueState()
        lying = make_task(1, TaskStatus.PENDING, danmaku_count=0)
        qs.add_task(lying)
        assert qs.get_task_by_id(lying.task_id).status is TaskStatus.UNCONFIGURED

    def test_add_task_promotes_complete_draft(self):
        """配置齐备的草稿即便标着未配置，入队即转待发"""
        qs = QueueState()
        stale = make_task(1, TaskStatus.UNCONFIGURED)
        qs.add_task(stale)
        assert qs.get_task_by_id(stale.task_id).status is TaskStatus.PENDING

    def test_startable_covers_paused(self):
        """PAUSED 属于可启动范围：start_queue 会先把残留运行态转回 PENDING"""
        qs = QueueState()
        qs.add_task(make_task(1, TaskStatus.PAUSED))
        assert qs.has_startable_tasks is True
        assert qs.has_pending_tasks is False

    def test_startable_ignores_terminal_states(self):
        """终态与未配置都不构成可启动的任务"""
        qs = QueueState()
        for status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            qs.add_task(make_task(1, status))
        # SKIPPED / UNCONFIGURED 要留在原状态，得是缺配置的——
        # 配置齐备的会在入队时被纠回待发
        for status in (TaskStatus.SKIPPED, TaskStatus.UNCONFIGURED):
            qs.add_task(make_task(1, status, danmaku_count=0))
        assert qs.has_startable_tasks is False
