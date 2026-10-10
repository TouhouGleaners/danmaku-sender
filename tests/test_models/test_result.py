"""BiliSendResponse 模型单元测试"""
from danmaku_sender.types.exceptions.api_errors import BiliDmErrorCode
from danmaku_sender.types.models.result import BiliSendResponse


class TestFromApiJson:
    """from_api_json 工厂方法"""

    def test_success_response(self):
        resp = {
            "code": 0,
            "message": "success",
            "data": {"dmid_str": "12345", "visible": True}
        }
        result = BiliSendResponse.from_api_json(resp)
        assert result.code == 0
        assert result.is_success is True
        assert result.dmid == "12345"
        assert result.is_visible is True
        assert result.hint == "弹幕发送成功。"

    def test_success_with_dmid_int_fallback(self):
        """data 里只有 dmid 没有 dmid_str"""
        resp = {
            "code": 0,
            "message": "ok",
            "data": {"dmid": 67890}
        }
        result = BiliSendResponse.from_api_json(resp)
        assert result.is_success is True
        assert result.dmid == "67890"

    def test_success_visible_false(self):
        resp = {
            "code": 0,
            "message": "ok",
            "data": {"dmid_str": "111", "visible": False}
        }
        result = BiliSendResponse.from_api_json(resp)
        assert result.is_visible is False

    def test_freq_limit_error(self):
        resp = {"code": 36703, "message": "发送频率过快"}
        result = BiliSendResponse.from_api_json(resp)
        assert result.code == 36703
        assert result.is_success is False
        assert "频率" in result.hint

    def test_unauthorized_error(self):
        resp = {"code": -101, "message": "未登录"}
        result = BiliSendResponse.from_api_json(resp)
        assert result.is_success is False
        assert "SESSDATA" in result.hint

    def test_unknown_error_with_message(self):
        """未知错误码应透传 B站原话"""
        resp = {"code": -12345, "message": "一些奇怪的错误"}
        result = BiliSendResponse.from_api_json(resp)
        assert result.is_success is False
        assert result.hint == "一些奇怪的错误"

    def test_unknown_error_without_message(self):
        """未知错误码且无 message 时用默认描述"""
        resp = {"code": -12345}
        result = BiliSendResponse.from_api_json(resp)
        assert "未定义" in result.hint

    def test_missing_code_defaults_to_response_malformed(self):
        resp = {"message": "no code field"}
        result = BiliSendResponse.from_api_json(resp)
        assert result.code == BiliDmErrorCode.RESPONSE_MALFORMED.code

    def test_missing_message_defaults_to_empty(self):
        resp = {"code": 0, "data": {}}
        result = BiliSendResponse.from_api_json(resp)
        assert result.msg == ""

    def test_success_with_empty_data_dict(self):
        resp = {"code": 0, "message": "ok", "data": {}}
        result = BiliSendResponse.from_api_json(resp)
        assert result.is_success is True
        assert result.dmid == ""

    def test_success_with_data_none(self):
        """data 不是 dict 的情况"""
        resp = {"code": 0, "message": "ok", "data": None}
        result = BiliSendResponse.from_api_json(resp)
        assert result.is_success is True
        assert result.dmid == ""
