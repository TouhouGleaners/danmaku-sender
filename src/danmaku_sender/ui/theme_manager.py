import logging
from dataclasses import dataclass

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt, QObject, Signal, Slot


logger = logging.getLogger("App.System.Theme")


@dataclass
class Palette:
    """双色调色板"""
    bg_base: str            # 最底层背景 (主窗口)
    bg_surface: str         # 表面背景 (侧边栏)
    bg_hover: str           # 悬停背景
    border_color: str       # 边框颜色
    text_main: str          # 主文本
    text_secondary: str     # 次文本
    primary: str            # 主色
    success: str            # 成功绿
    danger: str             # 危险红
    danger_bg: str          # 危险状态背景


class ThemeManager(QObject):
    """主题管理器 (单例)"""
    themeChanged = Signal(Palette)

    _instance = None

    # --- 浅色调色板 ---
    LIGHT = Palette(
        bg_base="#ffffff",
        bg_surface="#f8f9fa",
        bg_hover="#f1f3f5",
        border_color="#e1e4e8",
        text_main="#444d56",
        text_secondary="#7f8c8d",
        primary="#fb7299",
        success="#2ecc71",
        danger="#e74c3c",
        danger_bg="#fff0f0"
    )

    # --- 深色调色板 ---
    DARK = Palette(
        bg_base="#1e1e1e",
        bg_surface="#252526",
        bg_hover="#2d2d2d",
        border_color="#3e3e42",
        text_main="#cccccc",
        text_secondary="#858585",
        primary="#fb7299",
        success="#27ae60",
        danger="#e74c3c",
        danger_bg="#3a1c1c"
    )

    @classmethod
    def instance(cls) -> 'ThemeManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._current_palette = self.LIGHT

        # 监听系统级别的主题切换
        if hasattr(QGuiApplication, "styleHints"):
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)

    def current(self) -> Palette:
        return self._current_palette

    def init_theme(self):
        """初始化时获取系统当前主题"""
        if hasattr(QGuiApplication, "styleHints"):
            scheme = QGuiApplication.styleHints().colorScheme()
            is_dark = scheme == Qt.ColorScheme.Dark
            self._set_theme(self.DARK if is_dark else self.LIGHT)

    @Slot(Qt.ColorScheme)
    def _on_system_theme_changed(self, scheme: Qt.ColorScheme):
        is_dark = scheme == Qt.ColorScheme.Dark
        self._set_theme(self.DARK if is_dark else self.LIGHT)

    def _set_theme(self, palette: Palette):
        if self._current_palette != palette:
            self._current_palette = palette
            logger.info("🎨 系统深浅色模式改变，已热切换基础调色板。")
            self.themeChanged.emit(palette)