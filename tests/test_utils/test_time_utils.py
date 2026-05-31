"""time_utils 单元测试 — format_duration"""
from danmaku_sender.utils.time_utils import format_duration


class TestFormatDuration:
    """format_duration 的各种输入场景"""

    def test_zero(self):
        assert format_duration(0) == "00:00"

    def test_seconds_only(self):
        assert format_duration(45) == "00:45"

    def test_one_minute(self):
        assert format_duration(60) == "01:00"

    def test_minutes_and_seconds(self):
        assert format_duration(125) == "02:05"

    def test_one_hour(self):
        assert format_duration(3600) == "01:00:00"

    def test_hours_minutes_seconds(self):
        assert format_duration(3725) == "01:02:05"

    def test_large_value(self):
        assert format_duration(86399) == "23:59:59"  # 24h - 1s

    def test_none_returns_placeholder(self):
        assert format_duration(None) == "-:--:--"

    def test_negative_returns_placeholder(self):
        assert format_duration(-1) == "-:--:--"

    def test_negative_large(self):
        assert format_duration(-3600) == "-:--:--"

    def test_float_input(self):
        """浮点数应被截断为整数"""
        assert format_duration(65.7) == "01:05"

    def test_float_below_one(self):
        assert format_duration(0.9) == "00:00"

    def test_exactly_59_seconds(self):
        assert format_duration(59) == "00:59"

    def test_exactly_61_seconds(self):
        assert format_duration(61) == "01:01"
