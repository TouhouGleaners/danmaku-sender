"""QML 承载基座。

把 QML 表面装进 widgets 界面，并以根对象初始属性注入主题令牌与字体。
取色与字体均取自控件自身的 QPalette / QFont，随全局主题与字体变更同步。

两种承载：QmlHost 以 QQuickWidget 装进控件树，适合小控件；
QmlWindowHost 以原生 Quick 窗口承载，适合大场景——不经控件贴图回读，
且场景内部的布局变化（如分栏拖动）不触碰承载面的改尺寸。
"""
import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QEvent, QObject, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickView
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


class QmlPaletteBridge(QObject):
    """注入 QML 根对象的主题令牌，属性名为 ``theme``。

    取色角色与 ``ThemeService.ROLE_SOURCES`` 的语义对应：
    填充阶梯的悬停与按压档取自 Light / Midlight，画布取自 Window。

    Attributes:
        changed (Signal): 令牌取值变更广播，驱动 QML 绑定刷新。
    """

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._palette = QPalette()
        self._font = QFont()

    def sync(self, palette: QPalette, font: QFont) -> None:
        """刷新取色与字体来源并广播变更。

        Args:
            palette (QPalette): 当前生效的调色板。
            font (QFont): 当前生效的字体。
        """
        self._palette = palette
        self._font = font
        self.changed.emit()

    @Property(QColor, notify=changed)
    def background(self) -> QColor:
        """画布底色，取自 QPalette.Window。"""
        return self._palette.color(QPalette.ColorRole.Window)

    @Property(QColor, notify=changed)
    def fillHover(self) -> QColor:
        """悬停填充，取自 QPalette.Light。"""
        return self._palette.color(QPalette.ColorRole.Light)

    @Property(QColor, notify=changed)
    def fillPressed(self) -> QColor:
        """按压填充，取自 QPalette.Midlight。"""
        return self._palette.color(QPalette.ColorRole.Midlight)

    @Property(QColor, notify=changed)
    def text(self) -> QColor:
        """正文色，取自 QPalette.Text。"""
        return self._palette.color(QPalette.ColorRole.Text)

    @Property(QColor, notify=changed)
    def textSecondary(self) -> QColor:
        """次要文字色，取自 QPalette.PlaceholderText。"""
        return self._palette.color(QPalette.ColorRole.PlaceholderText)

    @Property(QColor, notify=changed)
    def accent(self) -> QColor:
        """强调色，取自 QPalette.Highlight。"""
        return self._palette.color(QPalette.ColorRole.Highlight)

    @Property(str, notify=changed)
    def fontFamily(self) -> str:
        """字体族名称。"""
        return self._font.family()

    @Property(int, notify=changed)
    def fontPointSize(self) -> int:
        """字号（磅）；像素字号按屏上 DPI 折算，QFont.pointSize 对其返回 -1。"""
        if self._font.pointSize() > 0:
            return self._font.pointSize()
        dpi = QGuiApplication.primaryScreen().logicalDotsPerInch()
        return round(self._font.pixelSize() * 72.0 / dpi)


class QmlHost(QQuickWidget):
    """QML 表面承载器：加载 QML 并保持主题令牌同步。

    构造时把 ``theme`` 与调用方给出的对象作为根对象初始属性注入后立即加载，
    调用方须在构造前备齐要注入的对象，QML 根对象按名声明对应 required property。
    调色板与字体变更经 changeEvent 自动同步。

    Args:
        qml_path (Path): QML 文件路径。
        properties (dict[str, Any] | None): 注入 QML 根对象的初始属性表。
        parent (QWidget | None): 父控件。
    """

    def __init__(
        self,
        qml_path: Path,
        properties: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)

        self._bridge = QmlPaletteBridge(self)
        self.setInitialProperties({**(properties or {}), "theme": self._bridge})

        self._bridge.sync(self.palette(), self.font())
        self.setSource(QUrl.fromLocalFile(str(qml_path)))
        if self.status() == QQuickWidget.Status.Error:
            detail = " | ".join(
                error.toString() for error in QQmlComponent(self.engine(), self.source()).errors()
            )
            logger.error(f"QML 加载失败: {qml_path} | {detail}")

    def changeEvent(self, event: QEvent) -> None:
        """调色板或字体变更后刷新主题令牌。"""
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.FontChange):
            self._bridge.sync(self.palette(), self.font())


class QmlWindowHost(QWidget):
    """以原生 Quick 窗口承载 QML 大场景的宿主控件。

    注入契约与 :class:`QmlHost` 相同。承载面不经控件贴图回读；
    场景内部的布局变化（如分栏拖动）不触碰承载面的改尺寸。

    Args:
        qml_path (Path): QML 文件路径。
        properties (dict[str, Any] | None): 注入 QML 根对象的初始属性表。
        parent (QWidget | None): 父控件。
    """

    def __init__(
        self,
        qml_path: Path,
        properties: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = QmlPaletteBridge(self)

        self._view = QQuickView()
        self._view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self._view.setInitialProperties({**(properties or {}), "theme": self._bridge})
        self._sync_surface()
        self._bridge.sync(self.palette(), self.font())
        self._view.setSource(QUrl.fromLocalFile(str(qml_path)))
        if self._view.status() == QQuickView.Status.Error:
            detail = " | ".join(
                error.toString()
                for error in QQmlComponent(self._view.engine(), self._view.source()).errors()
            )
            logger.error(f"QML 加载失败: {qml_path} | {detail}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QWidget.createWindowContainer(self._view, self))

    def changeEvent(self, event: QEvent) -> None:
        """调色板或字体变更后刷新表面底色与主题令牌。"""
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.FontChange):
            self._sync_surface()
            self._bridge.sync(self.palette(), self.font())

    def _sync_surface(self) -> None:
        """把 QML 表面的清屏色同步为画布底色。"""
        self._view.setColor(self.palette().color(QPalette.ColorRole.Window))
