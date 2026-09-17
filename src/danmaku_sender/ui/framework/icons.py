"""矢量图标系统

- SvgIcon.START               → 零括号，直接当 QIcon 实例用
- SvgIcon.START(color="...")  → 指定颜色动态生成
"""

import logging
import re
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QApplication

from danmaku_sender.config.app_meta import AppInfo

from .image_processor import QtImageProcessor

logger = logging.getLogger(__name__)

ICONS_DIR = AppInfo.Paths.ASSETS / "icons"


def _load_app_icon() -> QIcon:
    """加载程序全局窗口图标（.ico）"""
    icon_path = AppInfo.Paths.ASSETS / "icon.ico"
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


APP_ICON: QIcon = _load_app_icon()


def get_current_text_color() -> str | None:
    """从当前生效的 Qt 调色板获取主前景色；脱离 GUI 环境时返回 None"""
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app.palette().color(QPalette.ColorRole.WindowText).name()
    return None


@lru_cache(maxsize=128)
def _render_svg_icon(file_path_str: str, color: str | None) -> QIcon:
    """底层渲染缓存：同路径 + 同颜色仅解析并光栅化一次"""
    path = Path(file_path_str)
    if not path.exists():
        logger.warning(f"图标文件缺失: {path.name}")
        return QIcon()

    try:
        svg_content = path.read_text(encoding="utf-8")
        if color:
            if "fill=" in svg_content:
                svg_content = re.sub(r'fill=(["\']).*?\1', f'fill="{color}"', svg_content)
            else:
                svg_content = svg_content.replace("<svg", f'<svg fill="{color}"', 1)

        pixmap = QtImageProcessor.render_svg(svg_content.encode("utf-8"), 128, 1.0)
        return QIcon(pixmap) if not pixmap.isNull() else QIcon(str(path))
    except Exception as e:
        logger.error(f"渲染 SVG 图标失败 [{path.name}]: {e}", exc_info=True)
        return QIcon(str(path))


class _ThemedIcon(QIcon):
    """可调用的 QIcon 派生类——零括号直接当 QIcon，带括号支持覆写颜色"""

    def __init__(self, base_icon: QIcon, file_path_str: str, subfolder: str | None):
        super().__init__(base_icon)
        self._file_path_str = file_path_str
        self._subfolder = subfolder

    def __call__(self, *, color: str | None = None) -> "_ThemedIcon":
        """SvgIcon.START(color="#ff0000")：使用指定颜色重新渲染"""
        raw_icon = _render_svg_icon(self._file_path_str, color)
        return _ThemedIcon(raw_icon, self._file_path_str, self._subfolder)


class _IconDescriptor:
    """属性描述符：惰性求值，保障在 QApplication 初始化后才计算当前颜色"""

    def __init__(self, filename: str, subfolder: str | None = None):
        self.filename = filename
        self.subfolder = subfolder

    def _get_path_str(self) -> str:
        target_dir = ICONS_DIR / self.subfolder if self.subfolder else ICONS_DIR
        return str(target_dir / self.filename)

    def __get__(self, instance, owner=None) -> _ThemedIcon:
        """SvgIcon.START → 根据当前调色板前景色动态解析/读取缓存"""
        path_str = self._get_path_str()
        current_color = get_current_text_color()
        raw_icon = _render_svg_icon(path_str, current_color)
        return _ThemedIcon(raw_icon, path_str, self.subfolder)


class SvgIcon:
    """图标常量注册表（全部为强类型符号，IDE 自动补全）"""

    AUTO_AWESOME = _IconDescriptor("auto_awesome.svg")
    CANCEL = _IconDescriptor("cancel.svg")
    CHECK_CIRCLE = _IconDescriptor("check_circle.svg")
    DEFAULT_AVATAR = _IconDescriptor("default_avatar.svg")
    DELETE = _IconDescriptor("delete.svg")
    DONE_ALL = _IconDescriptor("done_all.svg")
    EDIT = _IconDescriptor("edit.svg")
    EDIT_DOCUMENT = _IconDescriptor("edit_document.svg")
    FILE_OPEN = _IconDescriptor("file_open.svg")
    FILE_SAVE = _IconDescriptor("file_save.svg")
    FORMAT_CLEAR = _IconDescriptor("format_clear.svg")
    GRADIENT = _IconDescriptor("gradient.svg")
    HANDYMAN = _IconDescriptor("handyman.svg")
    HELP = _IconDescriptor("help.svg")
    HISTORY = _IconDescriptor("history.svg")
    HOW_TO_REG = _IconDescriptor("how_to_reg.svg")
    MONITOR = _IconDescriptor("monitor.svg")
    NOTE_ADD = _IconDescriptor("note_add.svg")
    PERSON_ADD = _IconDescriptor("person_add.svg")
    PLAY_ARROW = _IconDescriptor("play_arrow.svg")
    QR_SCAN = _IconDescriptor("qr_scan.svg")
    SEND = _IconDescriptor("send.svg")
    SETTINGS = _IconDescriptor("settings.svg")
    SHORT_TEXT = _IconDescriptor("short_text.svg")
    START = _IconDescriptor("start.svg")
    STOP = _IconDescriptor("stop.svg")
    SYNC_ALT = _IconDescriptor("sync_alt.svg")
    TROUBLESHOOT = _IconDescriptor("troubleshoot.svg")
    UNDO = _IconDescriptor("undo.svg")
    VERTICAL_ALIGN_BOTTOM = _IconDescriptor("vertical_align_bottom.svg")
    VERTICAL_ALIGN_TOP = _IconDescriptor("vertical_align_top.svg")

    @staticmethod
    def clear_cache() -> None:
        """主题切换时清空缓存，让下次访问以新主题颜色重新渲染"""
        _render_svg_icon.cache_clear()
