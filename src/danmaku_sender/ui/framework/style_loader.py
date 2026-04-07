import re
import logging

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .image_processor import QtImageProcessor
from ..theme_manager import ThemeManager

from ...utils.path_utils import get_assets_path


logger = logging.getLogger("App.UI.StyleLoader")


def get_app_icon() -> QIcon:
    """获取程序全局图标"""
    icon_path = get_assets_path() / "icon.ico"
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()

def get_svg_icon(name: str, color: str | None = None) -> QIcon:
    """加载矢量图标"""
    icon_path = get_assets_path() / "icons" / name
    if not icon_path.exists():
        return QIcon()

    try:
        svg_content = icon_path.read_text(encoding="utf-8")
        if color is None:
            color = ThemeManager.instance().current().text_main

        if color:
            if 'fill=' in svg_content:
                svg_content = re.sub(r'fill=(["\']).*?\1', f'fill="{color}"', svg_content)
            else:
                svg_content = svg_content.replace("<svg", f'<svg fill="{color}"', 1)

        app = QApplication.instance()
        if isinstance(app, QApplication):
            dpr = app.primaryScreen().devicePixelRatio() if app else 1.0

        pixmap = QtImageProcessor.render_svg(svg_content.encode("utf-8"), 32, dpr)

        if not pixmap.isNull():
            return QIcon(pixmap)
        return QIcon(str(icon_path))

    except Exception as e:
        logger.error(f"动态渲染 SVG 图标失败 [{name}]: {e}", exc_info=True)
        return QIcon(str(icon_path))

def load_stylesheet():
    """加载全局样式表"""
    qss_path = get_assets_path() / "qss" / "style.qss"
    if not qss_path.exists():
        return

    try:
        with open(qss_path, "r", encoding="utf-8") as f:
            content = f.read()

        palette = ThemeManager.instance().current()

        replacements = {
            "{bg_base}": palette.bg_base,
            "{bg_surface}": palette.bg_surface,
            "{bg_hover}": palette.bg_hover,
            "{border_color}": palette.border_color,
            "{text_main}": palette.text_main,
            "{text_secondary}": palette.text_secondary,
            "{primary}": palette.primary,
            "{success}": palette.success,
            "{danger}": palette.danger,
            "{danger_bg}": palette.danger_bg
        }

        for key, value in replacements.items():
            content = content.replace(key, value)

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(content)

    except Exception as e:
        logger.error(f"渲染样式表模板失败: {e}", exc_info=True)