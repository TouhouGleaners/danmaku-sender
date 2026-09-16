import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.config.theme_config import ThemeConfig, ThemeMode
from danmaku_sender.utils.file_utils import read_json

logger = logging.getLogger(__name__)

THEMES_DIR = AppInfo.Paths.ASSETS / "themes"


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

    @classmethod
    def load_palette(cls, name: str) -> Palette:
        """从 assets/themes/{name}.json 加载调色板"""
        path = THEMES_DIR / f"{name}.json"
        data = read_json(path)
        if data is None:
            raise FileNotFoundError(f"主题文件缺失或损坏: {path}")
        if not isinstance(data, dict) or set(data) != set(Palette.__annotations__):
            raise FileNotFoundError(f"主题文件结构非法: {path}")
        try:
            return Palette(**data)
        except TypeError as e:
            raise FileNotFoundError(f"主题文件结构非法: {path}") from e

    @classmethod
    def instance(cls) -> 'ThemeManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.light = self.load_palette("light")
        self.dark = self.load_palette("dark")
        self.current_palette = self.light
        self.theme_mode = ThemeMode.SYSTEM

        # 监听系统级别的主题切换
        if hasattr(QGuiApplication, "styleHints"):
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)

    def current(self) -> Palette:
        return self.current_palette

    def init_theme(self, mode: ThemeMode = ThemeMode.SYSTEM):
        """初始化主题"""
        self.theme_mode = mode
        self._apply_mode()

    def bind_config(self, theme_config: ThemeConfig):
        """订阅 ThemeConfig 的变更（由 Runtime.bootstrap 调用）"""
        theme_config.subscribe("theme_mode", lambda v: self.set_theme_mode(v))

    def set_theme_mode(self, mode: ThemeMode):
        """设置主题模式（system / light / dark）"""
        if self.theme_mode == mode:
            return
        self.theme_mode = mode
        logger.info(f"主题模式已切换: {mode.value}")
        self._apply_mode()

    def _apply_mode(self):
        """根据当前模式应用对应调色板"""
        match self.theme_mode:
            case ThemeMode.SYSTEM:
                if hasattr(QGuiApplication, "styleHints"):
                    scheme = QGuiApplication.styleHints().colorScheme()
                    is_dark = scheme == Qt.ColorScheme.Dark
                    self._set_theme(self.dark if is_dark else self.light)
                else:
                    self._set_theme(self.light)
            case ThemeMode.DARK:
                self._set_theme(self.dark)
            case ThemeMode.LIGHT:
                self._set_theme(self.light)

    @Slot(Qt.ColorScheme)
    def _on_system_theme_changed(self, scheme: Qt.ColorScheme):
        """系统主题变化时，仅在 system 模式下响应"""
        if self.theme_mode == ThemeMode.SYSTEM:
            is_dark = scheme == Qt.ColorScheme.Dark
            self._set_theme(self.dark if is_dark else self.light)

    def _set_theme(self, palette: Palette):
        if self.current_palette != palette:
            self.current_palette = palette
            # 桥接 QPalette，让原生控件跟随主题
            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.setPalette(palette.to_qpalette())
            self.themeChanged.emit(palette)
