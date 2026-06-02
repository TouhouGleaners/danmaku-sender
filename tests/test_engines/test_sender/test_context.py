"""SendingContext / SendJob 单元测试"""
import pytest
from danmaku_sender.core.models.danmaku import Danmaku
from danmaku_sender.core.models.common import VideoTarget
from danmaku_sender.core.state import SenderConfig
from danmaku_sender.core.engines.sender.context import SendingContext, SendJob
from threading import Event


@pytest.fixture
def sending_context() -> SendingContext:
    return SendingContext(
        total=10,
        config=SenderConfig(),
        target=VideoTarget(bvid="BV1xx411c7mD", cid=1001)
    )


class TestSendingContext:
    def test_initial_state(self, sending_context: SendingContext):
        assert sending_context.total == 10
        assert sending_context.attempted_count == 0
        assert sending_context.success_count == 0
        assert sending_context.skipped_count == 0
        assert sending_context.auto_stop_reason == ""
        assert sending_context.fatal_error_occurred is False
        assert sending_context.unsent_records == []

    def test_elapsed_minutes_is_float(self, sending_context: SendingContext):
        assert isinstance(sending_context.elapsed_minutes, float)
        assert sending_context.elapsed_minutes >= 0

    def test_add_unsent_single(self, sending_context: SendingContext):
        dm = Danmaku(msg="test", progress=1000)
        sending_context.add_unsent(dm, "网络错误")
        assert len(sending_context.unsent_records) == 1
        assert sending_context.unsent_records[0]['dm'] is dm
        assert sending_context.unsent_records[0]['reason'] == "网络错误"

    def test_add_unsent_list(self, sending_context: SendingContext):
        dms = [
            Danmaku(msg="a", progress=1000),
            Danmaku(msg="b", progress=2000),
        ]
        sending_context.add_unsent(dms, "频率限制")
        assert len(sending_context.unsent_records) == 2
        assert all(r['reason'] == "频率限制" for r in sending_context.unsent_records)

    def test_local_counter_default(self, sending_context: SendingContext):
        assert sending_context.local_counter == {}

    def test_db_count_cache_default(self, sending_context: SendingContext):
        assert sending_context.db_count_cache == {}


class TestSendJob:
    def test_creation(self):
        job = SendJob(
            target=VideoTarget(bvid="BV1test", cid=1),
            danmakus=[Danmaku(msg="t", progress=0)],
            config=SenderConfig(),
            stop_event=Event()
        )
        assert job.target.bvid == "BV1test"
        assert len(job.danmakus) == 1
        assert job.progress_callback is None
        assert job.result_callback is None
