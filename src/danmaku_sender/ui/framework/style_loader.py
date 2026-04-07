import re
import logging

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

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
                svg_content = re.sub(r'fill="[^"]*"', f'fill="{color}"', svg_content)
            else:
                svg_content = svg_content.replace("<svg", f'<svg fill="{color}"', 1)

        data_bytes = svg_content.encode("utf-8")

        renderer = QSvgRenderer(data_bytes)
        if not renderer.isValid():
            return QIcon(str(icon_path))

        render_size = QSize(128, 128)
        pixmap = QPixmap(render_size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()

        return QIcon(pixmap)

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