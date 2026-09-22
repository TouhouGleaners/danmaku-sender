from enum import Enum

from pydantic import BaseModel, ConfigDict


class ThemeMode(Enum):
    """主题模式"""
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ThemeConfig(BaseModel):
    """主题配置"""
    model_config = ConfigDict(validate_assignment=True)

    theme_mode: ThemeMode = ThemeMode.SYSTEM
