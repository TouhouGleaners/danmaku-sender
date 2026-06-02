"""Pydantic 配置模型单元测试 — SenderConfig, MonitorConfig, ValidationConfig, VideoState"""
import pytest
from pydantic import ValidationError
from danmaku_sender.core.models.danmaku import Danmaku
from danmaku_sender.core.state import SenderConfig, MonitorConfig, ValidationConfig, VideoState


class TestSenderConfig:
    """SenderConfig Pydantic 模型"""

    def test_default_values(self):
        cfg = SenderConfig()
        assert cfg.min_delay == 8.0
        assert cfg.max_delay == 8.5
        assert cfg.burst_size == 3
        assert cfg.rest_min == 40.0
        assert cfg.rest_max == 45.0
        assert cfg.stop_after_count == 0
        assert cfg.stop_after_time == 0
        assert cfg.prevent_sleep is True
        assert cfg.use_system_proxy is True
        assert cfg.skip_sent is True

    def test_valid_custom_values(self):
        cfg = SenderConfig(min_delay=5.0, max_delay=10.0)
        assert cfg.min_delay == 5.0
        assert cfg.max_delay == 10.0

    def test_min_delay_too_small(self):
        with pytest.raises(ValidationError):
            SenderConfig(min_delay=0.0)

    def test_max_delay_too_small(self):
        with pytest.raises(ValidationError):
            SenderConfig(max_delay=0.0)

    def test_burst_size_negative(self):
        with pytest.raises(ValidationError):
            SenderConfig(burst_size=-1)

    def test_min_greater_than_max_raises(self):
        with pytest.raises(ValidationError, match="最小延迟不能大于最大延迟"):
            SenderConfig(min_delay=10.0, max_delay=5.0)

    def test_rest_min_greater_than_rest_max_raises(self):
        with pytest.raises(ValidationError, match="爆发休息的最小值不能大于最大值"):
            SenderConfig(burst_size=3, rest_min=50.0, rest_max=30.0)

    def test_rest_min_greater_than_rest_max_burst_size_1_ok(self):
        """burst_size <= 1 时不校验 rest_min/rest_max"""
        cfg = SenderConfig(burst_size=1, rest_min=50.0, rest_max=30.0)
        assert cfg.rest_min == 50.0

    def test_validate_assignment(self):
        """赋值时也应触发校验"""
        cfg = SenderConfig()
        with pytest.raises(ValidationError):
            cfg.min_delay = 999.0  # > max_delay=8.5


class TestMonitorConfig:
    def test_default_values(self):
        cfg = MonitorConfig()
        assert cfg.refresh_interval == 60
        assert cfg.prevent_sleep is True
        assert cfg.use_system_proxy is True

    def test_refresh_interval_too_small(self):
        with pytest.raises(ValidationError):
            MonitorConfig(refresh_interval=5)

    def test_refresh_interval_minimum(self):
        cfg = MonitorConfig(refresh_interval=10)
        assert cfg.refresh_interval == 10


class TestValidationConfig:
    def test_default_values(self):
        cfg = ValidationConfig()
        assert cfg.enabled is True
        assert cfg.blocked_keywords == []

    def test_custom_keywords(self):
        cfg = ValidationConfig(blocked_keywords=["广告", "加群"])
        assert cfg.blocked_keywords == ["广告", "加群"]

    def test_disabled(self):
        cfg = ValidationConfig(enabled=False)
        assert cfg.enabled is False


class TestVideoState:
    def test_default_state(self):
        vs = VideoState()
        assert vs.bvid == ""
        assert vs.selected_cid is None
        assert vs.loaded_danmakus == []
        assert vs.is_ready_to_send is False
        assert vs.danmaku_count == 0

    def test_ready_to_send_all_set(self):
        vs = VideoState(
            bvid="BV1xx411c7mD",
            selected_cid=1001,
            loaded_danmakus=[Danmaku(msg="t", progress=0)]
        )
        assert vs.is_ready_to_send is True

    def test_not_ready_missing_bvid(self):
        vs = VideoState(selected_cid=1001, loaded_danmakus=[Danmaku(msg="t", progress=0)])
        assert vs.is_ready_to_send is False

    def test_not_ready_missing_cid(self):
        vs = VideoState(bvid="BV1xx411c7mD", loaded_danmakus=[Danmaku(msg="t", progress=0)])
        assert vs.is_ready_to_send is False

    def test_not_ready_empty_danmakus(self):
        vs = VideoState(bvid="BV1xx411c7mD", selected_cid=1001)
        assert vs.is_ready_to_send is False

    def test_danmaku_count(self):
        dms = [Danmaku(msg=f"d{i}", progress=i * 1000) for i in range(5)]
        vs = VideoState(loaded_danmakus=dms)
        assert vs.danmaku_count == 5
