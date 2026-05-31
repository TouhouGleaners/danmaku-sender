"""danmaku_validator 单元测试 — validate_danmaku_list"""
import pytest
from danmaku_sender.core.models.danmaku import Danmaku
from danmaku_sender.core.state import ValidationConfig
from danmaku_sender.core.services.danmaku_validator import validate_danmaku_list, FORBIDDEN_SYMBOLS


def _dm(msg: str, progress: int = 1000) -> Danmaku:
    """快捷构造弹幕"""
    return Danmaku(msg=msg, progress=progress)


class TestNewlineDetection:
    """换行符检查"""

    def test_backslash_n(self):
        issues = validate_danmaku_list([_dm("hello\\nworld")])
        assert len(issues) == 1
        assert "换行符" in issues[0]['reason']

    def test_slash_n(self):
        issues = validate_danmaku_list([_dm("hello/nworld")])
        assert len(issues) == 1
        assert "换行符" in issues[0]['reason']

    def test_no_newline(self):
        issues = validate_danmaku_list([_dm("正常弹幕")])
        assert len(issues) == 0


class TestLengthCheck:
    """长度 >100 检查"""

    def test_over_100_chars(self):
        issues = validate_danmaku_list([_dm("a" * 101)])
        assert len(issues) == 1
        assert "100" in issues[0]['reason']

    def test_exactly_100_chars(self):
        issues = validate_danmaku_list([_dm("a" * 100)])
        assert len(issues) == 0

    def test_under_100_chars(self):
        issues = validate_danmaku_list([_dm("短弹幕")])
        assert len(issues) == 0


class TestTimestampCheck:
    """时间戳超出视频时长"""

    def test_exceeds_duration(self):
        issues = validate_danmaku_list([_dm("test", progress=5000)], video_duration_ms=3000)
        assert len(issues) == 1
        assert "时长" in issues[0]['reason']

    def test_within_duration(self):
        issues = validate_danmaku_list([_dm("test", progress=3000)], video_duration_ms=5000)
        assert len(issues) == 0

    def test_negative_duration_skips_check(self):
        """video_duration_ms <= 0 时跳过检查"""
        issues = validate_danmaku_list([_dm("test", progress=999999)], video_duration_ms=-1)
        assert len(issues) == 0


class TestForbiddenSymbols:
    """特殊符号检查"""

    @pytest.mark.parametrize("symbol", list(FORBIDDEN_SYMBOLS))
    def test_each_forbidden_symbol(self, symbol: str):
        issues = validate_danmaku_list([_dm(f"包含{symbol}的弹幕")])
        assert len(issues) == 1
        assert "禁用符号" in issues[0]['reason']

    def test_no_forbidden_symbol(self):
        issues = validate_danmaku_list([_dm("安全弹幕")])
        assert len(issues) == 0


class TestCustomKeywords:
    """自定义关键词过滤"""

    def test_keyword_match(self):
        config = ValidationConfig(enabled=True, blocked_keywords=["广告", "加群"])
        issues = validate_danmaku_list([_dm("快来加群吧")], validation_config=config)
        assert len(issues) == 1
        assert "加群" in issues[0]['reason']

    def test_keyword_case_insensitive(self):
        config = ValidationConfig(enabled=True, blocked_keywords=["abc"])
        issues = validate_danmaku_list([_dm("ABCdef")], validation_config=config)
        assert len(issues) == 1

    def test_multiple_keywords(self):
        config = ValidationConfig(enabled=True, blocked_keywords=["广告", "加群"])
        issues = validate_danmaku_list([_dm("广告加群")], validation_config=config)
        assert len(issues) == 1
        assert "广告" in issues[0]['reason']
        assert "加群" in issues[0]['reason']

    def test_disabled_custom_rules(self):
        config = ValidationConfig(enabled=False, blocked_keywords=["广告"])
        issues = validate_danmaku_list([_dm("广告弹幕")], validation_config=config)
        assert len(issues) == 0

    def test_empty_keyword_list(self):
        config = ValidationConfig(enabled=True, blocked_keywords=[])
        issues = validate_danmaku_list([_dm("正常弹幕")], validation_config=config)
        assert len(issues) == 0

    def test_empty_keyword_string_ignored(self):
        """空字符串关键词不应匹配"""
        config = ValidationConfig(enabled=True, blocked_keywords=[""])
        issues = validate_danmaku_list([_dm("任何弹幕")], validation_config=config)
        assert len(issues) == 0


class TestMultipleIssues:
    """单条弹幕多个问题"""

    def test_multiple_reasons_joined(self):
        dm = _dm("a" * 101 + "\\n" + "☢")
        issues = validate_danmaku_list([dm])
        assert len(issues) == 1
        reason = issues[0]['reason']
        assert "换行符" in reason
        assert "100" in reason
        assert "禁用符号" in reason

    def test_original_index_preserved(self):
        dms = [_dm("正常"), _dm("a" * 101), _dm("正常")]
        issues = validate_danmaku_list(dms)
        assert len(issues) == 1
        assert issues[0]['original_index'] == 1


class TestIsValidFlag:
    """is_valid 标记回填"""

    def test_valid_danmaku_flag_set_true(self):
        dm = _dm("正常弹幕")
        validate_danmaku_list([dm])
        assert dm.is_valid is True

    def test_invalid_danmaku_flag_set_false(self):
        dm = _dm("a" * 101)
        validate_danmaku_list([dm])
        assert dm.is_valid is False


class TestEdgeCases:
    """边界场景"""

    def test_empty_list(self):
        issues = validate_danmaku_list([])
        assert issues == []

    def test_no_config(self):
        issues = validate_danmaku_list([_dm("test")], validation_config=None)
        assert issues == []

    def test_all_valid(self):
        dms = [_dm("弹幕1"), _dm("弹幕2"), _dm("弹幕3")]
        issues = validate_danmaku_list(dms)
        assert issues == []

    def test_all_invalid(self):
        dms = [_dm("a" * 101), _dm("b" * 102)]
        issues = validate_danmaku_list(dms)
        assert len(issues) == 2
