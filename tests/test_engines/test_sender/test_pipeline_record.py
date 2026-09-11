"""发送管线存证回归 — 发送成功后记录必须真实落库

回归 2026-09 存证静默丢失事故：POST 成功但数据库无记录时，本测试会在 CI 当场变红。
"""
import sqlite3
import threading

import pytest

from danmaku_sender.config import ApiAuthConfig, SenderConfig
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.service.sender import SendPipeline, SendJob
from danmaku_sender.service.sender import pipeline as pipeline_mod
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku


SENT_DMIDS: list[str] = []


class StubClient:
    """伪 B 站客户端：POST 恒成功并返回递增 dmid"""

    def __init__(self, auth_config):
        pass

    @classmethod
    def from_config(cls, auth_config):
        return cls(auth_config)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post_danmaku(self, cid, bvid, params):
        dmid = str(900000000000000000 + len(SENT_DMIDS))
        SENT_DMIDS.append(dmid)
        return {"code": 0, "message": "0", "data": {"dmid_str": dmid, "visible": True}}


@pytest.fixture
def pipeline_env(tmp_path, monkeypatch) -> HistoryManager:
    hm = HistoryManager(tmp_path / "history.db")
    monkeypatch.setattr(pipeline_mod, "BiliApiClient", StubClient)
    return hm


def _run_pipeline(hm: HistoryManager, target: VideoTarget, danmakus: list[Danmaku]) -> None:
    """在独立线程中执行管线，与 QueueWorker 的真实调用方式一致"""
    pipeline = SendPipeline(
        ApiAuthConfig(sessdata="x", bili_jct="y", use_system_proxy=False), hm
    )
    job = SendJob(
        target=target,
        danmakus=danmakus,
        config=SenderConfig(min_delay=0.1, max_delay=0.2),
        stop_event=threading.Event(),
    )
    errors: list[Exception] = []

    def runner():
        try:
            pipeline.execute(job)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    t = threading.Thread(target=runner)
    t.start()
    t.join()
    assert not errors, f"管线执行异常: {errors}"


class TestPipelineRecord:
    def test_successful_send_records_to_db(self, pipeline_env):
        """每条发送成功的弹幕都必须有存证行"""
        hm = pipeline_env
        target = VideoTarget(bvid="BV1xx", cid=1001, title="T")
        _run_pipeline(hm, target, [Danmaku(msg="a", progress=1000), Danmaku(msg="b", progress=2000)])

        conn = sqlite3.connect(hm.db_path)
        rows = conn.execute("SELECT dmid, cid, status FROM sent_danmaku ORDER BY dmid").fetchall()
        conn.close()
        assert len(rows) == 2
        assert all(r[1] == 1001 for r in rows)
        assert all(r[2] == 0 for r in rows)  # PENDING

    def test_failed_post_leaves_no_record(self, pipeline_env, monkeypatch):
        """发送失败的弹幕不应有存证"""
        hm = pipeline_env

        def fail_post(self, cid, bvid, params):
            return {"code": -400, "message": "请求错误", "data": {}}

        monkeypatch.setattr(StubClient, "post_danmaku", fail_post)
        target = VideoTarget(bvid="BV1xx", cid=1001, title="T")
        _run_pipeline(hm, target, [Danmaku(msg="a", progress=1000)])

        n = sqlite3.connect(hm.db_path).execute("SELECT COUNT(*) FROM sent_danmaku").fetchone()[0]
        assert n == 0
