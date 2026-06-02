"""自定义异常类单元测试"""
import pytest
from danmaku_sender.core.exceptions.exceptions import BiliNetworkError, BiliApiError


class TestBiliNetworkError:
    def test_message_attribute(self):
        err = BiliNetworkError("连接超时")
        assert err.message == "连接超时"

    def test_catchable_as_exception(self):
        with pytest.raises(BiliNetworkError):
            raise BiliNetworkError("test")


class TestBiliApiError:
    def test_code_and_message(self):
        err = BiliApiError(code=36703, message="频率过快")
        assert err.code == 36703
        assert err.message == "频率过快"

    def test_catchable_with_code(self):
        with pytest.raises(BiliApiError) as exc_info:
            raise BiliApiError(code=-101, message="未登录")
        assert exc_info.value.code == -101
