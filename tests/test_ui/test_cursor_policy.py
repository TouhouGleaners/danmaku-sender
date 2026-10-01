"""AutoHandCursorFilter 的行为测试。

约定的边界是动作与控件之分：按钮执行命令给手型，改变值的控件保持箭头。
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton, QSlider, QToolButton

from danmaku_sender.ui.framework.cursor_policy import AutoHandCursorFilter


@pytest.fixture
def app_with_policy(qapp):
    """装上策略，用完卸载，避免影响其它用例。"""
    policy = AutoHandCursorFilter(qapp)
    qapp.installEventFilter(policy)
    yield qapp
    qapp.removeEventFilter(policy)


def _polished(app, widget):
    widget.show()
    app.processEvents()
    return widget


class TestAutoHandCursorFilter:
    @pytest.mark.parametrize("cls", [QPushButton, QToolButton])
    def test_buttons_get_hand(self, app_with_policy, cls):
        """按钮点击执行命令，给手型"""
        widget = _polished(app_with_policy, cls())
        assert widget.cursor().shape() == Qt.CursorShape.PointingHandCursor

    @pytest.mark.parametrize("cls", [QCheckBox, QComboBox, QSlider])
    def test_value_controls_keep_arrow(self, app_with_policy, cls):
        """改变值的控件不算动作，保持平台默认箭头"""
        widget = _polished(app_with_policy, cls())
        assert widget.cursor().shape() == Qt.CursorShape.ArrowCursor

    def test_non_button_keeps_arrow(self, app_with_policy):
        widget = _polished(app_with_policy, QLabel("text"))
        assert widget.cursor().shape() == Qt.CursorShape.ArrowCursor

    def test_explicit_cursor_is_preserved(self, app_with_policy):
        """显式设置过的光标不被覆盖"""
        widget = QPushButton("x")
        widget.setCursor(Qt.CursorShape.CrossCursor)
        _polished(app_with_policy, widget)
        assert widget.cursor().shape() == Qt.CursorShape.CrossCursor

    def test_explicit_arrow_is_preserved(self, app_with_policy):
        """显式设为箭头是关闭本约定的手段，不得改成小手"""
        widget = QPushButton("x")
        widget.setCursor(Qt.CursorShape.ArrowCursor)
        _polished(app_with_policy, widget)
        assert widget.cursor().shape() == Qt.CursorShape.ArrowCursor
