import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from danmaku_sender.config.theme_config import ThemeConfig, ThemeMode

logger = logging.getLogger(__name__)


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

    def to_qpalette(self) -> QPalette:
        """桥接到 Qt QPalette，让原生控件（QComboBox、QSpinBox 等）跟随主题"""
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window, QColor(self.bg_base))
        p.setColor(QPalette.ColorRole.WindowText, QColor(self.text_main))
        p.setColor(QPalette.ColorRole.Base, QColor(self.bg_surface))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor(self.bg_base))
        p.setColor(QPalette.ColorRole.ToolTipBase, QColor(self.bg_surface))
        p.setColor(QPalette.ColorRole.ToolTipText, QColor(self.text_main))
        p.setColor(QPalette.ColorRole.Text, QColor(self.text_main))
        p.setColor(QPalette.ColorRole.Button, QColor(self.bg_hover))
        p.setColor(QPalette.ColorRole.ButtonText, QColor(self.text_main))
        p.setColor(QPalette.ColorRole.BrightText, QColor(self.primary))
        p.setColor(QPalette.ColorRole.Highlight, QColor(self.primary))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        return p


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
        self._theme_mode = ThemeMode.SYSTEM

        # 监听系统级别的主题切换
        if hasattr(QGuiApplication, "styleHints"):
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)

    def current(self) -> Palette:
        return self._current_palette

    def init_theme(self, mode: ThemeMode = ThemeMode.SYSTEM):
        """初始化主题"""
        self._theme_mode = mode
        self._apply_mode()

    def bind_config(self, theme_config: ThemeConfig):
        """订阅 ThemeConfig 的变更（由 Runtime.bootstrap 调用）"""
        theme_config.subscribe("theme_mode", lambda v: self.set_theme_mode(v))

    def set_theme_mode(self, mode: ThemeMode):
        """设置主题模式（system / light / dark）"""
        if self._theme_mode == mode:
            return
        self._theme_mode = mode
        logger.info(f"主题模式已切换: {mode.value}")
        self._apply_mode()

    def _apply_mode(self):
        """根据当前模式应用对应调色板"""
        match self._theme_mode:
            case ThemeMode.SYSTEM:
                if hasattr(QGuiApplication, "styleHints"):
                    scheme = QGuiApplication.styleHints().colorScheme()
                    is_dark = scheme == Qt.ColorScheme.Dark
                    self._set_theme(self.DARK if is_dark else self.LIGHT)
                else:
                    self._set_theme(self.LIGHT)
            case ThemeMode.DARK:
                self._set_theme(self.DARK)
            case ThemeMode.LIGHT:
                self._set_theme(self.LIGHT)

    @Slot(Qt.ColorScheme)
    def _on_system_theme_changed(self, scheme: Qt.ColorScheme):
        """系统主题变化时，仅在 system 模式下响应"""
        if self._theme_mode == ThemeMode.SYSTEM:
            is_dark = scheme == Qt.ColorScheme.Dark
            self._set_theme(self.DARK if is_dark else self.LIGHT)

    def _set_theme(self, palette: Palette):
        if self._current_palette != palette:
            self._current_palette = palette
            # 桥接 QPalette，让原生控件跟随主题
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.setPalette(palette.to_qpalette())
            self.themeChanged.emit(palette)