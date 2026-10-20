"""应用级焦点约定

点到空白处要撤掉当前焦点。Qt 里 ``NoFocus`` 容器收到按压并不移动焦点，
聚焦的控件会一直保持焦点；Windows 的惯例是点到非控件处即取消焦点。

约定的边界是**焦点，不是控件**：可聚焦控件自行收下焦点，本约定只处理
落在不可聚焦区域上的按压。落在焦点控件自身子件上的按压也不撤，避免按钮里的
图标、文字标签把焦点抢走。
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
