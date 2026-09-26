"""QueueSendWorker 队列 ETA 计算的边界行为"""
import pytest

from danmaku_sender.config import SendPolicy
from danmaku_sender.controller.sender.workers import QueueSendWorker
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    TaskConfig,
    TaskSnapshot,
    TaskSpec,
    TaskStatus,
)


def _spec(task_id: str, total: int = 2) -> TaskSpec:
    """构造最小可用的工单。

    弹幕数默认 2：DelayManager.calc_eta 的契约是「最后一条发完不产生延时」，
    只有 1 条时任务自身 ETA 为 0，无法区分「间隔」与「任务耗时」。
    节奏取同值，便于只比较间隔部分。
    """
    return TaskSpec(
        task_id=task_id,
        target=VideoTarget(bvid="BV1", cid=1),
        danmakus=tuple(Danmaku(msg="x", progress=0) for _ in range(total)),
        config=TaskConfig(
            min_delay=1.0, max_delay=1.0,
            burst_enabled=False, burst_size=3,
            rest_min=1.0, rest_max=1.0,
        ),
    )


def _eta(future: tuple[TaskSnapshot, ...], policy: SendPolicy) -> float:
    return QueueSendWorker._calc_queue_eta(0, 1, _spec("t1").config, future, policy)


class TestCalcQueueEta:
    def test_no_extra_gap_when_future_all_done(self):
        """剩余任务全是非 PENDING 时，不应多算一次任务间隔。

        回归：原实现按 future_tasks 判断是否加间隔，即使它们都不会被发送。
        """
        policy = SendPolicy(delay_between_tasks=100.0)
        future = (
            TaskSnapshot(spec=_spec("t2"), status=TaskStatus.COMPLETED),
            TaskSnapshot(spec=_spec("t3"), status=TaskStatus.FAILED),
            TaskSnapshot(spec=_spec("t4"), status=TaskStatus.SKIPPED),
        )
        assert _eta(future, policy) == _eta((), policy)

    def test_trailing_non_pending_adds_no_gap(self):
        """末尾是非 PENDING 任务时，不应在最后一个待发任务后再加间隔。

        回归：原实现用 future_tasks[-1] 判断边界，末尾有非 PENDING 就会多算。
        """
        policy = SendPolicy(delay_between_tasks=100.0)
        trailing_done = (
            TaskSnapshot(spec=_spec("t2"), status=TaskStatus.PENDING),
            TaskSnapshot(spec=_spec("t3"), status=TaskStatus.COMPLETED),
        )
        only_pending = (TaskSnapshot(spec=_spec("t2"), status=TaskStatus.PENDING),)
        assert _eta(trailing_done, policy) == _eta(only_pending, policy)

    def test_one_gap_per_pending_task(self):
        """每个待发任务前算一次间隔：每多一个待发任务，增量相同。"""
        policy = SendPolicy(delay_between_tasks=100.0)
        first = TaskSnapshot(spec=_spec("t2"), status=TaskStatus.PENDING)
        second = TaskSnapshot(spec=_spec("t3"), status=TaskStatus.PENDING)

        base = _eta((), policy)
        one = _eta((first,), policy)
        two = _eta((first, second), policy)

        # 两个任务的 config/弹幕数相同，故每个增量 = 一个间隔 + 一个任务 ETA
        assert one - base > policy.delay_between_tasks, "应含至少一个任务间隔"
        assert two - one == pytest.approx(one - base)
