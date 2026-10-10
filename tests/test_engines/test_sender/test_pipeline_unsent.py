"""SendPipeline 未发出清单的登记范围。

设置阶段或循环开始前的失败，整批都未发出，必须进 unsent_records 供导出；
调度器已处理过的弹幕不得重复登记。
"""
from threading import Event

import pytest

from danmaku_sender.config import ApiAuthConfig, SenderConfig, SendPolicy
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.service.sender import SendJob, SendPipeline
from danmaku_sender.service.sender import pipeline as pipeline_mod
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)
AUTH = ApiAuthConfig(sessdata="x", bili_jct="y", use_system_proxy=False)


class StubClient:
    """伪 B 站客户端：POST 恒成功并返回递增 dmid"""

    fail_on_exit = False

    def __init__(self, auth_config):
        self.sent = 0

    @classmethod
    def from_config(cls, auth_config):
        return cls(auth_config)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if type(self).fail_on_exit:
            raise RuntimeError("连接关闭失败")
        return False

    def post_danmaku(self, cid, bvid, params):
        self.sent += 1
        dmid = str(900000000000000000 + self.sent)
        return {"code": 0, "message": "0", "data": {"dmid_str": dmid, "visible": True}}


class BrokenClient:
    """伪客户端：构造阶段就失败"""

    @classmethod
    def from_config(cls, auth_config):
        raise RuntimeError("客户端构造失败")


@pytest.fixture
def hm(tmp_path) -> HistoryManager:
    return HistoryManager(tmp_path / "history.db")


def make_dms(*msgs: str) -> list[Danmaku]:
    return [Danmaku(msg=m, progress=1000 + i) for i, m in enumerate(msgs)]


def make_job(dms: list[Danmaku], **overrides) -> SendJob:
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


def execute(hm: HistoryManager, job: SendJob, **overrides):
    pipeline = SendPipeline(AUTH, hm)
    return pipeline.execute(job, **overrides)


class TestUnsentOnSetupFailure:
    """设置阶段失败时整批登记为未发出"""

    def test_client_construction_failure_registers_all(self, hm, monkeypatch):
        monkeypatch.setattr(pipeline_mod, "BiliApiClient", BrokenClient)
        ctx = execute(hm, make_job(make_dms("a", "b", "c")))

        assert ctx.fatal_error_occurred is True
        assert "客户端构造失败" in ctx.fatal_error_msg
        assert [r['dm'].msg for r in ctx.unsent_records] == ["a", "b", "c"]

    def test_progress_emitter_failure_before_loop_registers_all(self, hm, monkeypatch):
        """初始进度回调抛异常时，一条都还没发，整批登记为未发出"""
        monkeypatch.setattr(pipeline_mod, "BiliApiClient", StubClient)

        def boom(attempted, task_total, eta):
            raise RuntimeError("进度回调失败")

        ctx = execute(hm, make_job(make_dms("a", "b")), progress_emitter=boom)

        assert ctx.fatal_error_occurred is True
        assert [r['dm'].msg for r in ctx.unsent_records] == ["a", "b"]


class TestUnsentNotDuplicated:
    """调度器已处理过的弹幕不得重复登记"""

    def test_failure_after_run_registers_nothing(self, hm, monkeypatch):
        """跑完之后连接关闭失败：已发的不得进未发出清单"""
        StubClient.fail_on_exit = True
        try:
            monkeypatch.setattr(pipeline_mod, "BiliApiClient", StubClient)
            ctx = execute(hm, make_job(make_dms("a", "b")))
        finally:
            StubClient.fail_on_exit = False

        assert ctx.success_count == 2
        assert ctx.unsent_records == [], "已发出的弹幕进了未发出清单，导出会重复发"

    def test_partial_run_failure_keeps_unsent_accurate(self, hm, monkeypatch):
        """中途失败：只有没发出去的进清单"""
        monkeypatch.setattr(pipeline_mod, "BiliApiClient", StubClient)

        calls = {"n": 0}

        def flaky_post(self, cid, bvid, params):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("第二条发包失败")
            dmid = str(900000000000000000 + calls["n"])
            return {"code": 0, "message": "0", "data": {"dmid_str": dmid, "visible": True}}

        monkeypatch.setattr(StubClient, "post_danmaku", flaky_post)
        ctx = execute(hm, make_job(make_dms("a", "b", "c")))

        assert ctx.fatal_error_occurred is True
        assert [r['dm'].msg for r in ctx.unsent_records] == ["b", "c"]
