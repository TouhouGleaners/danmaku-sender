"""发送 → 存证 → 核销 链路冒烟：三段必须靠同一个 task_id 串起来。

任务级历史的前提是这三段都落地且能对上，缺一段就查不出「这次发了哪些、存活如何」。
"""

import sqlite3
import threading

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, SenderConfig
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.service.sender import SendJob, SendPipeline
from danmaku_sender.service.sender import pipeline as pipeline_mod
from danmaku_sender.types.models.common import TaskMeta, VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDefinition, TaskStatus

TARGET = VideoTarget(bvid="BV1xx", cid=1001)
TASK_ID = "任务-冒烟"


class StubClient:
    """伪 B 站客户端：POST 恒成功并返回递增 dmid"""

    def __init__(self, auth, network):
        self._sent: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post_danmaku(self, cid, bvid, params):
        dmid = str(900000000000000000 + len(self._sent))
        self._sent.append(dmid)
        return {"code": 0, "message": "0", "data": {"dmid_str": dmid, "visible": True}}


def test_send_record_verify_share_task_id(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_mod, "BiliApiClient", StubClient)
    hm = HistoryManager(tmp_path / "history.db")

    definition = TaskDefinition(
        task_id=TASK_ID,
        target=TARGET,
        meta=TaskMeta(video_title="冒烟视频"),
        danmakus=(Danmaku(msg="a", progress=1000), Danmaku(msg="b", progress=2000)),
        config=SenderConfig.PacingConfig(min_delay=0.1, max_delay=0.2).to_task_config(),
    )

    # 1) 任务开始：写任务记录
    hm.upsert_task(definition, TaskStatus.RUNNING)

    # 2) 发送：每条成功弹幕存证，带上同一个 task_id
    pipeline = SendPipeline(
        ApiAuthConfig(sessdata="x", bili_jct="y"),
        NetworkPolicy(use_system_proxy=False),
        hm,
    )
    job = SendJob(
        task_id=TASK_ID,
        target=TARGET,
        danmakus=list(definition.danmakus),
        config=definition.config,
        queue_config=SenderConfig.QueueConfig(),
        stop_event=threading.Event(),
    )
    pipeline.execute(job)

    # 3) 任务结束：状态落账
    hm.upsert_task(definition, TaskStatus.COMPLETED)

    conn = sqlite3.connect(tmp_path / "history.db")
    evidence = conn.execute(
        "SELECT dmid, task_id, status FROM sent_danmaku ORDER BY dmid"
    ).fetchall()
    conn.close()

    assert len(evidence) == 2, "发送成功的弹幕都必须有存证行"
    assert all(row[1] == TASK_ID for row in evidence), "存证必须归属到同一个 task_id"
    assert all(row[2] == 0 for row in evidence), "存证初始为待验证"

    # 4) 核销：按 dmid 翻状态
    flipped = hm.verify_dmids([row[0] for row in evidence])
    assert flipped == 2

    # 5) 任务级历史：任务记录与存证能对上，存活统计看得见
    record = hm.get_task(TASK_ID)
    assert record["status"] == "COMPLETED"
    assert record["video_title"] == "冒烟视频"

    total, verified, lost = hm.get_stats(TARGET.cid)
    assert (total, verified, lost) == (2, 2, 0)
