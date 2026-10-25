"""ConfigStorage 配置加载与保存"""
import json

from danmaku_sender.config import Settings
from danmaku_sender.config.theme_config import ThemeMode
from danmaku_sender.infra.storage import config_storage as cs_module
from danmaku_sender.infra.storage.config_storage import ConfigStorage
from danmaku_sender.types.models.common import SendMode


class TestConfigLoad:
    def test_load_without_send_policy_uses_defaults(self, tmp_path, monkeypatch):
        """旧格式 config.json（缺 send_policy 段）回退默认值，不做迁移。

        这是有意的取舍：配置可容忍丢弃，故 allow_duplicates 等策略项不从旧 sender 段里搬，直接用默认值。
        """
        legacy = {"sender": {"min_delay": 3.0, "max_delay": 9.0, "skip_sent": False}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        monkeypatch.setattr(cs_module, "CONFIG_PATH", path)

        settings = Settings()
        ConfigStorage().load(settings)

        assert (settings.sender_config.min_delay, settings.sender_config.max_delay) == (3.0, 9.0)
        assert settings.send_policy.allow_duplicates is False, "缺 send_policy 段应回默认值"

    def test_load_reads_send_policy_section(self, tmp_path, monkeypatch):
        """新格式 config.json 的 send_policy 段应被读取。"""
        data = {
            "sender": {"min_delay": 3.0, "max_delay": 9.0},
            "send_policy": {
                "allow_duplicates": True,
                "delay_between_tasks": 12.5,
                "stop_after_count": 7,
                "stop_after_time": 0,
            },
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(cs_module, "CONFIG_PATH", path)

        settings = Settings()
        ConfigStorage().load(settings)

        assert settings.send_policy.allow_duplicates is True
        assert settings.send_policy.delay_between_tasks == 12.5
        assert settings.send_policy.stop_after_count == 7


class TestConfigSave:
    def test_save_roundtrips_enum_fields(self, tmp_path, monkeypatch):
        """保存后重新加载，枚举字段须原样回来。

        save 对序列化异常只记日志不抛出，落盘失败在重启前不可见。
        """
        path = tmp_path / "config.json"
        monkeypatch.setattr(cs_module, "CONFIG_PATH", path)

        settings = Settings()
        settings.send_policy.mode = SendMode.SEND_ONLY
        settings.theme_config.theme_mode = ThemeMode.DARK
        ConfigStorage().save(settings)

        restored = Settings()
        ConfigStorage().load(restored)

        assert restored.send_policy.mode is SendMode.SEND_ONLY
        assert restored.theme_config.theme_mode is ThemeMode.DARK
