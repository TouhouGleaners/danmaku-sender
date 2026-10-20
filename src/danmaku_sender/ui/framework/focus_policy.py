"""应用级焦点约定。

点击不可聚焦区域时撤掉当前焦点。可聚焦控件自行收下焦点，
本约定只处理落在不可聚焦区域上的按压；
落在焦点控件自身子件上的按压不撤。
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget


class ClickAwayFocusFilter(QObject):
    """点击鼠标点不走焦点的控件时撤掉当前焦点。"""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """在鼠标按压时判断落点，命中鼠标点不走焦点的控件则撤掉当前焦点。

        Args:
            obj (QObject): 被监听的对象。
            event (QEvent): 到达的事件。

        Returns:
            bool: 恒为 ``False``，不拦截事件传递。
        """
        if event.type() != QEvent.Type.MouseButtonPress or not isinstance(obj, QWidget):
            return False

        if obj.focusPolicy() & Qt.FocusPolicy.ClickFocus:
            return False

        focused = QApplication.focusWidget()
        if focused is None or focused is obj or focused.isAncestorOf(obj):
            return False

        focused.clearFocus()
        return False
