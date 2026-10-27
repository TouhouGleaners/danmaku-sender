"""ConfigStorage 配置加载与保存"""
import json

from danmaku_sender.config import Settings
from danmaku_sender.config.theme_config import ThemeMode
from danmaku_sender.infra.storage import config_storage as cs_module
from danmaku_sender.infra.storage.config_storage import ConfigStorage
from danmaku_sender.types.models.common import SendMode


class TestConfigLoad:
    def test_load_without_sender_uses_defaults(self, tmp_path, monkeypatch):
        """缺 sender 段时整块回退默认值。"""
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"theme": {"theme_mode": "dark"}}), encoding="utf-8")
        monkeypatch.setattr(cs_module, "CONFIG_PATH", path)

        settings = Settings()
        ConfigStorage().load(settings)

        assert settings.sender_config.pacing.min_delay == 9.5
        assert settings.sender_config.queue.allow_duplicates is False

    def test_load_reads_nested_sender_section(self, tmp_path, monkeypatch):
        """sender 段的 pacing / queue 子结构应被读取。"""
        data = {
            "sender": {
                "mode": "send_only",
                "pacing": {"min_delay": 3.0, "max_delay": 9.0},
                "queue": {"allow_duplicates": True, "delay_between_tasks": 12.5},
            },
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(cs_module, "CONFIG_PATH", path)

        settings = Settings()
        ConfigStorage().load(settings)

        assert settings.sender_config.mode is SendMode.SEND_ONLY
        assert (settings.sender_config.pacing.min_delay, settings.sender_config.pacing.max_delay) == (3.0, 9.0)
        assert settings.sender_config.queue.allow_duplicates is True
        assert settings.sender_config.queue.delay_between_tasks == 12.5

    def test_legacy_flat_sender_is_not_migrated(self, tmp_path, monkeypatch):
        """旧格式（sender 段平铺字段 + send_policy 段）不做迁移，整块回默认值。

        默认值即实测稳定节奏，回退落在安全一侧；需要保留的取值在设置页改回。
        """
        legacy = {
            "sender": {"min_delay": 3.0, "max_delay": 9.0},
            "send_policy": {"allow_duplicates": True, "delay_between_tasks": 12.5},
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        monkeypatch.setattr(cs_module, "CONFIG_PATH", path)

        settings = Settings()
        ConfigStorage().load(settings)

        assert settings.sender_config.pacing.min_delay == 9.5
        assert settings.sender_config.queue.delay_between_tasks == 30.0
        assert settings.sender_config.queue.allow_duplicates is False


class TestConfigSave:
    def test_save_roundtrips_enum_fields(self, tmp_path, monkeypatch):
        """保存后重新加载，枚举字段须原样回来。

        save 对序列化异常只记日志不抛出，落盘失败在重启前不可见。
        """
        path = tmp_path / "config.json"
        monkeypatch.setattr(cs_module, "CONFIG_PATH", path)

        settings = Settings()
        settings.sender_config.mode = SendMode.SEND_ONLY
        settings.theme_config.theme_mode = ThemeMode.DARK
        ConfigStorage().save(settings)

        restored = Settings()
        ConfigStorage().load(restored)

        assert restored.sender_config.mode is SendMode.SEND_ONLY
        assert restored.theme_config.theme_mode is ThemeMode.DARK

    def test_save_writes_nested_shape(self, tmp_path, monkeypatch):
        """落盘写的是 sender 下的 pacing / queue，不再有 send_policy 段。"""
        path = tmp_path / "config.json"
        monkeypatch.setattr(cs_module, "CONFIG_PATH", path)

        ConfigStorage().save(Settings())
        data = json.loads(path.read_text(encoding="utf-8"))

        assert set(data["sender"]) == {"mode", "pacing", "queue"}
        assert set(data["sender"]["pacing"]) == {
            "min_delay", "max_delay", "burst_enabled", "burst_size", "rest_min", "rest_max",
        }
        assert set(data["sender"]["queue"]) == {"allow_duplicates", "delay_between_tasks"}
        assert "send_policy" not in data
