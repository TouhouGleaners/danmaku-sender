from enum import Enum

from .base import AtomicModel


class ThemeMode(Enum):
    """主题模式"""
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ThemeConfig(AtomicModel):
    """主题配置

    Attributes:
        theme_mode: 主题模式。
        font_name: 字体档位，取值见 ``ui.framework.fonts`` 的档位表。
    """

    theme_mode: ThemeMode = ThemeMode.SYSTEM
    font_name: str = "misans"
