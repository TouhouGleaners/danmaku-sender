import logging
import re

from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QApplication

from danmaku_sender.config.app_meta import AppInfo

from .image_processor import QtImageProcessor

logger = logging.getLogger(__name__)

def get_app_icon() -> QIcon:
    """获取程序全局图标"""
    icon_path = AppInfo.Paths.ASSETS / "icon.ico"
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()


def get_current_text_color() -> str | None:
    """从当前生效的 Qt 调色板获取前景色；脱离 GUI 环境时返回 None，不强行染色"""
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app.palette().color(QPalette.ColorRole.WindowText).name()
    return None


class SvgIcon:
    """矢量图标加载器。

    用法：SvgIcon("name.svg") → QIcon
    """

    def __new__(cls, name: str, color: str | None = None, subfolder: str | None = None) -> QIcon:
        if subfolder:
            icon_path = AppInfo.Paths.ASSETS / "icons" / subfolder / name
        else:
            icon_path = AppInfo.Paths.ASSETS / "icons" / name
        if not icon_path.exists():
            return QIcon()

        try:
            svg_content = icon_path.read_text(encoding="utf-8")
            if color is None:
                color = get_current_text_color()

            # 只有真正拿到了颜色才染色；None 时保持 SVG 原样
            if color:
                if 'fill=' in svg_content:
                    svg_content = re.sub(r'fill=(["\']).*?\1', f'fill="{color}"', svg_content)
                else:
                    svg_content = svg_content.replace("<svg", f'<svg fill="{color}"', 1)

            pixmap = QtImageProcessor.render_svg(svg_content.encode("utf-8"), 128, 1.0)

            if not pixmap.isNull():
                return QIcon(pixmap)
            return QIcon(str(icon_path))

        except Exception as e:
            logger.error(f"动态渲染 SVG 图标失败 [{name}]: {e}", exc_info=True)
            return QIcon(str(icon_path))
