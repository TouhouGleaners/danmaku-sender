"""字体注册与文字渲染策略。

字体档位由字体族与 hinting 偏好构成。
细体与粗体的 hinting 策略不同，由服务按字重分别施加于控件。
"""

import logging
import sys
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget

from danmaku_sender.config.app_meta import AppInfo

logger = logging.getLogger(__name__)

FONTS_DIR = AppInfo.Paths.ASSETS / "fonts"
FONT_FILES: tuple[str, ...] = (
    "MiSans-Regular.ttf",
    "MiSans-Semibold.ttf",
)

# 采用灰度抗锯齿，避免 ClearType 产生彩色边缘
TEXT_RENDER_STRATEGY = QFont.StyleStrategy(
    QFont.StyleStrategy.PreferQuality
    | QFont.StyleStrategy.PreferAntialias
    | QFont.StyleStrategy.NoSubpixelAntialias
)

# 字重达到该值时按粗体策略应用 hinting
BOLD_WEIGHT = 600


@dataclass(frozen=True)
class FontProfile:
    """字体档位定义。

    Attributes:
        label: 设置页中的显示名称。
        families: 字体族名称，按回退顺序排列；空元组表示使用系统默认字体。
        bundled: 是否使用随附的字体文件。
        body_hinting: 细体的 hinting 偏好。
        bold_hinting: 粗体的 hinting 偏好。
    """

    label: str
    families: tuple[str, ...]
    bundled: bool
    body_hinting: QFont.HintingPreference
    bold_hinting: QFont.HintingPreference

    def hinting_for(self, weight: int) -> QFont.HintingPreference:
        """按字重返回 hinting 偏好。

        Args:
            weight: 字重，取值同 ``QFont.weight``。

        Returns:
            该字重对应的 hinting 偏好。
        """
        return self.bold_hinting if weight >= BOLD_WEIGHT else self.body_hinting


# 字形本身清晰，无需 hinting。
# 禁用：Windows 的 DirectWrite 会将 hinting 施加于笔画，造成局部加粗；
# 启用：其余平台的垂直 hinting 可改善小字号的清晰度。
_MISANS_HINTING = (
    QFont.HintingPreference.PreferNoHinting
    if sys.platform == "win32"
    else QFont.HintingPreference.PreferVerticalHinting
)

PROFILES: dict[str, FontProfile] = {
    "misans": FontProfile(
        label="MiSans",
        families=("MiSans",),
        bundled=True,
        body_hinting=_MISANS_HINTING,
        bold_hinting=_MISANS_HINTING,
    ),
    "yahei": FontProfile(
        label="微软雅黑",
        families=("Microsoft YaHei UI",),
        bundled=False,
        # 细体启用 hinting 以保持锐利，粗体禁用以避免垂直网格对齐导致的加粗
        body_hinting=QFont.HintingPreference.PreferDefaultHinting,
        bold_hinting=QFont.HintingPreference.PreferNoHinting,
    ),
    "system": FontProfile(
        label="跟随系统",
        families=(),
        bundled=False,
        body_hinting=QFont.HintingPreference.PreferDefaultHinting,
        bold_hinting=QFont.HintingPreference.PreferDefaultHinting,
    ),
}
DEFAULT_PROFILE = "misans"


class FontService(QObject):
    """字体渲染服务（隶属 UI 层，由 MainWindow 持有）。

    与 ThemeService 同属外观基础设施，须在创建任何 UI 控件之前完成首屏应用。
    持有随附字体的注册状态，以及按字重切换 hinting 的事件过滤器。

    Attributes:
        profile: 当前生效的字体档位。
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.profile: FontProfile = PROFILES[DEFAULT_PROFILE]
        self._bundled_registered = False
        self._hinting_filter = _HintingByWeight(self)
        self._hinting_filter.profile = self.profile

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.installEventFilter(self._hinting_filter)

    def apply(self, profile_name: str = DEFAULT_PROFILE) -> None:
        """按档位设置全局字体与文字渲染策略，并施加到已存在的控件。

        Args:
            profile_name: :data:`PROFILES` 的键；未登记的键使用默认档位。
        """
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            logger.error("FontService.apply 需在 QApplication 构造之后调用")
            return

        self.profile = PROFILES.get(profile_name, PROFILES[DEFAULT_PROFILE])
        self._hinting_filter.profile = self.profile

        if self.profile.bundled:
            self._ensure_bundled_fonts()

        families = self._target_families()

        font = QFont()
        font.setFamilies(families)
        font.setPointSize(app.font().pointSize())
        font.setHintingPreference(self.profile.body_hinting)
        font.setStyleStrategy(TEXT_RENDER_STRATEGY)
        app.setFont(font)

        self._apply_to_existing_widgets(app, families)
        logger.info(f"全局字体已设为 {self.profile.label}")

    def _target_families(self) -> list[str]:
        """返回当前档位的字体族列表。

        Returns:
            按回退顺序排列的字体族名称。
        """
        if self.profile.families:
            return list(self.profile.families)
        return [QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()]

    def _apply_to_existing_widgets(self, app: QApplication, families: list[str]) -> None:
        """把字体族与 hinting 施加到已存在的控件。

        ``QApplication.setFont`` 只对调用之后创建的控件生效，已存在的控件须逐个改写。
        各控件保留自身的字号、字重与斜体；一次 ``setFont`` 写全字体族与 hinting，
        避免再由 FontChange 回环补齐。

        Args:
            app: 应用实例。
            families: 目标字体族列表。
        """
        for widget in app.allWidgets():
            font = widget.font()
            font.setFamilies(families)
            font.setHintingPreference(self.profile.hinting_for(font.weight()))
            font.setStyleStrategy(TEXT_RENDER_STRATEGY)
            widget.setFont(font)
            widget.updateGeometry()

    def _ensure_bundled_fonts(self) -> None:
        """将随附字体注册进 Qt 字体库，仅执行一次。"""
        if self._bundled_registered:
            return
        self._bundled_registered = True

        for name in FONT_FILES:
            path = FONTS_DIR / name
            if not path.is_file():
                logger.error(f"缺少字体文件: {path}")
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id < 0 or not QFontDatabase.applicationFontFamilies(font_id):
                logger.error(f"字体注册失败: {path}")


class _HintingByWeight(QObject):
    """按字重调整控件的 hinting 偏好。

    细体与粗体对 hinting 的诉求相反：
    细体依赖 hinting 保持锐利，粗体需禁用 hinting 以避免笔画加粗。
    过滤器在控件样式初始化时按当前字重应用对应策略。

    ``setFont`` 会再送 FontChange，本过滤器须能重入；否则 hinting 取不齐时
    会与自己互相触发直至耗尽调用栈。

    Attributes:
        profile: 当前生效的字体档位，提供字重对应的 hinting 偏好。
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.profile: FontProfile = PROFILES[DEFAULT_PROFILE]
        self._applying = False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if self._applying:
            return False
        if isinstance(obj, QWidget) and event.type() in (
            QEvent.Type.Polish,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        ):
            self._apply(obj)
        return False

    def _apply(self, widget: QWidget) -> None:
        font = widget.font()
        want = self.profile.hinting_for(font.weight())
        if font.hintingPreference() == want:
            return
        self._applying = True
        try:
            font.setHintingPreference(want)
            widget.setFont(font)
        finally:
            self._applying = False
