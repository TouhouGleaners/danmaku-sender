"""账号管理子组件：账号卡片"""
from PySide6.QtCore import QSize, Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QWidget, QApplication
)

from danmaku_sender.types.models.account import AccountCredential
from danmaku_sender.ui.framework.style_loader import get_svg_icon, get_assets_path


class AccountRow(QFrame):
    """单个账号的展示卡片"""

    use_clicked = Signal(AccountCredential)
    edit_clicked = Signal(AccountCredential)
    delete_clicked = Signal(AccountCredential)
    check_clicked = Signal(AccountCredential)

    def __init__(self, account: AccountCredential, is_active: bool = False, parent=None):
        super().__init__(parent)
        self.account = account
        self._check_btn: QPushButton | None = None

        self.setFixedHeight(72)
        self.setObjectName("accountRow")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("active", is_active)

        self._create_ui(is_active)

    def _create_ui(self, is_active: bool):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # 左侧激活指示条
        accent = QFrame()
        accent.setFixedSize(3, 40)
        accent.setObjectName("accountAccent")
        accent.setProperty("active", is_active)
        layout.addWidget(accent)

        # 右侧信息区
        right = QVBoxLayout()
        right.setSpacing(4)

        # 第一行：昵称 + 等级图标 + 状态
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        name_label = QLabel(self.account.name or "未知用户")
        name_label.setObjectName("accountName")
        top_row.addWidget(name_label)

        # 等级图标
        level_icon_name = self._get_level_icon_name()
        if level_icon_name:
            level_label = QLabel()
            pixmap = self._render_level_icon(level_icon_name)
            if not pixmap.isNull():
                level_label.setPixmap(pixmap)
            top_row.addWidget(level_label)

        self._status_icon = QLabel()
        self._status_text = QLabel()
        self._status_text.setObjectName("accountStatus")
        self._update_status(self.account.is_valid)

        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(4)
        status_layout.addWidget(self._status_icon)
        status_layout.addWidget(self._status_text)
        top_row.addWidget(status_widget)
        top_row.addStretch()
        right.addLayout(top_row)

        # 第二行：凭据（由 add_cred 填充）
        self._cred_row = QHBoxLayout()
        self._cred_row.setSpacing(16)
        right.addLayout(self._cred_row)

        layout.addLayout(right, 1)

        # 右侧操作按钮
        actions = [
            ("how_to_reg.svg", "使用", self.use_clicked),
            ("troubleshoot.svg", "检测", self.check_clicked),
            ("edit.svg", "编辑", self.edit_clicked),
            ("delete.svg", "删除", self.delete_clicked),
        ]
        for icon_name, tooltip, signal in actions:
            btn = QPushButton()
            btn.setIcon(get_svg_icon(icon_name))
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(32, 32)
            btn.setObjectName("accountIconBtn")
            btn.clicked.connect(lambda checked=False, s=signal: s.emit(self.account))
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignVCenter)
            if signal is self.check_clicked:
                self._check_btn = btn

    def add_cred(self, prefix: str, masked_value: str, full_value: str):
        """添加一个凭据字段：单击遮蔽值复制到剪贴板"""
        label = QLabel(f"{prefix}: {masked_value}")
        label.setObjectName("credValue")
        label.setCursor(Qt.CursorShape.PointingHandCursor)

        def _on_click(event: QMouseEvent):
            if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                label.setText(f"{prefix}: 按 Ctrl+单击复制完整值")
                QTimer.singleShot(1000, lambda: label.setText(f"{prefix}: {masked_value}"))
                return

            QApplication.clipboard().setText(full_value)
            label.setText(f"{prefix}: 已复制完整值")
            QTimer.singleShot(500, lambda: label.setText(f"{prefix}: {masked_value}"))

        label.mousePressEvent = _on_click
        self._cred_row.addWidget(label)

    def mouseDoubleClickEvent(self, event):
        self.use_clicked.emit(self.account)
        super().mouseDoubleClickEvent(event)

    def set_check_enabled(self, enabled: bool):
        if self._check_btn:
            self._check_btn.setEnabled(enabled)

    def _get_level_icon_name(self) -> str | None:
        """根据账号等级返回对应的图标文件名，未知等级返回 None"""
        level = self.account.level
        if level < 0 or level > 6:
            return None
        if level == 6 and self.account.is_senior_member:
            return "LV6_Lightning.svg"
        return f"LV{level}.svg"

    def _render_level_icon(self, name: str) -> QPixmap:
        """直接从 SVG 渲染等级图标，DPI 感知，保持原始宽高比，固定逻辑高度 12px"""
        logical_h = 12
        svg_path = get_assets_path() / "icons" / "account_levels" / name
        renderer = QSvgRenderer(str(svg_path))
        if not renderer.isValid():
            return QPixmap()

        vb = renderer.viewBoxF()
        aspect = vb.width() / vb.height() if vb.height() > 0 else 1.0
        logical_w = max(1, int(logical_h * aspect))

        dpr = self.devicePixelRatioF()
        phys_w = max(1, int(logical_w * dpr))
        phys_h = max(1, int(logical_h * dpr))

        pixmap = QPixmap(phys_w, phys_h)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, phys_w, phys_h))
        painter.end()
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    def _update_status(self, is_valid: bool | None):
        if is_valid is True:
            self._status_icon.setPixmap(get_svg_icon("check_circle.svg", "#4CAF50").pixmap(16, 16))
            self._status_text.setText("有效")
            self._status_text.setProperty("status", "valid")
        elif is_valid is False:
            self._status_icon.setPixmap(get_svg_icon("cancel.svg", "#E53935").pixmap(16, 16))
            self._status_text.setText("失效")
            self._status_text.setProperty("status", "invalid")
        else:
            self._status_icon.setPixmap(get_svg_icon("help.svg", "#999").pixmap(16, 16))
            self._status_text.setText("未检测")
            self._status_text.setProperty("status", "unknown")
        self._status_text.style().unpolish(self._status_text)
        self._status_text.style().polish(self._status_text)
