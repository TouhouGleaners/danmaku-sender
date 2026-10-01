"""应用级光标约定

推压式按钮的悬停光标统一为手型。约定的边界是**动作，不是控件**：按钮点击
下去执行命令，因此给手型；勾选框、单选框、组合框、滑块、输入框改变的是值，
属于控件，沿用平台默认的箭头光标。

Qt 样式表不支持 `cursor` 属性，无法用一条 QSS 规则表达；逐个控件调用
`setCursor` 又零散且容易遗漏，因此在应用级按控件类型约定一次。

手型在这里是 hover 观感不足时的显式补充。若将来补齐 Fluent 式 hover
（按钮自身的悬停底色足以传达可交互），本约定应整体移除。
"""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QPushButton, QToolButton


class AutoHandCursorFilter(QObject):
    """为推压式按钮自动设置手型光标。

    覆盖 QPushButton 与 QToolButton。QCheckBox、QRadioButton、QComboBox
    等改变值的控件不在此列；响应点击的 QLabel、头像区等非按钮控件同样
    不属于本约定，仍需各自调用 ``setCursor``。
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """在控件 polish 时设置手型光标。

        Args:
            obj: 被监听的对象。
            event: 到达的事件。

        Returns:
            bool: 恒为 False，不拦截事件传递。
        """
        if event.type() != QEvent.Type.Polish:
            return False

        # 用字面量元组收窄类型，obj 的静态类型是 QObject，没有 setCursor
        if isinstance(obj, (QPushButton, QToolButton)) and obj.cursor().shape() == Qt.CursorShape.ArrowCursor:
            obj.setCursor(Qt.CursorShape.PointingHandCursor)

        return False
