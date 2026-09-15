from enum import Enum

from pydantic import ConfigDict

from danmaku_sender.types.models.evented_model import EventedModel


class ThemeMode(Enum):
    """主题模式"""
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ThemeConfig(EventedModel):
    """主题配置"""
    model_config = ConfigDict(validate_assignment=True)

    theme_mode: ThemeMode = ThemeMode.SYSTEM
