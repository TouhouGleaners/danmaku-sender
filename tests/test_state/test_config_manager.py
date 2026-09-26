"""ConfigManager 配置加载与保存"""
import json

from danmaku_sender.runtime.managers import config_manager as cm_module
from danmaku_sender.runtime.managers.config_manager import ConfigManager
from danmaku_sender.runtime.state.app_state import AppState


class TestConfigLoad:
    def test_load_without_send_policy_uses_defaults(self, tmp_path, monkeypatch):
        """旧格式 config.json（缺 send_policy 段）回退默认值，不做迁移。

        这是有意的取舍：配置可容忍丢弃，故 skip_sent 等策略项
        不从旧 sender 段里搬，直接用默认值。
        """
        legacy = {"sender": {"min_delay": 3.0, "max_delay": 9.0, "skip_sent": False}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        monkeypatch.setattr(cm_module, "CONFIG_PATH", path)

        state = AppState()
        ConfigManager().load(state)

        assert (state.sender_config.min_delay, state.sender_config.max_delay) == (3.0, 9.0)
        assert state.send_policy.skip_sent is True, "缺 send_policy 段应回默认值"

    def test_load_reads_send_policy_section(self, tmp_path, monkeypatch):
        """新格式 config.json 的 send_policy 段应被读取。"""
        data = {
            "sender": {"min_delay": 3.0, "max_delay": 9.0},
            "send_policy": {
                "skip_sent": False,
                "delay_between_tasks": 12.5,
                "stop_after_count": 7,
                "stop_after_time": 0,
            },
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(cm_module, "CONFIG_PATH", path)

        state = AppState()
        ConfigManager().load(state)

        assert state.send_policy.skip_sent is False
        assert state.send_policy.delay_between_tasks == 12.5
        assert state.send_policy.stop_after_count == 7
