"""QueueSendWorker 的收尾语义：未执行任务的处置与终局信号。

已知致命结果才把未执行的任务补标中止；未预期异常让它们保持待发、可重试。
终局信号与 ending 一律发出，BaseException 逃逸也不例外。
"""

import threading

import pytest

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, SenderConfig
from danmaku_sender.controller.sender.workers import QueueSendWorker
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.queue import (
    DanmakuPack,
    SendOptions,
    TargetSlot,
    Task,
    TaskConfig,
    TaskState,
    TaskStatus,
)


class _AbnormalExit(BaseException):
    """模拟打穿 except Exception 的 BaseException（如 KeyboardInterrupt）。"""


class Record:
    """收集 QueueSendWorker 收尾信号的发射记录。"""

    def __init__(self, worker: QueueSendWorker) -> None:
        self.skipped: list[tuple[str, str]] = []
        self.aborted: int = 0
        self.completed: int = 0
        self.ended: int = 0
        worker.taskSkipped.connect(self._on_skipped)
        worker.queueAborted.connect(self._on_aborted)
        worker.queueCompleted.connect(self._on_completed)
        worker.ending.connect(self._on_ending)

    def _on_skipped(self, task_id: str, reason: str) -> None:
        self.skipped.append((task_id, reason))

    def _on_aborted(self) -> None:
        self.aborted += 1

    def _on_completed(self) -> None:
        self.completed += 1

    def _on_ending(self, worker: object) -> None:
        self.ended += 1


def _task(task_id: str) -> Task:
    return Task(
        task_id=task_id,
        slot=TargetSlot(target=VideoTarget(bvid="BV1", cid=1), video_title="标题"),
        pack=DanmakuPack(),
        options=SendOptions(
            pacing=TaskConfig(
                min_delay=0.1, max_delay=0.1, burst_enabled=False, burst_size=0, rest_min=0.0, rest_max=0.0
            )
        ),
        state=TaskState(status=TaskStatus.PENDING),
    )


def _worker(tmp_path, *task_ids: str) -> QueueSendWorker:
    return QueueSendWorker(
        tasks=tuple(_task(task_id) for task_id in task_ids),
        auth=ApiAuthConfig(sessdata="sess", bili_jct="csrf"),
        network=NetworkPolicy(),
        queue_config=SenderConfig.QueueConfig(delay_between_tasks=0.0),
        history_manager=HistoryManager(tmp_path / "history.db"),
        stop_event=threading.Event(),
    )


def test_abort_marks_remaining_tasks(tmp_path, monkeypatch):
    """致命错误中止：未执行的任务补标中止"""
    worker = _worker(tmp_path, "t1", "t2", "t3")
    monkeypatch.setattr(QueueSendWorker, "_execute_task", lambda self, task, idx, total: False)
    seen = Record(worker)

    worker.run()

    assert seen.skipped == [("t2", "致命错误，队列中止"), ("t3", "致命错误，队列中止")]
    assert (seen.aborted, seen.completed, seen.ended) == (1, 0, 1)


def test_crash_keeps_remaining_tasks_pending(tmp_path, monkeypatch):
    """未预期异常中止：未执行的任务保持待发、可重试，不补标"""
    worker = _worker(tmp_path, "t1", "t2", "t3")

    def boom(self, task, idx, total):
        raise RuntimeError("执行器异常")

    monkeypatch.setattr(QueueSendWorker, "_execute_task", boom)
    seen = Record(worker)

    worker.run()

    assert seen.skipped == []
    assert (seen.aborted, seen.completed, seen.ended) == (1, 0, 1)


def test_base_exception_escape_still_ends_queue(tmp_path, monkeypatch):
    """BaseException 逃逸也要发终局信号与 ending，否则控制器永久锁住队列"""
    worker = _worker(tmp_path, "t1", "t2")

    def boom(self, task, idx, total):
        raise _AbnormalExit

    monkeypatch.setattr(QueueSendWorker, "_execute_task", boom)
    seen = Record(worker)

    with pytest.raises(_AbnormalExit):
        worker.run()

    assert seen.skipped == []
    assert (seen.aborted, seen.completed, seen.ended) == (1, 0, 1)


def test_completed_emits_queue_completed(tmp_path, monkeypatch):
    """跑完全部任务发 queueCompleted 与 ending"""
    worker = _worker(tmp_path, "t1")
    monkeypatch.setattr(QueueSendWorker, "_execute_task", lambda self, task, idx, total: True)
    seen = Record(worker)

    worker.run()

    assert (seen.aborted, seen.completed, seen.ended) == (0, 1, 1)


def test_stop_aborts_without_marking(tmp_path):
    """手动停止：未执行的任务保持待发，不补标"""
    worker = _worker(tmp_path, "t1", "t2")
    worker.stop_event.set()
    seen = Record(worker)

    worker.run()

    assert seen.skipped == []
    assert (seen.aborted, seen.completed, seen.ended) == (1, 0, 1)
