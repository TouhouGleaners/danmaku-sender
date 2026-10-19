"""键盘焦点来源跟踪。

WinUI 的系统焦点视觉（``UseSystemFocusVisuals``）只在键盘导航时出现，
鼠标点击移动焦点时不画焦点框。本混入为自绘控件记录焦点来源。

Typical usage example::

    class MyControl(KeyboardFocus, QWidget):
        def paintEvent(self, event):
            ...
            if self.hasKeyboardFocus():
                self._paint_focus_ring()
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent


class KeyboardFocus:
    """记录当前焦点是否来自键盘导航。

    子类须位于 QWidget 子类之前，以便 ``super()`` 继续走到 Qt 侧。
    """

    _keyboard_focus: bool = False

    _KEYBOARD_REASONS = frozenset(
        {
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        }
    )

    def hasKeyboardFocus(self) -> bool:
        """返回当前焦点是否来自键盘导航。

        Returns:
            bool: 由 Tab / 反向 Tab / 快捷键取得焦点时为 ``True``。
        """
        return self._keyboard_focus

    def focusInEvent(self, event: QFocusEvent) -> None:
        """记录焦点来源并重绘。"""
        super().focusInEvent(event)  # type: ignore[misc]
        self._keyboard_focus = event.reason() in self._KEYBOARD_REASONS
        self.update()

    def focusOutEvent(self, event: QEvent) -> None:
        """清除键盘焦点标记并重绘。"""
        super().focusOutEvent(event)  # type: ignore[misc]
        self._keyboard_focus = False
        self.update()
