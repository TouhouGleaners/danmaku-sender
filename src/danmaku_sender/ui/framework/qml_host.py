"""QML 承载基座。

把 QML 表面装进 widgets 界面，并以根对象初始属性注入主题令牌与字体。
取色与字体均取自控件自身的 QPalette / QFont，随全局主题与字体变更同步。

两种承载：QmlHost 以 QQuickWidget 装进控件树，适合小控件；
QmlWindowHost 以原生 Quick 窗口承载，适合大场景——不经控件贴图回读，
且场景内部的布局变化（如分栏拖动）不触碰承载面的改尺寸。
"""
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QEvent, QObject, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickView
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

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
        self._dpi: float | None = None
        # WinUI 的图标字体回退链；无字体的系统留空串，由 QML 端容错
        self._icon_font_family = next(
            (name for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if name in QFontDatabase.families()),
            "",
        )

    def sync(self, palette: QPalette, font: QFont, dpi: float) -> None:
        """刷新取色、字体与 DPI 来源并广播变更。

        Args:
            palette (QPalette): 当前生效的调色板。
            font (QFont): 当前生效的字体。
            dpi (float): 宿主所在屏幕的逻辑 DPI，用于像素字号折算。
        """
        self._palette = palette
        self._font = font
        self._dpi = dpi
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
        """字号（磅）；像素字号按宿主屏幕 DPI 折算，QFont.pointSize 对其返回 -1。"""
        if self._font.pointSize() > 0:
            return self._font.pointSize()
        # 像素字号按宿主屏幕 DPI 折算；同步前无 DPI 可用，退回 96 这一行业基准
        dpi = self._dpi if self._dpi is not None else 96.0
        return round(self._font.pixelSize() * 72.0 / dpi)

    @Property(str, notify=changed)
    def iconFontFamily(self) -> str:
        """图标字体族；取值见构造时的回退链。"""
        return self._icon_font_family


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

        self._bridge.sync(self.palette(), self.font(), self.screen().logicalDotsPerInch())
        self.setSource(QUrl.fromLocalFile(str(qml_path)))
        if self.status() == QQuickWidget.Status.Error:
            detail = " | ".join(
                error.toString() for error in QQmlComponent(self.engine(), self.source()).errors()
            )
            # 脱离父控件再抛出：失败件不留在调用方布局里，避免捕获重试时累积孤儿
            self.setParent(None)
            raise RuntimeError(f"QML 加载失败: {qml_path} | {detail}")

    def changeEvent(self, event: QEvent) -> None:
        """调色板、字体或所在屏幕变更后刷新主题令牌。"""
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.FontChange,
            QEvent.Type.ScreenChangeInternal,
            QEvent.Type.DevicePixelRatioChange,
        ):
            self._bridge.sync(self.palette(), self.font(), self.screen().logicalDotsPerInch())


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
        self._bridge.sync(self.palette(), self.font(), self.screen().logicalDotsPerInch())
        self._view.setSource(QUrl.fromLocalFile(str(qml_path)))
        if self._view.status() == QQuickView.Status.Error:
            detail = " | ".join(
                error.toString()
                for error in QQmlComponent(self._view.engine(), self._view.source()).errors()
            )
            # 脱离父控件再抛出：失败件不留在调用方布局里，避免捕获重试时累积孤儿
            self.setParent(None)
            raise RuntimeError(f"QML 加载失败: {qml_path} | {detail}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QWidget.createWindowContainer(self._view, self))

    def changeEvent(self, event: QEvent) -> None:
        """调色板、字体或所在屏幕变更后刷新表面底色与主题令牌。"""
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.FontChange,
            QEvent.Type.ScreenChangeInternal,
            QEvent.Type.DevicePixelRatioChange,
        ):
            self._sync_surface()
            self._bridge.sync(self.palette(), self.font(), self.screen().logicalDotsPerInch())

    def _sync_surface(self) -> None:
        """把 QML 表面的清屏色同步为画布底色。"""
        self._view.setColor(self.palette().color(QPalette.ColorRole.Window))
