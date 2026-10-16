import sys
from enum import Enum

from .base import AtomicModel


class ThemeMode(Enum):
    """主题模式"""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class FontChoice(Enum):
    """界面字体档位。

    Attributes:
        MISANS (str): 随附的 MiSans，渲染策略经校准。
        YAHEI (str): 微软雅黑，细体与粗体分别取 hinting。
        SYSTEM (str): 系统默认字体，渲染交给平台。
    """

    MISANS = "misans"
    YAHEI = "yahei"
    SYSTEM = "system"


# Windows 上系统默认字体的中文渲染需要明确的中文字体，故默认钉在微软雅黑；
# 其余平台的系统默认字体即为首选，跟随系统即可。
DEFAULT_FONT = FontChoice.YAHEI if sys.platform == "win32" else FontChoice.SYSTEM


class ThemeConfig(AtomicModel):
    """主题配置

    Attributes:
        theme_mode (ThemeMode): 主题模式。
        font_name (FontChoice): 界面字体档位。
    """

    theme_mode: ThemeMode = ThemeMode.SYSTEM
    font_name: FontChoice = DEFAULT_FONT
