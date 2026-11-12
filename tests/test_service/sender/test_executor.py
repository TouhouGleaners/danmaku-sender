"""DanmakuExecutor 发包结论测试 — 单次发包、重试建议与策略边界"""

import pytest

from danmaku_sender.infra.bilibili.bili_api_client import BiliApiClient
from danmaku_sender.service.sender.executor import DanmakuExecutor, SendAttempt
from danmaku_sender.types.exceptions.api_errors import BiliDmErrorCode
from danmaku_sender.types.exceptions.exceptions import BiliApiError, BiliNetworkError
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)
DANMAKU = Danmaku(msg="a", progress=1000)


class StubClient(BiliApiClient):
    """伪 B 站客户端：给定异常就抛出，否则返回成功响应。"""

    def __init__(self, exc: Exception | None = None):
        self.exc = exc
        self.calls = 0

    def post_danmaku(self, cid, bvid, params):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return {"code": 0, "message": "0", "data": {"dmid_str": "dm1", "visible": True}}


class TestSend:
    def test_success_returns_response(self):
        """发包成功时给出最终响应"""
        attempt = DanmakuExecutor(StubClient()).send(TARGET, DANMAKU, 0)

        assert attempt.response is not None
        assert attempt.response.is_success

    def test_non_rate_limit_api_error_fails_immediately(self):
        """非限流的业务异常不再重试，一次发包即定论"""
        client = StubClient(BiliApiError(BiliDmErrorCode.ACCOUNT_BANNED.code, "账号被封停"))
        attempt = DanmakuExecutor(client).send(TARGET, DANMAKU, 0)

        assert attempt.response is not None
        assert attempt.response.code == BiliDmErrorCode.ACCOUNT_BANNED.code
        assert client.calls == 1

    @pytest.mark.parametrize("attempt_no", [0, 1, 2])
    def test_rate_limit_suggests_penalty_retry(self, attempt_no):
        """限流异常在重试额度内建议罚时后再试，单次尝试只发一包"""
        client = StubClient(BiliApiError(BiliDmErrorCode.FREQ_LIMIT.code, "限流"))
        attempt = DanmakuExecutor(client).send(TARGET, DANMAKU, attempt_no)

        assert attempt.response is None
        assert attempt.retry_delay == 10.0
        assert client.calls == 1

    def test_rate_limit_gives_up_after_max_retries(self):
        """限流重试额度用尽后定论为失败"""
        exc = BiliApiError(BiliDmErrorCode.FREQ_LIMIT.code, "限流")
        attempt = DanmakuExecutor(StubClient(exc)).send(TARGET, DANMAKU, DanmakuExecutor.MAX_RETRIES)

        assert attempt.response is not None
        assert attempt.response.code == BiliDmErrorCode.FREQ_LIMIT.code

    @pytest.mark.parametrize(("attempt_no", "delay"), [(0, 2.0), (1, 4.0), (2, 8.0)])
    def test_network_error_suggests_exponential_backoff(self, attempt_no, delay):
        """网络异常按指数退避建议等待时长，单次尝试只发一包"""
        client = StubClient(BiliNetworkError("连接超时"))
        attempt = DanmakuExecutor(client).send(TARGET, DANMAKU, attempt_no)

        assert attempt.response is None
        assert attempt.retry_delay == delay
        assert client.calls == 1

    def test_network_error_gives_up_after_max_retries(self):
        """网络异常重试额度用尽后定论为失败"""
        exc = BiliNetworkError("连接超时")
        attempt = DanmakuExecutor(StubClient(exc)).send(TARGET, DANMAKU, DanmakuExecutor.MAX_RETRIES)

        assert attempt.response is not None
        assert attempt.response.code == BiliDmErrorCode.NETWORK_ERROR.code


class TestSendAttempt:
    def test_attempt_without_response_requires_positive_delay(self):
        """既无响应又无正等待的结论拒绝构造，调用方拿到会零等待空转"""
        with pytest.raises(ValueError):
            SendAttempt()
