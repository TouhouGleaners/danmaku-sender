"""ToggleSwitch 宿主与 QML 开关的契约测试。"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest

from danmaku_sender.ui.framework.form_binder import base as form_binder_base
from danmaku_sender.ui.framework.toggle_switch import ToggleSwitch


@pytest.fixture()
def switch(qapp):
    """已显示的开关；键事件需要活动焦点，显示后交由用例自行聚焦。"""
    widget = ToggleSwitch()
    widget.show()
    qapp.processEvents()
    yield widget
    widget.deleteLater()


class TestToggleSwitch:
    def test_loads_with_default_state(self, switch: ToggleSwitch) -> None:
        assert switch.rootObject() is not None
        assert switch.isOn() is False

    def test_set_is_on_emits_only_on_change(self, switch: ToggleSwitch) -> None:
        fired: list[bool] = []
        switch.toggled.connect(fired.append)
        switch.setIsOn(True)
        switch.setIsOn(True)
        assert switch.isOn() is True
        assert fired == [True]

    def test_emit_unchanged_repairs_handlers(self, switch: ToggleSwitch) -> None:
        """值未变化时补发信号，驱动依赖切换状态的联动。"""
        fired: list[bool] = []
        switch.toggled.connect(fired.append)
        form_binder_base._WidgetAdapter.emit_unchanged(switch)
        assert fired == [False]

    def test_keyboard_toggles(self, switch: ToggleSwitch, qapp) -> None:
        switch.setFocus()
        qapp.processEvents()
        QTest.keyClick(switch, Qt.Key.Key_Space)
        assert switch.isOn() is True

    def test_keyboard_focus_shows_focus_ring(self, switch: ToggleSwitch) -> None:
        QCoreApplication.sendEvent(switch, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        assert switch.rootObject().property("focusRingVisible") is True

    def test_mouse_focus_hides_focus_ring(self, switch: ToggleSwitch) -> None:
        QCoreApplication.sendEvent(switch, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        QTest.mousePress(switch, Qt.MouseButton.LeftButton)
        assert switch.rootObject().property("focusRingVisible") is False

    def test_disabled_blocks_toggle_and_syncs_to_qml(self, switch: ToggleSwitch, qapp) -> None:
        switch.setIsOn(True)
        switch.setEnabled(False)
        assert switch.rootObject().property("enabled") is False
        switch.setFocus()
        qapp.processEvents()
        QTest.keyClick(switch, Qt.Key.Key_Space)
        assert switch.isOn() is True
