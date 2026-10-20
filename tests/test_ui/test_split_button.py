"""SplitButton 的分半命中与主动作信号测试。

约定的边界是两半之分：左半发主动作，右半弹菜单，互不串台。
"""
import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QMenu

from danmaku_sender.ui.framework.split_button import SplitButton


@pytest.fixture
def button(qapp):
    """构造带图文与菜单的分体按钮。"""
    widget = SplitButton()
    widget.setText("发送并监视")
    menu = QMenu()
    menu.addAction("仅发送")
    widget.setMenu(menu)
    widget.resize(widget.sizeHint())
    widget.show()
    qapp.processEvents()
    return widget


def _press(widget: SplitButton, half: SplitButton._Half) -> None:
    """在指定半边内按下左键。"""
    pos = QPointF(widget._zones()[int(half)].center())
    widget.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            pos,
            pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def _release(widget: SplitButton, half: SplitButton._Half) -> None:
    """在指定半边内松开左键。"""
    pos = QPointF(widget._zones()[int(half)].center())
    widget.mouseReleaseEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            pos,
            pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def _click(widget: SplitButton, half: SplitButton._Half) -> None:
    """在指定半边内按下再松开左键。"""
    _press(widget, half)
    _release(widget, half)


class TestSplitButtonProperties:
    def test_text_roundtrip(self, button):
        """setText 后 text() 返回同样的文字"""
        assert button.text() == "发送并监视"

    def test_accent_roundtrip(self, button):
        """setAccent 后 accent() 返回同色，清空后为 None"""
        button.setAccent(QColor("#2ecc71"))
        assert button.accent().name() == "#2ecc71"
        button.setAccent(None)
        assert button.accent() is None

    def test_menu_roundtrip(self, button):
        """setMenu 后 menu() 返回同一个菜单"""
        assert button.menu() is not None
        assert button.menu().actions()[0].text() == "仅发送"

    def test_size_hint_covers_content(self, button):
        """量算宽度不低于右半边宽度，高度固定"""
        hint = button.sizeHint()
        assert hint.width() >= button.SECONDARY_WIDTH
        assert hint.height() == button.HEIGHT

    def test_wider_text_widens_size_hint(self, button):
        """文字变长时量算宽度随之增加"""
        before = button.sizeHint().width()
        button.setText("终止发送并继续监视五分钟后停止")
        assert button.sizeHint().width() > before


class TestSplitButtonActivation:
    def test_primary_half_emits_clicked(self, button):
        """主半边点击发主动作信号"""
        spy = QSignalSpy(button.clicked)
        _click(button, SplitButton._Half.PRIMARY)
        assert spy.count() == 1

    def test_secondary_half_does_not_emit_clicked(self, button):
        """次半边点击不发主动作信号"""
        spy = QSignalSpy(button.clicked)
        _click(button, SplitButton._Half.SECONDARY)
        assert spy.count() == 0

    def test_secondary_half_opens_menu(self, button):
        """次半边原地松开后弹出菜单"""
        _click(button, SplitButton._Half.SECONDARY)
        assert button.menu().isVisible()

    def test_press_primary_release_secondary_does_not_emit(self, button):
        """按下主半边后拖到次半边松开，不发信号"""
        spy = QSignalSpy(button.clicked)
        _press(button, SplitButton._Half.PRIMARY)
        _release(button, SplitButton._Half.SECONDARY)
        assert spy.count() == 0

    def test_non_left_button_is_ignored(self, button):
        """非左键不发信号"""
        spy = QSignalSpy(button.clicked)
        pos = QPointF(button._zones()[int(SplitButton._Half.PRIMARY)].center())
        common = (
            pos,
            pos,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
        button.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, *common))
        button.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, *common))
        assert spy.count() == 0

    def test_disabled_button_emits_nothing(self, button):
        """禁用时不发信号"""
        spy = QSignalSpy(button.clicked)
        button.setEnabled(False)
        _click(button, SplitButton._Half.PRIMARY)
        assert spy.count() == 0


class TestSplitButtonRebound:
    def test_press_starts_rebound_on_that_half(self, button):
        """按下某半边时该半边进入回弹"""
        _press(button, SplitButton._Half.PRIMARY)
        assert button._animated is SplitButton._Half.PRIMARY
        assert button._press_anim.state() != QAbstractAnimation.State.Stopped

    def test_press_sinks_content(self, button):
        """按住期间内容下沉，回弹期间再叠加正弦位移"""
        _press(button, SplitButton._Half.PRIMARY)
        button._rebound = 0.5
        assert button._content_offset(SplitButton._Half.PRIMARY) > button.PRESS_SINK
        assert button._content_offset(SplitButton._Half.SECONDARY) == 0.0

    def test_rebound_is_a_sine_that_returns_to_baseline(self, button):
        """回弹位移起落各半，中段最大、两端为零"""
        button._animated = SplitButton._Half.PRIMARY
        button._pressed = None
        button._rebound = 0.0
        assert button._content_offset(SplitButton._Half.PRIMARY) == pytest.approx(0.0)
        button._rebound = 0.5
        mid = button._content_offset(SplitButton._Half.PRIMARY)
        button._rebound = 1.0
        assert button._content_offset(SplitButton._Half.PRIMARY) == pytest.approx(0.0)
        assert mid == pytest.approx(button.PRESS_BOUNCE)

    def test_hide_cancels_press(self, button):
        """隐藏控件时未完成的按压被取消"""
        _press(button, SplitButton._Half.PRIMARY)
        assert button._pressed is SplitButton._Half.PRIMARY
        button.hide()
        assert button._pressed is None

    def test_disable_cancels_press(self, button):
        """禁用控件时未完成的按压被取消"""
        _press(button, SplitButton._Half.PRIMARY)
        button.setEnabled(False)
        assert button._pressed is None


class TestSplitButtonHitTest:
    def test_primary_zone_hit(self, button):
        """主半边内命中主半边"""
        rect = button._zones()[int(SplitButton._Half.PRIMARY)]
        assert button._hit(rect.center()) is SplitButton._Half.PRIMARY

    def test_secondary_zone_hit(self, button):
        """次半边内命下次半边"""
        rect = button._zones()[int(SplitButton._Half.SECONDARY)]
        assert button._hit(rect.center()) is SplitButton._Half.SECONDARY

    def test_zones_are_contiguous(self, button):
        """两半相接无缝隙，且铺满按钮表面"""
        primary, secondary = button._zones()
        surface = button._surface_rect()
        assert primary.right() + 1 == secondary.left()
        assert primary.left() == surface.left()
        assert secondary.right() == surface.right()

    def test_empty_menu_leaves_secondary_inert(self, qapp):
        """未设菜单时右半边不弹出，也不发主动作"""
        widget = SplitButton()
        widget.setText("发送")
        widget.resize(widget.sizeHint())
        widget.show()
        qapp.processEvents()
        spy = QSignalSpy(widget.clicked)
        _click(widget, SplitButton._Half.SECONDARY)
        assert spy.count() == 0
        assert widget.menu() is None
