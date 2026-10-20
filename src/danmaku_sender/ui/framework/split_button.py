"""主次两半的分体按钮。

左半执行主动作，右半弹出菜单。表面、立体描边、中缝与图文全部自绘。
填充走控件填充阶梯，强调面按不透明度叠在画布色上；描边为竖向渐变，
按下时仅该半边扁平化。配色取自应用级 QPalette，来源见 ThemeService 的 ROLE_SOURCES。
"""

import math
from enum import IntEnum

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QEnterEvent,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .icons import SvgIcon, rerender
from .keyboard_focus import KeyboardFocus


class SplitButton(KeyboardFocus, QWidget):
    """主次两半的分体按钮。

    Attributes:
        clicked (Signal): 点击主半边时发射。
    """

    clicked = Signal()

    # 外框；FOCUS_MARGIN 是留给焦点框的透明余量，按钮表面画在余量内侧
    RADIUS = 4
    HEIGHT = 28
    BORDER_WIDTH = 1
    FOCUS_MARGIN = 5

    # 中缝与右半
    SECONDARY_WIDTH = 32
    DIVIDER_WIDTH = 1

    # 图文排布
    PAD_H = 10
    PRIMARY_MIN_WIDTH = 32
    ICON_SIZE = 14
    ICON_GAP = 6
    # SVG 是 24 格字形，墨水只占一半宽；放大到 18 才等于 9px 的可见宽度
    CHEVRON_SIZE = 18

    # 按压回弹：按下即静止下沉，叠加一条起落各半的正弦位移
    PRESS_MS = 150
    PRESS_SINK = 0.5
    PRESS_BOUNCE = 0.5

    # 强调面的悬停与按压：填充换成强调色的半透明雾，底色透上来
    ACCENT_HOVER_OPACITY = 0.9
    ACCENT_PRESS_OPACITY = 0.8

    # 强调面的中缝（WinUI ControlStrokeColorOnAccentTertiary）
    ACCENT_DIVIDER = QColor(0, 0, 0, 55)

    # 双层焦点框：外环为主、内环为辅，整体落在按钮表面之外的余量里
    FOCUS_OUTER_WIDTH = 2
    FOCUS_INNER_WIDTH = 1
    FOCUS_OUTER_OUTSET = 4.0
    FOCUS_INNER_OUTSET = 2.5
    FOCUS_INNER_ALPHA = 0.7

    class _Half(IntEnum):
        """两个可按半边。

        Attributes:
            PRIMARY: 左半，执行主动作。
            SECONDARY: 右半，弹出菜单。
        """

        PRIMARY = 0
        SECONDARY = 1

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化分体按钮。

        Args:
            parent (QWidget | None): 父控件。
        """
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(self.HEIGHT + 2 * self.FOCUS_MARGIN)

        self._text = ""
        self._icon = QIcon()
        self._menu: QMenu | None = None
        self._accent: QColor | None = None

        self._hover: SplitButton._Half | None = None
        self._pressed: SplitButton._Half | None = None
        self._animated: SplitButton._Half | None = None
        self._open = False
        self._rebound = 0.0

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(self.PRESS_MS)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_anim.valueChanged.connect(self._accept_rebound)
        self._press_anim.finished.connect(self._finish_rebound)

    # ── 属性 ────────────────────────────────────────────────────────

    def setText(self, text: str) -> None:
        """设置主半边文字。

        Args:
            text (str): 主半边显示的文字。
        """
        if self._text == text:
            return
        self._text = text
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        """返回主半边文字。

        Returns:
            str: 主半边显示的文字。
        """
        return self._text

    def setIcon(self, icon: QIcon) -> None:
        """设置主半边图标。

        Args:
            icon (QIcon): 主半边显示的图标。
        """
        self._icon = icon
        self.update()

    def icon(self) -> QIcon:
        """返回主半边图标。

        Returns:
            QIcon: 主半边显示的图标。
        """
        return self._icon

    def setAccent(self, color: QColor | None) -> None:
        """设置强调面底色。

        Args:
            color (QColor | None): 强调色；为 ``None`` 时用中性控件面。
        """
        self._accent = QColor(color) if color is not None else None
        self.update()

    def accent(self) -> QColor | None:
        """返回强调面底色。

        Returns:
            QColor | None: 强调色；中性面时为 ``None``。
        """
        return QColor(self._accent) if self._accent is not None else None

    def setMenu(self, menu: QMenu | None) -> None:
        """设置右半边弹出的菜单。

        菜单可见期间两半均呈按压态。

        Args:
            menu (QMenu | None): 右半边弹出的菜单；为 ``None`` 时右半边不响应。
        """
        if self._menu is menu:
            return

        if self._menu is not None:
            self._menu.aboutToShow.disconnect(self._on_menu_shown)
            self._menu.aboutToHide.disconnect(self._on_menu_hidden)

        if self._open:
            self._open = False
            self.update()

        self._menu = menu
        if menu is not None:
            menu.aboutToShow.connect(self._on_menu_shown)
            menu.aboutToHide.connect(self._on_menu_hidden)

    def menu(self) -> QMenu | None:
        """返回右半边弹出的菜单。

        Returns:
            QMenu | None: 右半边弹出的菜单；未设置时为 ``None``。
        """
        return self._menu

    def isOpen(self) -> bool:
        """返回菜单是否正弹出。

        Returns:
            bool: 菜单可见时为 ``True``。
        """
        return self._open

    def sizeHint(self) -> QSize:
        """返回按内容量算的尺寸。

        Returns:
            QSize: 图标、文字与右半边的合计宽度，高度固定。
        """
        return QSize(math.ceil(self._content_width()), self.HEIGHT)

    def minimumSizeHint(self) -> QSize:
        """返回最小尺寸。

        Returns:
            QSize: 与按内容量算的尺寸一致。
        """
        return self.sizeHint()

    # ── 排布 ────────────────────────────────────────────────────────

    def _content_width(self) -> float:
        """返回内容合计宽度。

        Returns:
            float: 主区（含最小宽）与右半边之和。
        """
        primary = 2 * self.PAD_H
        if not self._icon.isNull():
            primary += self.ICON_SIZE
            if self._text:
                primary += self.ICON_GAP
        primary += self._text_width()
        primary = max(float(self.PRIMARY_MIN_WIDTH), primary)
        return primary + self.DIVIDER_WIDTH + self.SECONDARY_WIDTH + 2 * self.FOCUS_MARGIN

    def _text_width(self) -> float:
        """返回文字墨水所需宽度。

        墨水可能超出排版进宽，取三种度量的最大值以保证量算与绘制一致。

        Returns:
            float: 进宽、外接框与紧致外接框三者的最大值。
        """
        if not self._text:
            return 0.0
        metrics = QFontMetrics(self.font())
        return max(
            float(metrics.horizontalAdvance(self._text)),
            float(metrics.boundingRect(self._text).width()),
            float(metrics.tightBoundingRect(self._text).width()),
        )

    def _surface_rect(self) -> QRect:
        """返回按钮表面矩形，四周留出焦点框余量。

        Returns:
            QRect: 扣除 :attr:`FOCUS_MARGIN` 后的表面矩形。
        """
        m = self.FOCUS_MARGIN
        return self.rect().adjusted(m, m, -m, -m)

    def _zones(self) -> tuple[QRect, QRect]:
        """返回左右半边的命中矩形。

        Returns:
            tuple[QRect, QRect]: 主半边与次半边的命中矩形。
        """
        rect = self._surface_rect()
        return (
            QRect(rect.left(), rect.top(), rect.width() - self.SECONDARY_WIDTH, rect.height()),
            QRect(
                rect.right() - self.SECONDARY_WIDTH + 1,
                rect.top(),
                self.SECONDARY_WIDTH,
                rect.height(),
            ),
        )

    def _hit(self, pos: QPoint) -> _Half | None:
        """返回落点所在的半边。

        Args:
            pos (QPoint): 控件坐标系下的指针位置。

        Returns:
            SplitButton._Half | None: 落在半边内时为该半边，否则为 ``None``。
        """
        primary, secondary = self._zones()
        if primary.contains(pos):
            return SplitButton._Half.PRIMARY
        if secondary.contains(pos):
            return SplitButton._Half.SECONDARY
        return None

    def _palette(self) -> QPalette:
        """返回应用级调色板。

        Returns:
            QPalette: 主题调色板。
        """
        app = QApplication.instance()
        return app.palette() if isinstance(app, QApplication) else self.palette()

    # ── 事件 ────────────────────────────────────────────────────────

    def enterEvent(self, event: QEnterEvent) -> None:
        """指针进入时按落点更新悬停半边。"""
        super().enterEvent(event)
        self._set_hover(self._hit(event.position().toPoint()))

    def leaveEvent(self, event: QEvent) -> None:
        """指针离开时清除悬停半边，按压半边保留到松开。"""
        super().leaveEvent(event)
        self._hover = None
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """指针移动时更新悬停半边。"""
        super().mouseMoveEvent(event)
        self._set_hover(self._hit(event.position().toPoint()))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """按下半边：记下按压半边并启动回弹。

        两半都收下按压，避免事件上浮到父控件。
        """
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            super().mousePressEvent(event)
            return

        self._pressed = self._hit(event.position().toPoint())
        if self._pressed is None:
            super().mousePressEvent(event)
            return

        self._start_rebound(self._pressed)
        self.update()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """空格与回车触发主动作，Alt+下 或 F4 弹出菜单。

        Args:
            event (QKeyEvent): 键盘事件。
        """
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
            event.accept()
            return

        alt_down = (
            event.key() == Qt.Key.Key_Down
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
        )

        if self._menu is not None and (alt_down or event.key() == Qt.Key.Key_F4):
            self._popup_menu()
            event.accept()
            return

        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """松开：主半边在原地发出主动作，次半边在原地弹出菜单。"""
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            released = self._hit(event.position().toPoint())
            pressed = self._pressed
            self._pressed = None
            self.update()

            if pressed is SplitButton._Half.SECONDARY and released is pressed:
                self._popup_menu()
                event.accept()
                return

            if pressed is SplitButton._Half.PRIMARY and released is pressed:
                self.clicked.emit()
                event.accept()
                return

            if pressed is not None:
                event.accept()
                return

        self._pressed = None
        self.update()
        super().mouseReleaseEvent(event)

    def _popup_menu(self) -> None:
        """在按钮表面下缘弹出菜单。"""
        if self._menu is None:
            return
        surface = self._surface_rect()
        self._menu.popup(self.mapToGlobal(QPoint(surface.left(), surface.bottom() + 1)))

    def _on_menu_shown(self) -> None:
        self._open = True
        self.update()

    def _on_menu_hidden(self) -> None:
        self._open = False
        self.update()

    def _set_hover(self, half: _Half | None) -> None:
        """记录悬停半边并在变化时重绘。

        Args:
            half (SplitButton._Half | None): 悬停半边；无悬停时为 ``None``。
        """
        if self._hover == half:
            return
        self._hover = half
        self.update()

    # ── 按压回弹 ────────────────────────────────────────────────────

    def _start_rebound(self, half: _Half | None) -> None:
        """为指定半边启动正弦回弹。

        Args:
            half (SplitButton._Half | None): 受回弹的半边；为 ``None`` 时不启动。
        """
        if half is None:
            return
        self._animated = half
        self._press_anim.stop()
        self._press_anim.setStartValue(0.0)
        self._press_anim.setEndValue(1.0)
        self._press_anim.start()

    def _accept_rebound(self, value: float) -> None:
        self._rebound = float(value)
        self.update()

    def _finish_rebound(self) -> None:
        self._rebound = 0.0
        self._animated = None
        self.update()

    def _content_offset(self, half: _Half) -> float:
        """返回某半边图文的纵向下沉量。

        Args:
            half (SplitButton._Half): 目标半边。

        Returns:
            float: 下沉像素，按住期间为静止量，回弹期间再叠加正弦位移。
        """
        # 菜单弹出只改底色，图文不下沉：WinUI 的 FlyoutOpen 亦然
        offset = self.PRESS_SINK if self._pressed is half else 0.0
        if self._animated is half:
            offset += math.sin(math.pi * self._rebound) * self.PRESS_BOUNCE
        return offset

    def _is_sunk(self, half: _Half) -> bool:
        """返回某半边是否处于按压外观。

        菜单弹出只压右半：主半边并未被按过，跟着下沉是误导。
        WinUI 的 ``FlyoutOpen`` 会同时压两半，此处不跟。

        Args:
            half (SplitButton._Half): 目标半边。

        Returns:
            bool: 该半边被按下，或菜单弹出且是右半时为 ``True``。
        """
        if self._pressed is half:
            return True
        return self._open and half is SplitButton._Half.SECONDARY

    # ── 取色 ────────────────────────────────────────────────────────

    def _surface_colors(self, palette: QPalette) -> tuple[QColor, QColor, QColor]:
        """返回填充三色：静止、悬停、按压。

        Args:
            palette (QPalette): 主题调色板。

        Returns:
            tuple[QColor, ...]: 静止填充、悬停填充、按压填充。
        """
        if self._accent is None:
            return (
                palette.color(QPalette.ColorRole.Base),
                palette.color(QPalette.ColorRole.Light),
                palette.color(QPalette.ColorRole.Midlight),
            )
        accent = QColor(self._accent)
        backdrop = palette.color(QPalette.ColorRole.Window)
        return (
            accent,
            self._wash(accent, backdrop, self.ACCENT_HOVER_OPACITY),
            self._wash(accent, backdrop, self.ACCENT_PRESS_OPACITY),
        )

    @staticmethod
    def _wash(fore: QColor, back: QColor, opacity: float) -> QColor:
        """按不透明度把前景色叠在底色上，返回合成色。

        Args:
            fore (QColor): 前景色，即强调色。
            back (QColor): 底色，即画布色。
            opacity (float): 前景色的不透明度，取值 0 到 1。

        Returns:
            QColor: 合成后的实色。
        """
        t = 1.0 - opacity
        return QColor(
            round(fore.red() + (back.red() - fore.red()) * t),
            round(fore.green() + (back.green() - fore.green()) * t),
            round(fore.blue() + (back.blue() - fore.blue()) * t),
        )

    def _label_color(self, palette: QPalette, sunk: bool) -> QColor:
        """返回主半边图文色。

        Args:
            palette (QPalette): 主题调色板。
            sunk (bool): 是否处于按压外观。

        Returns:
            QColor: 强调面取白色，中性面取主文字色；按压时减淡。
        """
        if self._accent is None:
            color = palette.color(QPalette.ColorRole.WindowText)
            return color if not sunk else QColor.fromRgb(color.red(), color.green(), color.blue(), 191)
        return QColor("#ffffff") if not sunk else QColor(255, 255, 255, 179)

    def _chevron_color(self, palette: QPalette, sunk: bool) -> QColor:
        """返回右半边 chevron 色。

        中性面的 chevron 本就比文字淡一档，按压再淡一档；强调面与文字同色。

        Args:
            palette (QPalette): 主题调色板。
            sunk (bool): 是否处于按压外观。

        Returns:
            QColor: chevron 颜色。
        """
        if self._accent is not None:
            return self._label_color(palette, sunk)
        color = palette.color(QPalette.ColorRole.PlaceholderText)
        return color if not sunk else QColor.fromRgb(color.red(), color.green(), color.blue(), 183)

    # ── 绘制 ────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制表面、立体描边、分半高亮、中缝、图文与焦点框。"""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        palette = self._palette()
        full = QRectF(self._surface_rect())
        primary, secondary = self._zones()

        self._paint_surface(painter, palette, full)
        self._paint_highlights(painter, palette, full, primary, secondary)
        self._paint_strokes(painter, palette, full, primary, secondary)
        self._paint_divider(painter, palette, secondary)
        self._paint_content(painter, palette, primary, secondary)
        self._paint_focus(painter, palette, full)

    def _paint_surface(self, painter: QPainter, palette: QPalette, full: QRectF) -> None:
        """绘制静止填充。"""
        rest, _, _ = self._surface_colors(palette)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(rest)
        painter.drawRoundedRect(full, self.RADIUS, self.RADIUS)

    def _paint_highlights(
        self,
        painter: QPainter,
        palette: QPalette,
        full: QRectF,
        primary: QRect,
        secondary: QRect,
    ) -> None:
        """在悬停或按压的半边叠加填充阶梯色。"""
        if not self.isEnabled():
            return
        _, hover, press = self._surface_colors(palette)
        painter.setPen(Qt.PenStyle.NoPen)
        for half, zone in (
            (SplitButton._Half.PRIMARY, primary),
            (SplitButton._Half.SECONDARY, secondary),
        ):
            if self._is_sunk(half):
                color = press
            elif self._hover is half:
                color = hover
            else:
                continue
            painter.setBrush(color)
            painter.save()
            painter.setClipRect(QRectF(zone))
            painter.drawRoundedRect(full, self.RADIUS, self.RADIUS)
            painter.restore()

    def _paint_strokes(
        self,
        painter: QPainter,
        palette: QPalette,
        full: QRectF,
        primary: QRect,
        secondary: QRect,
    ) -> None:
        """绘制立体描边；按压的那一半改用弱化实色，强调面按压时描边消失。"""
        if not self.isEnabled():
            return

        sunk = any(self._is_sunk(half) for half in SplitButton._Half)
        if self._accent is not None:
            if not sunk:
                self._paint_elevation(painter, palette, full)
            return

        self._paint_elevation(painter, palette, full)
        faded = palette.color(QPalette.ColorRole.Shadow)

        for half, zone in (
            (SplitButton._Half.PRIMARY, primary),
            (SplitButton._Half.SECONDARY, secondary),
        ):
            if not self._is_sunk(half):
                continue

            painter.save()
            painter.setClipRect(QRectF(zone))
            self._stroke_ring(painter, QColor(faded), full)
            painter.restore()

    def _paint_elevation(self, painter: QPainter, palette: QPalette, full: QRectF) -> None:
        """绘制平描一圈的描边，明暗只落在上/下横边。

        渐变铺满描边环会把竖边底端一起拉暗，形成「竖边往上长几像素」的脏角；
        竖边因此保持均匀，立体感只由两条横边的强弱差承担。

        Args:
            painter (QPainter): 正在绘制的画笔。
            palette (QPalette): 主题调色板。
            full (QRectF): 按钮表面矩形。
        """
        faint, strong = self._stroke_colors(palette)
        self._stroke_ring(painter, faint, full)

        # 浅色主题强端在下缘、深色在上缘；只描横边，两端各让开圆角半径
        y = full.bottom() - 0.5 if self._flipped() else full.top() + 0.5
        pen = QPen(strong, self.BORDER_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(
            QPointF(full.left() + self.RADIUS, y), QPointF(full.right() - self.RADIUS, y)
        )

    def _stroke_colors(self, palette: QPalette) -> tuple[QColor, QColor]:
        """返回描边两色：弱端与强端。

        Args:
            palette (QPalette): 主题调色板。

        Returns:
            tuple[QColor, ...]: 弱端描边色与强端描边色。
        """
        if self._accent is None:
            return (
                palette.color(QPalette.ColorRole.Shadow),
                palette.color(QPalette.ColorRole.Dark),
            )
        return (
            QColor(255, 255, 255, 20),  # ControlStrokeColorOnAccentDefault
            QColor(0, 0, 0, 55),  # ControlStrokeColorOnAccentTertiary
        )

    def _flipped(self) -> bool:
        """返回立体描边的强端是否在下缘。

        浅色主题的强端在下缘，深色主题在上缘。

        Returns:
            bool: 强端在下缘时为 ``True``。
        """
        app = QApplication.instance()
        window = app.palette().color(QPalette.ColorRole.Window) if isinstance(app, QApplication) else QColor()
        return window.lightness() >= 128


    def _stroke_ring(self, painter: QPainter, color: QColor, full: QRectF) -> None:
        """用实色描出外框一圈。

        Args:
            painter (QPainter): 正在绘制的画笔。
            color (QColor): 描边色。
            full (QRectF): 外框矩形。
        """
        pen = QPen(color, self.BORDER_WIDTH)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            full.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS
        )

    def _paint_divider(self, painter: QPainter, palette: QPalette, secondary: QRect) -> None:
        """绘制通高的中缝发丝线。"""
        if not self.isEnabled():
            return
        color = (
            QColor(self.ACCENT_DIVIDER)
            if self._accent is not None
            else palette.color(QPalette.ColorRole.Shadow)
        )
        # 整像素矩形填充，避免画笔走线在两列之间糊开；高度只到按钮表面
        surface = self._surface_rect()
        painter.fillRect(
            QRect(secondary.left(), surface.top(), self.DIVIDER_WIDTH, surface.height()),
            color,
        )

    def _paint_content(
        self, painter: QPainter, palette: QPalette, primary: QRect, secondary: QRect
    ) -> None:
        """绘制主半边图标与文字、右半边 chevron。"""
        if not self.isEnabled():
            label = QColor(self._chevron_color(palette, False))
            label.setAlphaF(label.alphaF() * 0.4)
            chevron = label
        else:
            label = self._label_color(palette, self._is_sunk(SplitButton._Half.PRIMARY))
            chevron = self._chevron_color(palette, self._is_sunk(SplitButton._Half.SECONDARY))

        primary_offset = self._content_offset(SplitButton._Half.PRIMARY)
        secondary_offset = self._content_offset(SplitButton._Half.SECONDARY)

        layout = QRectF(primary).adjusted(self.PAD_H, 0, -self.PAD_H, 0)
        cursor = layout.left()

        if not self._icon.isNull():
            icon_rect = QRectF(
                cursor, primary.top() + primary_offset, self.ICON_SIZE, primary.height()
            )
            painter.save()
            painter.setOpacity(label.alphaF())
            rerender(self._icon, label.name()).paint(
                painter,
                icon_rect.toRect(),
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled,
            )
            painter.restore()
            cursor += self.ICON_SIZE
            if self._text:
                cursor += self.ICON_GAP

        if self._text:
            painter.setPen(label)
            painter.setFont(self.font())
            painter.save()
            painter.setClipRect(layout)
            painter.drawText(
                QRectF(cursor, primary.top() + primary_offset, layout.right() - cursor, primary.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self._text,
            )
            painter.restore()

        self._paint_chevron(
            painter, QRectF(secondary).translated(0, secondary_offset), chevron
        )

    def _paint_chevron(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        """绘制右半边的弹出指示 chevron。

        Args:
            painter (QPainter): 正在绘制的画笔。
            rect (QRectF): 右半边的绘制矩形。
            color (QColor): chevron 颜色。
        """
        icon_rect = QRectF(
            rect.center().x() - self.CHEVRON_SIZE / 2,
            rect.center().y() - self.CHEVRON_SIZE / 2,
            self.CHEVRON_SIZE,
            self.CHEVRON_SIZE,
        )
        painter.save()
        painter.setOpacity(color.alphaF())
        rerender(SvgIcon.CHEVRON_DOWN, color.name()).paint(
            painter, icon_rect.toRect(), Qt.AlignmentFlag.AlignCenter
        )
        painter.restore()

    def _paint_focus(self, painter: QPainter, palette: QPalette, full: QRectF) -> None:
        """键盘导航时绘制双层焦点框。

        落在按钮表面之外的透明余量里：与 WinUI 的焦点视觉同形，又不被 Qt
        裁在控件矩形内切出角楔。鼠标点击不画，对应 ``UseSystemFocusVisuals``。

        Args:
            painter (QPainter): 正在绘制的画笔。
            palette (QPalette): 主题调色板。
            full (QRectF): 按钮表面矩形。
        """
        if not self.hasKeyboardFocus() or not self.isEnabled():
            return
        outer = QColor(palette.color(QPalette.ColorRole.WindowText))
        inner = QColor(palette.color(QPalette.ColorRole.Window))
        inner.setAlphaF(self.FOCUS_INNER_ALPHA)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for color, width, outset in (
            (outer, self.FOCUS_OUTER_WIDTH, self.FOCUS_OUTER_OUTSET),
            (inner, self.FOCUS_INNER_WIDTH, self.FOCUS_INNER_OUTSET),
        ):
            pen = QPen(color, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawRoundedRect(
                full.adjusted(-outset, -outset, outset, outset),
                self.RADIUS + outset,
                self.RADIUS + outset,
            )
