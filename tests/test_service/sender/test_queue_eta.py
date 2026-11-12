"""QueueSendWorker 队列预计时长的估算与上报边界行为"""

import threading

import pytest

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, SenderConfig
from danmaku_sender.controller.sender.workers import QueueSendWorker
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.service.sender import SendingContext
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    TaskConfig,
    TaskDefinition,
    TaskSnapshot,
    TaskStatus,
)


def _definition(task_id: str, total: int = 2) -> TaskDefinition:
    """构造最小可用的工单。

    弹幕数默认 2：等待发生在每条发送完毕后、最后一项不等，
    只有 1 条时任务自身预计时长为 0，无法区分「间隔」与「任务耗时」。
    节奏取同值，便于只比较间隔部分。
    """
    return TaskDefinition(
        task_id=task_id,
        target=VideoTarget(bvid="BV1", cid=1),
        danmakus=tuple(Danmaku(msg="x", progress=i) for i in range(total)),
        config=TaskConfig(
            min_delay=1.0, max_delay=1.0,
            burst_enabled=False, burst_size=3,
            rest_min=1.0, rest_max=1.0,
        ),
    )


def _tail_eta(
    hm: HistoryManager,
    future: tuple[TaskSnapshot, ...],
    queue_config: SenderConfig.QueueConfig | None = None,
) -> float:
    """构造一个 Worker 实例来估算队列尾部时长。"""
    worker = QueueSendWorker(
        tasks=(),
        auth=ApiAuthConfig(sessdata="x", bili_jct="y"),
        network=NetworkPolicy(use_system_proxy=False),
        queue_config=queue_config or SenderConfig.QueueConfig(),
        history_manager=hm,
        stop_event=threading.Event(),
    )
    return worker._tail_eta(future)


@pytest.fixture
def hm(tmp_path) -> HistoryManager:
    return HistoryManager(tmp_path / "history.db")


class TestTailEta:
    def test_no_extra_gap_when_future_all_done(self, hm, monkeypatch):
        """剩余任务全是非待发时，尾部时长为 0"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        future = (
            TaskSnapshot(definition=_definition("t2"), status=TaskStatus.COMPLETED),
            TaskSnapshot(definition=_definition("t3"), status=TaskStatus.FAILED),
            TaskSnapshot(definition=_definition("t4"), status=TaskStatus.SKIPPED),
        )
        assert _tail_eta(hm, future) == 0.0

    def test_trailing_non_pending_adds_no_gap(self, hm, monkeypatch):
        """末尾是非待发任务时，不应在最后一个待发任务后再加间隔"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        trailing_done = (
            TaskSnapshot(definition=_definition("t2"), status=TaskStatus.PENDING),
            TaskSnapshot(definition=_definition("t3"), status=TaskStatus.COMPLETED),
        )
        only_pending = (TaskSnapshot(definition=_definition("t2"), status=TaskStatus.PENDING),)

        # 一个待发任务 = 间隔 30 + 自身等待 1.0；两边都得是这个值，不许双双归零
        assert _tail_eta(hm, only_pending) == pytest.approx(31.0)
        assert _tail_eta(hm, trailing_done) == pytest.approx(31.0)

    def test_finished_task_adds_no_gap(self, hm, monkeypatch):
        """游标走满的空任务没有发送，不占任务间隔"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        done_cursor = TaskSnapshot(
            definition=_definition("t2"), status=TaskStatus.PENDING, attempted=2,
        )
        fresh = TaskSnapshot(definition=_definition("t3"), status=TaskStatus.PENDING)

        assert _tail_eta(hm, (done_cursor,)) == 0.0
        assert _tail_eta(hm, (done_cursor, fresh)) == pytest.approx(31.0)

    def test_one_gap_per_pending_task(self, hm, monkeypatch):
        """每个待发任务前算一次间隔：每多一个待发任务，增量相同"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        queue_config = SenderConfig.QueueConfig(delay_between_tasks=100.0)
        first = TaskSnapshot(definition=_definition("t2"), status=TaskStatus.PENDING)
        second = TaskSnapshot(definition=_definition("t3"), status=TaskStatus.PENDING)

        one = _tail_eta(hm, (first,), queue_config)
        two = _tail_eta(hm, (first, second), queue_config)

        # 每个任务 = 间隔 100 + 自身等待 1.0（2 条里第一条后等一次，最后一项不等）
        assert one == pytest.approx(101.0)
        assert two == pytest.approx(202.0)

    def test_future_task_eta_resumes_from_cursor(self, hm, monkeypatch):
        """续传后待发任务也可能带着游标，计划从游标起估，不算前半段"""
        monkeypatch.setattr("random.uniform", lambda a, b: b)
        queue_config = SenderConfig.QueueConfig(delay_between_tasks=0.0)
        fresh = TaskSnapshot(definition=_definition("t2", total=4), status=TaskStatus.PENDING)
        resumed = TaskSnapshot(
            definition=_definition("t2", total=4), status=TaskStatus.PENDING, attempted=2,
        )

        # total=4：从 0 起还有 3 次等待，从游标 2 起只剩 1 次（最后一项不等）
        assert _tail_eta(hm, (fresh,), queue_config) == pytest.approx(3.0)
        assert _tail_eta(hm, (resumed,), queue_config) == pytest.approx(1.0)


class TestQueueEtaReporting:
    def test_fatal_failure_zeroes_queue_eta(self, hm, monkeypatch):
        """致命失败中止整队：队列剩余时间归零，不再挂着后续任务的估算"""

        class StubPipeline:
            """伪流水线：上报一次任务进度后以致命错误收场。"""

            def __init__(self, *args, **kwargs):
                pass

            def execute(self, job, progress_emitter=None):
                ctx = SendingContext(total=1, target=job.target)
                ctx.fatal_error_occurred = True
                ctx.fatal_error_msg = "致命错误"
                if progress_emitter:
                    progress_emitter(0, 1, 42.0)
                return ctx

        monkeypatch.setattr("danmaku_sender.controller.sender.workers.SendPipeline", StubPipeline)
        snap = TaskSnapshot(definition=_definition("t1"), status=TaskStatus.PENDING)
        future = TaskSnapshot(definition=_definition("t2"), status=TaskStatus.PENDING)
        worker = QueueSendWorker(
            tasks=(snap, future),
            auth=ApiAuthConfig(sessdata="x", bili_jct="y"),
            network=NetworkPolicy(use_system_proxy=False),
            queue_config=SenderConfig.QueueConfig(),
            history_manager=hm,
            stop_event=threading.Event(),
        )
        received: list[float] = []
        worker.queueProgressUpdated.connect(lambda idx, total, eta: received.append(eta))

        worker._execute_task(snap, 0, 2)

        # 尾部含后续任务（间隔 30 + 计划等待 1.0）：归零上报必须把这个非零尾巴清掉
        assert received == [73.0, 0.0]
