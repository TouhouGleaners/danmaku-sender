"""承载 QML ToggleSwitch 的二元开关控件（WinUI 3 形制）。"""

import logging
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal, Slot
from PySide6.QtWidgets import QWidget

from danmaku_sender.ui.framework.qml_host import QmlHost

QML_PATH = Path(__file__).resolve().parent / "qml" / "ToggleSwitch.qml"

logger = logging.getLogger(__name__)


class ToggleSwitch(QmlHost):
    """以 QML ToggleSwitch 为内容的二元开关控件。

    对外沿用开关契约（isOn / setIsOn / toggled），与 form_binder 的开关适配对齐；
    明暗随主题令牌换装，宿主清屏色由 QmlHost 同步。

    Args:
        parent (QWidget | None): 父控件。

    Typical usage example::

        switch = ToggleSwitch()
        switch.setIsOn(True)
        layout.addWidget(switch)
    """

    toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(QML_PATH, properties={"host": self}, parent=parent)
        self.setFixedSize(40, 20)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.rootObject().setProperty("enabled", self.isEnabled())

    def changeEvent(self, event: QEvent) -> None:
        """启用状态变更后同步到 QML 根对象。"""
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self.rootObject().setProperty("enabled", self.isEnabled())

    @Slot(bool)
    def notify_toggled(self, value: bool) -> None:
        """接收 QML 侧的用户切换，转为 toggled 信号。

        Args:
            value (bool): 新状态。
        """
        self.toggled.emit(value)

    def isOn(self) -> bool:
        """读取开关状态。

        Returns:
            bool: 开启为 True。
        """
        return bool(self.rootObject().property("checked"))

    def setIsOn(self, value: bool) -> None:
        """设置开关状态；值变化时发 toggled（与 QCheckBox.setChecked 同语义）。

        Args:
            value (bool): 目标状态。
        """
        if self.isOn() == value:
            return
        self.rootObject().setProperty("checked", value)
        self.toggled.emit(value)
