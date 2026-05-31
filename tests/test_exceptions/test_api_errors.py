"""BiliDmErrorCode 枚举单元测试"""
import pytest
from danmaku_sender.core.exceptions.api_errors import BiliDmErrorCode, ERROR_METADATA


class TestFromCode:
    """from_code 映射"""

    def test_success(self):
        assert BiliDmErrorCode.from_code(0) == BiliDmErrorCode.SUCCESS

    def test_unauthorized(self):
        assert BiliDmErrorCode.from_code(-101) == BiliDmErrorCode.UNAUTHORIZED

    def test_freq_limit(self):
        assert BiliDmErrorCode.from_code(36703) == BiliDmErrorCode.FREQ_LIMIT

    def test_unknown_code_fallback(self):
        assert BiliDmErrorCode.from_code(-12345) == BiliDmErrorCode.BILI_UNKNOWN_ERROR

    def test_large_unknown_code(self):
        assert BiliDmErrorCode.from_code(99999) == BiliDmErrorCode.BILI_UNKNOWN_ERROR

    def test_network_error(self):
        assert BiliDmErrorCode.from_code(-9001) == BiliDmErrorCode.NETWORK_ERROR


class TestDescription:
    """description 属性"""

    def test_success_description(self):
        assert "成功" in BiliDmErrorCode.SUCCESS.description

    def test_unauthorized_description(self):
        assert "SESSDATA" in BiliDmErrorCode.UNAUTHORIZED.description

    def test_freq_limit_description(self):
        assert "频率" in BiliDmErrorCode.FREQ_LIMIT.description

    def test_all_codes_have_description(self):
        """所有已定义的枚举成员都应有对应描述"""
        for member in BiliDmErrorCode:
            desc = member.description
            assert desc, f"{member.name} 缺少描述"
            assert desc != "未知错误", f"{member.name} 描述不应为默认值"


class TestIsFatal:
    """is_fatal 分类"""

    @pytest.mark.parametrize("code,expected_fatal", [
        (0, False),       # SUCCESS
        (-101, True),     # UNAUTHORIZED
        (-102, True),     # ACCOUNT_BANNED
        (-111, True),     # CSRF_FAILED
        (-400, False),    # REQUEST_ERROR
        (-404, True),     # NOT_FOUND
        (36700, True),    # SYSTEM_UPGRADING
        (36701, False),   # CONTENT_FORBIDDEN
        (36702, False),   # DANMAKU_TOO_LONG
        (36703, False),   # FREQ_LIMIT
        (36704, True),    # VIDEO_NOT_REVIEWED
        (36705, True),    # LEVEL_INSUFFICIENT_GENERAL
        (36706, False),   # LEVEL_INSUFFICIENT_TOP
        (36707, False),   # LEVEL_INSUFFICIENT_BOTTOM
        (36708, False),   # LEVEL_INSUFFICIENT_COLOR
        (36709, False),   # LEVEL_INSUFFICIENT_ADVANCED
        (36710, False),   # PERMISSION_INSUFFICIENT_STYLE
        (36711, True),    # VIDEO_DANMAKU_FORBIDDEN
        (36712, False),   # LENGTH_LIMIT_LEVEL1
        (36713, True),    # VIDEO_NOT_PAID
        (36714, False),   # INVALID_PROGRESS
        (36715, False),   # DAILY_LIMIT_EXCEEDED
        (36718, False),   # NOT_PREMIUM_MEMBER
        (-1, True),       # BILI_SERVER_ERROR
        (-999, True),     # BILI_UNKNOWN_ERROR
        (-9001, True),    # NETWORK_ERROR
        (-9002, True),    # PROTOCOL_ERROR
        (-9003, True),    # RESPONSE_MALFORMED
        (-9999, True),    # CLIENT_RUNTIME_ERROR
    ])
    def test_fatal_classification(self, code: int, expected_fatal: bool):
        err = BiliDmErrorCode.from_code(code)
        assert err.is_fatal == expected_fatal, f"{err.name} (code={code}) fatal 应为 {expected_fatal}"


class TestMetadataCompleteness:
    """所有枚举成员都有 ERROR_METADATA 条目"""

    def test_all_members_in_metadata(self):
        for member in BiliDmErrorCode:
            assert member in ERROR_METADATA, f"{member.name} 不在 ERROR_METADATA 中"

    def test_metadata_no_extra_keys(self):
        for key in ERROR_METADATA:
            assert isinstance(key, BiliDmErrorCode), f"非法键: {key}"
