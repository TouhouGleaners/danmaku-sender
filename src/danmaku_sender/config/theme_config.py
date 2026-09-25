from enum import Enum

from .base import AtomicModel


class ThemeMode(Enum):
    """主题模式"""
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ThemeConfig(AtomicModel):
    """主题配置"""

    theme_mode: ThemeMode = ThemeMode.SYSTEM
