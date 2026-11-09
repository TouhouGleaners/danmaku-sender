"""UI 层主题基础设施

负责深浅色主题检测、全局 QPalette 映射与 QSS 样式表变量渲染。
由 MainWindow 统一持有生命周期，通过设置页的 themeApplied 信号触发变更。
"""

import dataclasses
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


# QPalette.ColorRole 到 Palette 属性的映射表。
# 覆盖 Qt 全部标准 ColorRole，防止未覆盖角色回退到不可控的系统默认色。
#
# 注意: Qt 原生 QPalette 缺乏现代 UI 系统的微层次（Subtle/Elevation）角色，
# 此处借用 Light/Midlight/Mid/Dark/Shadow 等角色承载 WinUI 3 的状态与描边色阶：
# - Light / Midlight: 承载控件悬停 (SubtleSecondary) 与按压 (SubtleTertiary) 填充
# - Mid / Dark / Shadow: 承载主描边 (ControlStroke)、强描边 (StrongStroke) 与分割线 (DividerStroke)
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
    QPalette.ColorRole.HighlightedText: "TextFillColorPrimary",
    QPalette.ColorRole.ToolTipBase: "CardBackgroundFillColorDefault",
    QPalette.ColorRole.ToolTipText: "TextFillColorPrimary",
    QPalette.ColorRole.PlaceholderText: "TextFillColorSecondary",
    QPalette.ColorRole.Link: "AccentFillColorDefault",
    QPalette.ColorRole.LinkVisited: "AccentFillColorDefault",
    QPalette.ColorRole.Accent: "AccentFillColorDefault",
    QPalette.ColorRole.Light: "SubtleFillColorSecondary",
    QPalette.ColorRole.Midlight: "SubtleFillColorTertiary",
    QPalette.ColorRole.Mid: "ControlStrokeColorDefault",
    QPalette.ColorRole.Dark: "ControlStrongStrokeColorDefault",
    QPalette.ColorRole.Shadow: "DividerStrokeColorDefault",
}

# 禁用状态下需要降透明度/弱化的文本角色。
# setPalette 会连同 Disabled 组一起覆写，因此需要单独对这些角色赋予次要文字色，确保置灰反馈明显。
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
        """根据映射表构建 Qt 原生 QPalette，供未被 QSS 覆写的原生控件使用。

        按 :data:`ROLE_SOURCES` 设置全部 ColorRole。
        未设置的值会被 Qt 回退为系统默认值，因此映射表必须保持完整。

        Returns:
            填充了全部 ColorRole 的 QPalette。
        """
        palette = QPalette()
        for role, prop_name in ROLE_SOURCES.items():
            color_str = getattr(self, prop_name)
            palette.setColor(role, QColor(color_str))

        # 单独处理禁用态置灰，防止文字与正常状态同色
        disabled_color = QColor(self.TextFillColorSecondary)
        for role in DISABLED_TEXT_ROLES:
            palette.setColor(QPalette.ColorGroup.Disabled, role, disabled_color)

        return palette


class ThemeService(QObject):
    """主题渲染服务。

    Attributes:
        tokens (ClassVar[Palette]): 当前主题 token，构造与渲染时更新；
            供 Card.surface_color 等按名取色。
    """

    themeChanged = Signal(Palette)

    # 全局当前生效的调色板快照，供无上下文的静态表面（如 Card 底色）快速查阅
    tokens: ClassVar[Palette]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_preference = ThemeMode.SYSTEM
        self._palettes: dict[ThemeMode, Palette] = {
            ThemeMode.LIGHT: self._load_palette("light"),
            ThemeMode.DARK: self._load_palette("dark"),
        }
        self.current_palette: Palette = self._palettes[ThemeMode.LIGHT]
        ThemeService.tokens = self.current_palette

        # 监听操作系统层面的深浅色切换
        if hasattr(QGuiApplication, "styleHints"):
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)

    @property
    def effective_mode(self) -> ThemeMode:
        """当前实际落到屏幕上的具象主题模式"""
        if self._current_preference != ThemeMode.SYSTEM:
            return self._current_preference
        return self._detect_system_mode()

    @staticmethod
    def _detect_system_mode() -> ThemeMode:
        """检测系统层面的深浅色模式"""
        if hasattr(QGuiApplication, "styleHints"):
            hints = QGuiApplication.styleHints()
            match hints.colorScheme():
                case Qt.ColorScheme.Light:
                    return ThemeMode.LIGHT
                case Qt.ColorScheme.Dark:
                    return ThemeMode.DARK
                case _:
                    logger.warning(f"未知系统色彩方案: {hints.colorScheme()}，回退为浅色模式")
                    return ThemeMode.LIGHT

        return ThemeMode.LIGHT

    @staticmethod
    def _load_palette(name: str) -> Palette:
        """从 assets/themes/{name}.json 加载调色板"""
        path = THEMES_DIR / f"{name}.json"
        data = read_json(path)
        if not isinstance(data, dict):
            raise FileNotFoundError(f"主题文件缺失或格式损坏: {path}")

        try:
            return Palette(**data)
        except (TypeError, ValueError) as e:
            raise ValueError(f"主题文件字段与 Palette 定义不匹配: {path}") from e

    def apply_theme(self, preference: ThemeMode) -> None:
        """将选定的 Palette 同步注入到 QPalette 与 QSS 模板中"""
        self._current_preference = preference
        self._render(self._palettes[self.effective_mode])

    def _render(self, palette: Palette) -> None:
        """同步更新 QPalette 与 QSS 样式表，使两者的渲染变更同时生效。"""
        self.current_palette = palette
        ThemeService.tokens = palette

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return

        # 1. 注入原生 QPalette（必须在 setStyleSheet 之前）
        app.setPalette(palette.to_qpalette())

        # 2. 清空 SvgIcon 渲染缓存，使后续矢量图标按新前景色光栅化
        SvgIcon.clear_cache()

        # 3. 编译并注入全局 QSS（用 str.replace 避免 CSS 大括号冲突）
        if QSS_PATH.exists():
            try:
                css = QSS_PATH.read_text(encoding="utf-8")
                for key, value in dataclasses.asdict(palette).items():
                    css = css.replace(f"{{{key}}}", value)
                app.setStyleSheet(css)
            except Exception:
                logger.exception("加载样式表失败")

        # 4. 广播主题变动信号，通知各业务视图与 QML 桥接层
        self.themeChanged.emit(palette)
        logger.info(f"全局主题已生效: {self._current_preference.value}")

    @Slot(Qt.ColorScheme)
    def _on_system_scheme_changed(self, scheme: Qt.ColorScheme):
        """操作系统层面的深浅色切换回调"""
        if self._current_preference == ThemeMode.SYSTEM:
            concrete_mode = ThemeMode.LIGHT if scheme == Qt.ColorScheme.Light else ThemeMode.DARK
            self._render(self._palettes[concrete_mode])
