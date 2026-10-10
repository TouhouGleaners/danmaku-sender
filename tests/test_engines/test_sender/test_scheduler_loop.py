"""DanmakuScheduler 发送循环测试 — 记账/查重/中止/诊断

- 记账：跳过、成功、失败、未发出清单的计数与归类。
- 存证降级：远端成功但未入账。
- 诊断：致命原因与异常中断时的未发出清单。
"""
from threading import Event

import pytest

from danmaku_sender.config import SenderConfig, SendPolicy
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.service.sender.context import SendingContext, SendJob
from danmaku_sender.service.sender.scheduler import DanmakuScheduler
from danmaku_sender.types.exceptions.api_errors import BiliDmErrorCode
from danmaku_sender.types.exceptions.exceptions import HistoryStorageError
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.result import BiliSendResponse, SendStatus

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)


class StubExecutor:
    """伪发包器：按脚本逐条返回响应，脚本耗尽后重复返回末项。"""

    def __init__(self, script: list[BiliSendResponse]):
        self.script = list(script)
        self.calls: list[Danmaku] = []

    def execute(self, target, danmaku, stop_event) -> BiliSendResponse:
        self.calls.append(danmaku)
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]


class FailingExecutor:
    """伪发包器：指定序号的调用抛出异常。"""

    def __init__(self, fail_on_call: int = 0):
        self.fail_on_call = fail_on_call
        self.calls = 0

    def execute(self, target, danmaku, stop_event) -> BiliSendResponse:
        self.calls += 1
        if self.calls - 1 == self.fail_on_call:
            raise RuntimeError("执行器异常")
        return BiliSendResponse(code=0, is_success=True, msg="ok", hint="弹幕发送成功。", dmid=f"dm{self.calls}")


def ok_response(dmid: str = "dm-ok") -> BiliSendResponse:
    return BiliSendResponse(code=0, is_success=True, msg="ok", hint="弹幕发送成功。", dmid=dmid)


def failed_response(hint: str = "被拒绝", fatal: bool = False) -> BiliSendResponse:
    code = BiliDmErrorCode.ACCOUNT_BANNED.code if fatal else BiliDmErrorCode.FREQ_LIMIT.code
    return BiliSendResponse(code=code, is_success=False, msg="bad", hint=hint)


def degraded_response() -> BiliSendResponse:
    """远端接受但未返回 dmid。"""
    return BiliSendResponse(code=0, is_success=True, msg="ok", hint="弹幕发送成功。", dmid="")


def make_dms(*msgs: str) -> list[Danmaku]:
    return [Danmaku(msg=m, progress=1000 + i) for i, m in enumerate(msgs)]


def build_job(dms: list[Danmaku], **overrides) -> SendJob:
    defaults = {
        "task_id": "t1",
        "target": TARGET,
        "danmakus": dms,
        "config": SenderConfig(min_delay=0.1, max_delay=0.1).to_task_config(),
        "policy": SendPolicy(),
        "stop_event": Event(),
    }
    defaults.update(overrides)
    return SendJob(**defaults)


def run(scheduler: DanmakuScheduler, job: SendJob) -> SendingContext:
    ctx = SendingContext(total=len(job.danmakus), target=job.target)
    scheduler.run_pipeline(job, ctx)
    return ctx


@pytest.fixture
def hm(tmp_path) -> HistoryManager:
    return HistoryManager(tmp_path / "history.db")


def make_scheduler(hm: HistoryManager, executor) -> DanmakuScheduler:
    return DanmakuScheduler(executor, hm)


class TestAccounting:
    """发送循环的记账结果"""

    def test_all_sent_successfully(self, hm):
        """全部发送成功时计数正确，未发出清单为空"""
        executor = StubExecutor([ok_response("d1"), ok_response("d2")])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a", "b")))

        assert len(executor.calls) == 2
        assert ctx.success_count == 2
        assert ctx.attempted_count == 2
        assert ctx.skipped_count == 0
        assert ctx.unsent_records == []
        assert ctx.fatal_error_occurred is False

    def test_each_send_is_recorded(self, hm):
        """发送成功后写入账本"""
        executor = StubExecutor([ok_response("d1"), ok_response("d2")])
        run(make_scheduler(hm, executor), build_job(make_dms("a", "b")))
        assert hm.count_records(TARGET, Danmaku(msg="a", progress=1000)) == 1
        assert hm.count_records(TARGET, Danmaku(msg="b", progress=1001)) == 1

    def test_dedup_skips_already_recorded(self, hm):
        """账本已有的弹幕查重跳过，不再发包"""
        hm.record_danmaku("t1", TARGET, Danmaku(msg="a", progress=1000), "d0")
        executor = StubExecutor([ok_response("d1"), ok_response("d2")])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a", "b")))

        assert len(executor.calls) == 1
        assert ctx.skipped_count == 1
        assert ctx.success_count == 1
        assert ctx.unsent_records == []

    def test_nonfatal_failure_goes_to_unsent_and_loop_continues(self, hm):
        """非致命失败记入未发出清单，循环继续"""
        executor = StubExecutor([failed_response("限流中"), ok_response("d2")])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a", "b")))

        assert len(executor.calls) == 2
        assert ctx.success_count == 1
        assert len(ctx.unsent_records) == 1
        assert ctx.unsent_records[0]['dm'].msg == "a"
        assert ctx.unsent_records[0]['reason'] == "限流中"
        assert ctx.fatal_error_occurred is False

    def test_fatal_failure_stops_loop_and_keeps_remaining(self, hm):
        """致命失败中止循环，当前条与剩余条记入未发出清单"""
        executor = StubExecutor([failed_response("致命", fatal=True), ok_response("d2")])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a", "b", "c")))

        assert len(executor.calls) == 1
        assert ctx.fatal_error_occurred is True
        assert [r['dm'].msg for r in ctx.unsent_records] == ["a", "b", "c"]

    def test_manual_stop_keeps_remaining(self, hm):
        """手动停止后未发出的弹幕记入未发出清单"""
        job = build_job(make_dms("a", "b", "c"))
        executor = StubExecutor([ok_response("d1"), ok_response("d2"), ok_response("d3")])
        job.stop_event.set()
        ctx = run(make_scheduler(hm, executor), job)

        assert len(executor.calls) == 0
        assert [r['dm'].msg for r in ctx.unsent_records] == ["a", "b", "c"]
        assert ctx.unsent_records[0]['reason'] == "任务手动停止"

    def test_auto_stop_keeps_remaining(self, hm):
        """触发数量上限自动停止后，剩余弹幕记入未发出清单"""
        policy = SendPolicy(stop_after_count=1)
        executor = StubExecutor([ok_response("d1"), ok_response("d2"), ok_response("d3")])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a", "b", "c"), policy=policy))

        assert ctx.success_count == 1
        assert ctx.auto_stop_reason != ""
        assert [r['dm'].msg for r in ctx.unsent_records] == ["b", "c"]

    def test_empty_job_is_noop(self, hm):
        """空任务不发包、不记账"""
        executor = StubExecutor([ok_response()])
        ctx = run(make_scheduler(hm, executor), build_job([]))
        assert len(executor.calls) == 0
        assert ctx.success_count == 0

    def test_duplicate_fingerprints_are_counted_separately(self, hm):
        """同指纹多条按出现次数查重，跳过数以账本记录数为准"""
        dms = [Danmaku(msg="same", progress=1000)] * 3
        hm.record_danmaku("t1", TARGET, dms[0], "d0")
        executor = StubExecutor([ok_response("d1"), ok_response("d2")])
        ctx = run(make_scheduler(hm, executor), build_job(dms))

        assert ctx.skipped_count == 1
        assert len(executor.calls) == 2


class TestDegradedAccounting:
    """存证降级：远端成功但未入账"""

    def test_missing_dmid_is_degraded_not_success(self, hm):
        """未返回 dmid 时判为降级并记入 evidence_failures"""
        executor = StubExecutor([degraded_response()])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a")))

        assert ctx.success_count == 1
        assert len(ctx.evidence_failures) == 1
        assert ctx.evidence_failures[0][0].msg == "a"

    def test_storage_failure_is_degraded_not_success(self, hm, monkeypatch):
        """落库失败时判为降级并记入 evidence_failures"""

        def raise_storage_error(*args, **kwargs):
            raise HistoryStorageError("落库异常")

        monkeypatch.setattr(hm, "record_danmaku", raise_storage_error)
        executor = StubExecutor([ok_response("d1")])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a")))

        assert ctx.success_count == 1
        assert len(ctx.evidence_failures) == 1

    def test_degraded_danmaku_is_not_in_ledger(self, hm):
        """降级弹幕不写入账本"""
        executor = StubExecutor([degraded_response()])
        run(make_scheduler(hm, executor), build_job(make_dms("a")))
        assert hm.count_records(TARGET, Danmaku(msg="a", progress=1000)) == 0


class TestDiagnostics:
    """诊断信息的留存"""

    def test_fatal_reason_is_kept(self, hm):
        """致命错误的响应提示写入 fatal_error_msg"""
        executor = StubExecutor([failed_response("账号被封禁", fatal=True)])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a")))
        assert ctx.fatal_error_occurred is True
        assert ctx.fatal_error_msg == "账号被封禁"

    def test_exception_marks_fatal_with_reason(self, hm):
        """循环内异常置致命并写入 fatal_error_msg"""
        executor = FailingExecutor(fail_on_call=0)
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a", "b")))
        assert ctx.fatal_error_occurred is True
        assert "执行器异常" in ctx.fatal_error_msg

    def test_exception_keeps_pending_in_unsent(self, hm):
        """循环内异常时未发出的弹幕记入未发出清单"""
        executor = FailingExecutor(fail_on_call=1)
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a", "b", "c")))
        assert [r['dm'].msg for r in ctx.unsent_records] == ["b", "c"]

    def test_result_callback_sees_recorded_result(self, hm):
        """记账先于 result_callback，回调异常不丢记账结论"""
        seen: list[tuple[str, bool]] = []
        ledger_at_callback: list[int] = []

        def callback(dm, result):
            ledger_at_callback.append(hm.count_records(TARGET, dm))
            seen.append((dm.msg, result.status is SendStatus.SUCCESS))
            raise RuntimeError("回调异常")

        executor = StubExecutor([ok_response("d1")])
        job = build_job(make_dms("a"), result_callback=callback)
        ctx = SendingContext(total=1, target=job.target)
        make_scheduler(hm, executor).run_pipeline(job, ctx)

        assert ledger_at_callback == [1], "回调运行时存证尚未落库"
        assert seen == [("a", True)]
        assert ctx.success_count == 1
        assert hm.count_records(TARGET, Danmaku(msg="a", progress=1000)) == 1, "回调抛异常丢了存证"
        assert ctx.fatal_error_occurred is True


class TestDedupReadFailure:
    """查重查询失败的处理"""

    def test_count_records_failure_aborts_loop(self, hm, monkeypatch):
        """查重查询失败时中止发送"""

        def raise_query_error(*args, **kwargs):
            raise HistoryStorageError("查重查询失败")

        monkeypatch.setattr(hm, "count_records", raise_query_error)
        executor = StubExecutor([ok_response("d1"), ok_response("d2")])
        ctx = run(make_scheduler(hm, executor), build_job(make_dms("a", "b")))

        assert len(executor.calls) == 0
        assert ctx.fatal_error_occurred is True
        assert "查重查询失败" in ctx.fatal_error_msg
