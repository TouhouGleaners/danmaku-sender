"""UI 层主题基础设施

负责系统外观嗅探、调色板映射与全局样式表渲染。
由 MainWindow 持有，通过 AppState.themeModeChanged 信号驱动。
"""

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.config.theme_config import ThemeMode
from danmaku_sender.utils.file_utils import read_json

logger = logging.getLogger(__name__)

THEMES_DIR = AppInfo.Paths.ASSETS / "themes"
QSS_PATH = AppInfo.Paths.ASSETS / "qss" / "style.qss"


@dataclass(frozen=True)
class Palette:
    """系统色彩语义 Token（不可变）"""
    bg_base: str
    bg_surface: str
    bg_hover: str
    border_color: str
    text_main: str
    text_secondary: str
    primary: str
    success: str
    danger: str
    danger_bg: str

    def to_qpalette(self) -> QPalette:
        """映射为 Qt 原生调色板，让未被 QSS 覆盖的原生部件也能协调显示"""
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


class ThemeService(QObject):
    """主题渲染服务（隶属 UI 层，由 MainWindow 持有）"""

    themeChanged = Signal(Palette)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.light_palette = self._load_palette("light")
        self.dark_palette = self._load_palette("dark")
        self.current_palette: Palette = self.light_palette
        self._current_mode = ThemeMode.SYSTEM

        # 监听操作系统层面的深浅色切换
        hints = QGuiApplication.styleHints() if hasattr(QGuiApplication, "styleHints") else None
        if hints:
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)

    @staticmethod
    def _load_palette(name: str) -> Palette:
        """从 assets/themes/{name}.json 加载调色板"""
        path = THEMES_DIR / f"{name}.json"
        data = read_json(path)
        if data is None:
            raise FileNotFoundError(f"主题文件缺失或损坏: {path}")
        if not isinstance(data, dict) or set(data) != set(Palette.__annotations__):
            raise ValueError(f"主题文件结构非法: {path}")
        try:
            return Palette(**data)
        except TypeError as e:
            raise ValueError(f"主题文件结构非法: {path}") from e

    def apply_theme(self, mode: ThemeMode) -> None:
        """计算环境并应用主题（唯一的渲染入口）"""
        self._current_mode = mode
        is_dark = False

        if mode == ThemeMode.SYSTEM:
            hints = QGuiApplication.styleHints() if hasattr(QGuiApplication, "styleHints") else None
            if hints:
                is_dark = hints.colorScheme() == Qt.ColorScheme.Dark
        else:
            is_dark = mode == ThemeMode.DARK

        palette = self.dark_palette if is_dark else self.light_palette
        self._render(palette)

    def _render(self, palette: Palette) -> None:
        """同时更新 QPalette 与 QSS 样式表，保证渲染副作用原子生效"""
        self.current_palette = palette

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return

        # 1. 注入原生 QPalette（必须在 setStyleSheet 之前）
        app.setPalette(palette.to_qpalette())

        # 2. 编译并注入全局 QSS（用 str.replace 避免 CSS 大括号冲突）
        if QSS_PATH.exists():
            try:
                css = QSS_PATH.read_text(encoding="utf-8")
                for token, color in {
                    "{bg_base}": palette.bg_base,
                    "{bg_surface}": palette.bg_surface,
                    "{bg_hover}": palette.bg_hover,
                    "{border_color}": palette.border_color,
                    "{text_main}": palette.text_main,
                    "{text_secondary}": palette.text_secondary,
                    "{primary}": palette.primary,
                    "{success}": palette.success,
                    "{danger}": palette.danger,
                    "{danger_bg}": palette.danger_bg,
                }.items():
                    css = css.replace(token, color)
                app.setStyleSheet(css)
            except Exception as e:
                logger.error(f"加载样式表失败: {e}", exc_info=True)

        # 3. 广播主题变动通知
        self.themeChanged.emit(palette)
        logger.info(f"全局主题已生效: {self._current_mode.value}")

    @Slot(Qt.ColorScheme)
    def _on_system_scheme_changed(self, scheme: Qt.ColorScheme):
        """系统主题变化时，仅在 SYSTEM 模式下响应"""
        if self._current_mode == ThemeMode.SYSTEM:
            self.apply_theme(ThemeMode.SYSTEM)
