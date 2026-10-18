"""矢量图标系统。

按主题前景色惰性渲染 SVG 图标。
图标常量登记在 :class:`SvgIcon` 上，属性访问即渲染，无需实例化。

Typical usage example::

    from danmaku_sender.ui.framework.icons import SvgIcon

    button.setIcon(SvgIcon.SEND)                   # 零括号，直接当 QIcon 用
    button.setIcon(SvgIcon.SEND(color="#ff0000"))  # 指定颜色重新渲染
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


def get_app_icon() -> QIcon:
    """获取程序全局窗口图标。

    Returns:
        QIcon: 窗口图标；图标文件缺失时返回空图标。
    """
    icon_path = AppInfo.Paths.ASSETS / "icon.ico"
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


def get_current_text_color() -> str | None:
    """获取当前生效的主前景色。

    Returns:
        str | None: 十六进制颜色字符串；脱离 GUI 环境时返回 ``None``。
    """
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app.palette().color(QPalette.ColorRole.WindowText).name()
    return None


@lru_cache(maxsize=128)
def _render_svg_icon(file_path_str: str, color: str | None) -> QIcon:
    """解析并光栅化 SVG 图标，同路径与同颜色仅渲染一次。

    Args:
        file_path_str (str): SVG 文件的绝对路径。
        color (str | None): 填充色；为 ``None`` 时保留文件原有颜色。

    Returns:
        QIcon: 渲染结果；文件缺失或渲染失败时返回退化图标。
    """
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
    """可调用的主题图标。

    零括号直接当 :class:`QIcon` 使用；带括号则按指定颜色重新渲染，
    返回新的实例。持有源 SVG 路径，是重新渲染的依据。

    Typical usage example::

        icon = SvgIcon.SEND                    # 零括号，已按当前前景色渲染好
        label.setPixmap(icon.pixmap(20, 20))

        SvgIcon.SEND(color="#ff0000")  # 指定颜色重新渲染
        SvgIcon.SEND()                 # 不填颜色 = 重新按当前前景色渲染
    """

    def __init__(self, base_icon: QIcon, file_path_str: str, subfolder: str | None):
        super().__init__(base_icon)
        self._file_path_str = file_path_str
        self._subfolder = subfolder

    def __call__(self, *, color: str | None = None) -> "_ThemedIcon":
        """按指定颜色重新渲染本图标。

        Args:
            color (str | None): 填充色；省略则取当前调色板前景色。

        Returns:
            _ThemedIcon: 重新渲染后的主题图标，与本实例指向同一 SVG 文件。

        Typical usage example::

            SvgIcon.START(color="#ff0000")  # 指定颜色渲染
            SvgIcon.START()                 # 重新按当前前景色渲染
        """
        if color is None:
            color = get_current_text_color()
        raw_icon = _render_svg_icon(self._file_path_str, color)
        return _ThemedIcon(raw_icon, self._file_path_str, self._subfolder)


class _IconDescriptor:
    """把 SVG 文件名延迟解析为 :class:`_ThemedIcon` 的属性描述符。

    惰性求值，保证在 ``QApplication`` 构造之后才计算前景色。
    文件名相对 :data:`ICONS_DIR` 解析。

    Typical usage example::

        class SvgIcon:
            SEND = _IconDescriptor("send.svg")                    # assets/icons/send.svg
            LOGO = _IconDescriptor("logo.svg", "account_levels")  # assets/icons/account_levels/logo.svg

        SvgIcon.SEND  # 访问该类属性时才渲染
    """

    def __init__(self, filename: str, subfolder: str | None = None):
        self.filename = filename
        self.subfolder = subfolder

    def _get_path_str(self) -> str:
        target_dir = ICONS_DIR / self.subfolder if self.subfolder else ICONS_DIR
        return str(target_dir / self.filename)

    def __get__(self, instance, owner=None) -> _ThemedIcon:
        """渲染本图标，颜色取当前调色板前景色。

        Args:
            instance (object | None): 访问者；经类访问时为 ``None``。
            owner (type | None): 持有本描述符的类。

        Returns:
            _ThemedIcon: 按当前前景色渲染好的主题图标。
        """
        path_str = self._get_path_str()
        current_color = get_current_text_color()
        raw_icon = _render_svg_icon(path_str, current_color)
        return _ThemedIcon(raw_icon, path_str, self.subfolder)


class SvgIcon:
    """图标常量注册表。

    每个类属性是一个 :class:`_IconDescriptor`，
    访问即按当前调色板前景色渲染并返回 :class:`_ThemedIcon`。
    全部为强类型符号，IDE 可自动补全。

    Typical usage example::

        button.setIcon(SvgIcon.SEND)                   # 零括号，直接当 QIcon
        button.setIcon(SvgIcon.SEND(color="#ff0000"))  # 指定颜色
        SvgIcon.clear_cache()                          # 主题切换后清缓存
    """

    AUTO_AWESOME = _IconDescriptor("auto_awesome.svg")
    ARROW_DOWNWARD = _IconDescriptor("arrow_downward.svg")
    ARROW_UPWARD = _IconDescriptor("arrow_upward.svg")
    CANCEL = _IconDescriptor("cancel.svg")
    CHECK_CIRCLE = _IconDescriptor("check_circle.svg")
    CHEVRON_RIGHT = _IconDescriptor("chevron_right.svg")
    CLOSE = _IconDescriptor("close.svg")
    CONTENT_COPY = _IconDescriptor("content_copy.svg")
    DEFAULT_AVATAR = _IconDescriptor("default_avatar.svg")
    DELETE = _IconDescriptor("delete.svg")
    DELETE_SWEEP = _IconDescriptor("delete_sweep.svg")
    DONE_ALL = _IconDescriptor("done_all.svg")
    EDIT_DOCUMENT = _IconDescriptor("edit_document.svg")
    EDIT_LINE = _IconDescriptor("edit_line.svg")
    EDIT_ARROW_DOWN = _IconDescriptor("edit_arrow_down.svg")
    EDIT_ARROW_UP = _IconDescriptor("edit_arrow_up.svg")
    ERROR = _IconDescriptor("error.svg")
    FACT_CHECK = _IconDescriptor("fact_check.svg")
    FILE_OPEN = _IconDescriptor("file_open.svg")
    FILE_SAVE = _IconDescriptor("file_save.svg")
    FORMAT_CLEAR = _IconDescriptor("format_clear.svg")
    GRADIENT = _IconDescriptor("gradient.svg")
    HANDYMAN = _IconDescriptor("handyman.svg")
    HELP = _IconDescriptor("help.svg")
    HISTORY = _IconDescriptor("history.svg")
    HOW_TO_REG = _IconDescriptor("how_to_reg.svg")
    INFO = _IconDescriptor("info.svg")
    MONITOR = _IconDescriptor("monitor.svg")
    NOTE_ADD = _IconDescriptor("note_add.svg")
    OPEN_IN_NEW = _IconDescriptor("open_in_new.svg")
    PERSON_ADD = _IconDescriptor("person_add.svg")
    PLAYLIST_ADD = _IconDescriptor("playlist_add.svg")
    PLAY_ARROW = _IconDescriptor("play_arrow.svg")
    QR_SCAN = _IconDescriptor("qr_scan.svg")
    REFRESH = _IconDescriptor("refresh.svg")
    RESTART_ALT = _IconDescriptor("restart_alt.svg")
    SAVE = _IconDescriptor("save.svg")
    SEARCH_CHECK = _IconDescriptor("search_check.svg")
    SEND = _IconDescriptor("send.svg")
    SETTINGS = _IconDescriptor("settings.svg")
    SHORT_TEXT = _IconDescriptor("short_text.svg")
    START = _IconDescriptor("start.svg")
    STOP = _IconDescriptor("stop.svg")
    SUBJECT = _IconDescriptor("subject.svg")
    SYNC_ALT = _IconDescriptor("sync_alt.svg")
    TROUBLESHOOT = _IconDescriptor("troubleshoot.svg")
    TUNE = _IconDescriptor("tune.svg")
    UNDO = _IconDescriptor("undo.svg")
    WARNING = _IconDescriptor("warning.svg")

    @staticmethod
    def clear_cache() -> None:
        """清空渲染缓存，下次访问按新主题颜色重新渲染。

        Typical usage example::

            SvgIcon.clear_cache()  # 主题切换后调用
        """
        _render_svg_icon.cache_clear()


def rerender(icon: QIcon) -> QIcon:
    """按当前调色板前景色重新渲染主题图标。

    Args:
        icon (QIcon): 先前由 :class:`SvgIcon` 取得的图标。

    Returns:
        QIcon: 重新渲染后的图标；非主题图标按原样返回。

    Typical usage example::

        # 主题切换后重绘已固化到控件上的位图
        label.setPixmap(rerender(stored_icon).pixmap(20, 20))
    """
    return icon() if isinstance(icon, _ThemedIcon) else icon
