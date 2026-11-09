"""UI 层主题基础设施

负责系统外观检测、调色板映射与全局样式表渲染。
由 MainWindow 持有，通过设置页的 themeApplied 信号驱动。
"""

import logging
from dataclasses import dataclass
from typing import ClassVar

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.config.theme_config import ThemeMode
from danmaku_sender.utils.file_utils import read_json

from .icons import SvgIcon

logger = logging.getLogger(__name__)

THEMES_DIR = AppInfo.Paths.ASSETS / "themes"
QSS_PATH = AppInfo.Paths.ASSETS / "qss" / "style.qss"


# QPalette.ColorRole 到颜色来源的映射：取值为 Palette 的属性名，
# 或以 # 开头的颜色字面量。须覆盖 Qt 全部 ColorRole，未覆盖的角色会被 Qt 回退为系统默认值。
ROLE_SOURCES: dict[QPalette.ColorRole, str] = {
    QPalette.ColorRole.Window: "SolidBackgroundFillColorTertiary",
    QPalette.ColorRole.WindowText: "TextFillColorPrimary",
    QPalette.ColorRole.Base: "ControlFillColorDefault",
    QPalette.ColorRole.AlternateBase: "CardBackgroundFillColorSecondary",
    QPalette.ColorRole.Text: "TextFillColorPrimary",
    QPalette.ColorRole.Button: "ControlFillColorSecondary",
    QPalette.ColorRole.ButtonText: "TextFillColorPrimary",
    QPalette.ColorRole.BrightText: "AccentFillColorDefault",
    QPalette.ColorRole.Highlight: "AccentFillColorDefault",
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.ToolTipBase: "CardBackgroundFillColorDefault",
    QPalette.ColorRole.ToolTipText: "TextFillColorPrimary",
    QPalette.ColorRole.PlaceholderText: "TextFillColorSecondary",
    QPalette.ColorRole.Link: "AccentFillColorDefault",
    QPalette.ColorRole.LinkVisited: "AccentFillColorDefault",
    QPalette.ColorRole.Accent: "AccentFillColorDefault",
    # Light / Midlight 承载控件填充阶梯的悬停与按压档。
    # Mid / Dark / Shadow 服务于描边：Dark 为立体描边的强端，Shadow 为弱端与分隔线。
    QPalette.ColorRole.Light: "SubtleFillColorSecondary",
    QPalette.ColorRole.Midlight: "SubtleFillColorTertiary",
    QPalette.ColorRole.Mid: "ControlStrokeColorDefault",
    QPalette.ColorRole.Dark: "ControlStrongStrokeColorDefault",
    QPalette.ColorRole.Shadow: "DividerStrokeColorDefault",
}

# setColor(role, color) 会同时写入 Disabled 组，使禁用态文字与正常态同色，
# 覆盖 Qt 原生的置灰效果。这些文字角色须在 Disabled 组另行赋弱化色（见 to_qpalette）。
DISABLED_TEXT_ROLES: tuple[QPalette.ColorRole, ...] = (
    QPalette.ColorRole.WindowText,
    QPalette.ColorRole.Text,
    QPalette.ColorRole.ButtonText,
)


@dataclass(frozen=True)
class Palette:
    """系统色彩语义 Token（不可变），字段名即 WinUI 3 ThemeResource 名。"""
    SolidBackgroundFillColorBase: str
    SolidBackgroundFillColorSecondary: str
    SolidBackgroundFillColorTertiary: str
    CardBackgroundFillColorDefault: str
    CardBackgroundFillColorSecondary: str
    LayerFillColorDefault: str
    ControlFillColorDefault: str
    ControlFillColorSecondary: str
    SubtleFillColorSecondary: str
    SubtleFillColorTertiary: str
    ControlStrokeColorDefault: str
    ControlStrongStrokeColorDefault: str
    DividerStrokeColorDefault: str
    CardStrokeColorDefault: str
    TextFillColorPrimary: str
    TextFillColorSecondary: str
    AccentFillColorDefault: str
    SystemFillColorSuccess: str
    SystemFillColorCaution: str
    SystemFillColorAttention: str
    SystemFillColorAttentionBackground: str

    def to_qpalette(self) -> QPalette:
        """映射为 Qt 原生调色板，供未被 QSS 覆盖的控件使用。

        按 :data:`ROLE_SOURCES` 设置全部 ColorRole。
        未设置的角色会被 Qt 回退为系统默认值，因此映射表必须保持完整。

        Returns:
            填充了全部 ColorRole 的调色板。
        """
        p = QPalette()
        for role, source in ROLE_SOURCES.items():
            color = source if source.startswith("#") else getattr(self, source)
            p.setColor(role, QColor(color))
        # 覆写 Disabled 组文字色，恢复禁用态的置灰效果（见 DISABLED_TEXT_ROLES）
        for role in DISABLED_TEXT_ROLES:
            p.setColor(QPalette.ColorGroup.Disabled, role, QColor(self.TextFillColorSecondary))
        return p


class ThemeService(QObject):
    """主题渲染服务（隶属 UI 层，由 MainWindow 持有）。

    Attributes:
        tokens (ClassVar[Palette]): 当前主题 token，构造与渲染时更新；
            供 Card.surface_color 等按名取色。
    """

    themeChanged = Signal(Palette)

    tokens: ClassVar[Palette]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.light_palette = self._load_palette("light")
        self.dark_palette = self._load_palette("dark")
        self.current_palette: Palette = self.light_palette
        ThemeService.tokens = self.current_palette
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
        """判定深浅色并应用主题（唯一的渲染入口）。"""
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
        """同步更新 QPalette 与 QSS 样式表，使两者的渲染变更同时生效。"""
        self.current_palette = palette
        # 先更新 tokens 再 setPalette：PaletteChange 触发的表面重算须取到新值
        ThemeService.tokens = palette

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return

        # 1. 注入原生 QPalette（必须在 setStyleSheet 之前）
        app.setPalette(palette.to_qpalette())

        # 2. 清空图标渲染缓存，后续 SvgIcon 常量访问将以新调色板颜色重新渲染
        SvgIcon.clear_cache()

        # 3. 编译并注入全局 QSS（用 str.replace 避免 CSS 大括号冲突）
        if QSS_PATH.exists():
            try:
                css = QSS_PATH.read_text(encoding="utf-8")
                for token, color in {
                    "{SolidBackgroundFillColorBase}": palette.SolidBackgroundFillColorBase,
                    "{SolidBackgroundFillColorSecondary}": palette.SolidBackgroundFillColorSecondary,
                    "{SolidBackgroundFillColorTertiary}": palette.SolidBackgroundFillColorTertiary,
                    "{CardBackgroundFillColorDefault}": palette.CardBackgroundFillColorDefault,
                    "{CardBackgroundFillColorSecondary}": palette.CardBackgroundFillColorSecondary,
                    "{LayerFillColorDefault}": palette.LayerFillColorDefault,
                    "{ControlFillColorDefault}": palette.ControlFillColorDefault,
                    "{ControlFillColorSecondary}": palette.ControlFillColorSecondary,
                    "{SubtleFillColorSecondary}": palette.SubtleFillColorSecondary,
                    "{SubtleFillColorTertiary}": palette.SubtleFillColorTertiary,
                    "{ControlStrokeColorDefault}": palette.ControlStrokeColorDefault,
                    "{ControlStrongStrokeColorDefault}": palette.ControlStrongStrokeColorDefault,
                    "{DividerStrokeColorDefault}": palette.DividerStrokeColorDefault,
                    "{CardStrokeColorDefault}": palette.CardStrokeColorDefault,
                    "{TextFillColorPrimary}": palette.TextFillColorPrimary,
                    "{TextFillColorSecondary}": palette.TextFillColorSecondary,
                    "{AccentFillColorDefault}": palette.AccentFillColorDefault,
                    "{SystemFillColorSuccess}": palette.SystemFillColorSuccess,
                    "{SystemFillColorCaution}": palette.SystemFillColorCaution,
                    "{SystemFillColorAttention}": palette.SystemFillColorAttention,
                    "{SystemFillColorAttentionBackground}": palette.SystemFillColorAttentionBackground,
                }.items():
                    css = css.replace(token, color)
                app.setStyleSheet(css)
            except Exception as e:
                logger.error(f"加载样式表失败: {e}", exc_info=True)

        # 4. 广播主题变动通知
        self.themeChanged.emit(palette)
        logger.info(f"全局主题已生效: {self._current_mode.value}")

    @Slot(Qt.ColorScheme)
    def _on_system_scheme_changed(self, scheme: Qt.ColorScheme):
        """系统主题变化时，仅在 SYSTEM 模式下响应"""
        if self._current_mode == ThemeMode.SYSTEM:
            self.apply_theme(ThemeMode.SYSTEM)
