from enum import IntEnum

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from danmaku_sender.config import Settings
from danmaku_sender.config.theme_config import FontChoice, ThemeMode
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import SendMode
from danmaku_sender.ui.framework.breadcrumb_bar import BreadcrumbBar
from danmaku_sender.ui.framework.fonts import PROFILES
from danmaku_sender.ui.framework.form_binder import LiveFormBinder
from danmaku_sender.ui.framework.icons import SvgIcon, rerender
from danmaku_sender.ui.framework.number_box import DoubleNumberBox, NumberBox
from danmaku_sender.ui.framework.settings_row import ICON_SIZE, NavRow, SettingsRow
from danmaku_sender.ui.framework.wrap_layout import WrapLayout


class Subpage(IntEnum):
    """设置页子页，取值即栈下标。

    Attributes:
        DIRECTORY: 目录页，列出全部分类。
        SYSTEM: 系统子页。
        NETWORK: 网络子页。
        SEND: 发送子页。
    """

    DIRECTORY = 0
    SYSTEM = 1
    NETWORK = 2
    SEND = 3


class SettingsPage(QWidget):
    """全局设置页。

    属于实时修改表单：
    无「保存」按钮，控件变更通过 LiveFormBinder立即写入配置模型。
    主题需要即时生效，因此在 ``after_write`` 中发射 ``themeApplied``。
    页面显示时调用 ``fill()`` 刷新控件值。

    页面为子页导航：目录页列出三个分类，各分类为独立子页。
    页头为路径式导航条，末段是当前子页，其余段可点击返回目录。
    """

    themeApplied = Signal(ThemeMode)  # 主题已写入配置，可立即应用
    fontApplied = Signal(FontChoice)  # 字体档位已写入配置，可立即应用

    def __init__(self, state: AppState, settings: Settings):
        super().__init__()

        self.state = state
        self.settings = settings
        self._icon_jobs: list[tuple[QLabel, QIcon]] = []
        self._create_ui()

    # ── 排版构件 ────────────────────────────────────────────────────────

    def _icon(self, icon: QIcon) -> QLabel:
        """构造设置行图标，居中于占位框内。

        Args:
            icon (QIcon): 图标来源；主题切换后可据此重绘。

        Returns:
            QLabel: 承载图标的标签。
        """
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_jobs.append((label, icon))
        self._paint_icon(label, icon)
        return label

    @staticmethod
    def _paint_icon(label: QLabel, icon: QIcon) -> None:
        """按当前调色板渲染图标到标签。

        Args:
            label (QLabel): 承载图标的标签。
            icon (QIcon): 图标来源。
        """
        label.setPixmap(rerender(icon).pixmap(ICON_SIZE, ICON_SIZE))

    def refresh_icons(self) -> None:
        """主题切换后按当前调色板重绘设置行图标。"""
        for label, icon in self._icon_jobs:
            self._paint_icon(label, icon)

    def _row(
        self,
        title: str,
        subtitle: str,
        icon,
        trailing: QWidget | None = None,
        danger: bool = False,
    ) -> SettingsRow:
        return SettingsRow(
            title, subtitle, trailing=trailing, icon=self._icon(icon), danger=danger
        )

    def _nav_row(self, title: str, subtitle: str, icon, target: Subpage) -> NavRow:
        """构造目录页的可点条目，点击进入对应子页。

        Args:
            title (str): 分类名称。
            subtitle (str): 该分类的内容概述。
            icon: 分类图标。
            target (Subpage): 目标子页。

        Returns:
            NavRow: 可点的目录条目。
        """
        row = NavRow(
            title,
            subtitle,
            target,
            trailing=self._icon(SvgIcon.CHEVRON_RIGHT),
            icon=self._icon(icon),
        )
        row.activated.connect(self._stack.setCurrentIndex)
        return row

    def _subpage(self, trail: list[str]) -> tuple[QScrollArea, QVBoxLayout]:
        """构造子页骨架：滚动容器与内容布局，页头已排入布局。

        Args:
            trail (list[str]): 面包屑路径，末段为当前子页名。

        Returns:
            tuple[QScrollArea, QVBoxLayout]: 入栈的滚动容器，以及待填充的内容布局。
        """
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(48, 34, 48, 48)
        body.setSpacing(4)

        breadcrumb = BreadcrumbBar(content)
        breadcrumb.setItems(trail)
        breadcrumb.itemActivated.connect(
            lambda _index: self._stack.setCurrentIndex(Subpage.DIRECTORY)
        )
        body.addWidget(breadcrumb)
        body.addSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll, body

    @staticmethod
    def _spin_with_unit(spin: QWidget, unit: str) -> QWidget:
        """把数值框与单位拼成一小组件，供设置行尾部使用。"""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(spin)
        lay.addWidget(QLabel(unit))
        return box

    # ── 页面构建 ────────────────────────────────────────────────────────

    def _create_ui(self):
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_directory())     # Subpage.DIRECTORY
        self._stack.addWidget(self._build_system_page())   # Subpage.SYSTEM
        self._stack.addWidget(self._build_network_page())  # Subpage.NETWORK
        self._stack.addWidget(self._build_send_page())     # Subpage.SEND

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

    def _build_directory(self) -> QWidget:
        """构建目录页：三个分类条目加页脚提示。"""
        page, body = self._subpage(["设置"])

        body.addWidget(self._nav_row("系统", "界面主题、字体与休眠行为", SvgIcon.SETTINGS, Subpage.SYSTEM))
        body.addWidget(self._nav_row("网络", "网络请求的代理方式", SvgIcon.SYNC_ALT, Subpage.NETWORK))
        body.addWidget(self._nav_row("发送", "发送间隔、爆发节奏与停止条件", SvgIcon.TUNE, Subpage.SEND))
        body.addStretch()

        info_label = QLabel("💡 账号管理请点击左上角头像区域。")
        info_label.setStyleSheet("color: gray; font-size: 12px;")
        body.addWidget(info_label)
        return page

    def _build_system_page(self) -> QWidget:
        """构建系统子页。"""
        page, body = self._subpage(["设置", "系统"])

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("跟随系统", ThemeMode.SYSTEM)
        self.theme_combo.addItem("浅色模式", ThemeMode.LIGHT)
        self.theme_combo.addItem("深色模式", ThemeMode.DARK)
        self.theme_combo.setFixedWidth(160)
        body.addWidget(
            self._row("界面主题", "选择浅色、深色，或跟随系统外观", SvgIcon.GRADIENT, self.theme_combo)
        )

        self.font_combo = QComboBox()
        font_tips = {
            FontChoice.MISANS: "随附字体，渲染经校准",
            FontChoice.YAHEI: "保留细体锐利，避免粗体被过度加粗",
            FontChoice.SYSTEM: "使用系统默认字体，渲染交给平台",
        }
        for choice in FontChoice:
            self.font_combo.addItem(PROFILES[choice].label, choice)
            self.font_combo.setItemData(
                self.font_combo.count() - 1, font_tips[choice], Qt.ItemDataRole.ToolTipRole
            )
        self.font_combo.setFixedWidth(160)
        body.addWidget(
            self._row("界面字体", "切换字体会同步调整笔画渲染，保持清晰", SvgIcon.SHORT_TEXT, self.font_combo)
        )

        self.prevent_sleep_checkbox = QCheckBox()
        self.prevent_sleep_checkbox.setChecked(True)
        self.prevent_sleep_checkbox.setToolTip("保持网络和CPU运行，但允许屏幕关闭。")
        body.addWidget(
            self._row(
                "阻止电脑休眠",
                "任务运行期间保持网络与处理器工作，屏幕仍可关闭",
                SvgIcon.START,
                self.prevent_sleep_checkbox,
            )
        )
        body.addStretch()
        return page

    def _build_network_page(self) -> QWidget:
        """构建网络子页。"""
        page, body = self._subpage(["设置", "网络"])

        self.proxy_checkbox = QCheckBox()
        self.proxy_checkbox.setChecked(True)
        self.proxy_checkbox.setToolTip("启用后，程序将使用系统设置的代理服务器进行网络请求。")
        body.addWidget(
            self._row(
                "使用系统代理",
                "经由系统设置的代理服务器发起网络请求",
                SvgIcon.SYNC_ALT,
                self.proxy_checkbox,
            )
        )
        body.addStretch()
        return page

    def _build_send_page(self) -> QWidget:
        """构建发送子页。"""
        page, body = self._subpage(["设置", "发送"])

        self.send_mode_combo = QComboBox()
        self.send_mode_combo.addItem("发送并监视", SendMode.SEND_AND_MONITOR)
        self.send_mode_combo.addItem("仅发送", SendMode.SEND_ONLY)
        self.send_mode_combo.setFixedWidth(160)
        self.send_mode_combo.setAccessibleName("发送模式")
        body.addWidget(
            self._row(
                "发送模式",
                "发送期间是否一并核销已发出的弹幕",
                SvgIcon.MONITOR,
                self.send_mode_combo,
            )
        )

        self.min_delay = DoubleNumberBox()
        self.min_delay.setRange(0.1, 60.0)
        self.min_delay.setValue(8.0)
        self.min_delay.setSingleStep(0.5)
        self.min_delay.setAccessibleName("随机间隔 下限")
        self.max_delay = DoubleNumberBox()
        self.max_delay.setRange(0.1, 60.0)
        self.max_delay.setValue(8.5)
        self.max_delay.setSingleStep(0.5)
        self.max_delay.setAccessibleName("随机间隔 上限")

        delay_box = QWidget()
        delay_lay = QHBoxLayout(delay_box)
        delay_lay.setContentsMargins(0, 0, 0, 0)
        delay_lay.setSpacing(6)
        delay_lay.addWidget(self.min_delay)
        delay_lay.addWidget(QLabel("至"))
        delay_lay.addWidget(self.max_delay)
        delay_lay.addWidget(QLabel("秒"))
        body.addWidget(
            self._row("随机间隔", "相邻两条弹幕之间的发送间隔", SvgIcon.TUNE, delay_box)
        )

        self.burst_enabled_cb = QCheckBox()
        self.burst_enabled_cb.setToolTip("勾选启用爆发模式：每发 N 条后自动休息一段时间")
        self.burst_enabled_cb.toggled.connect(self._on_burst_toggled)
        self.burst_enabled_cb.setAccessibleName("爆发模式")

        self.burst_size = NumberBox()
        self.burst_size.setRange(2, 100)
        self.burst_size.setValue(3)
        self.burst_size.setAccessibleName("爆发模式 每轮条数")
        self.burst_rest_min = DoubleNumberBox()
        self.burst_rest_min.setRange(0.0, 300.0)
        self.burst_rest_min.setValue(10.0)
        self.burst_rest_min.setAccessibleName("爆发模式 休息下限")
        self.burst_rest_max = DoubleNumberBox()
        self.burst_rest_max.setRange(0.0, 300.0)
        self.burst_rest_max.setValue(20.0)
        self.burst_rest_max.setAccessibleName("爆发模式 休息上限")
        self._burst_controls: list[QWidget] = [
            self.burst_size, self.burst_rest_min, self.burst_rest_max
        ]

        burst_box = QWidget()
        burst_lay = WrapLayout(burst_box, spacing=6)
        burst_lay.addWidget(self.burst_enabled_cb)
        burst_lay.addWidget(QLabel("每"))
        burst_lay.addWidget(self.burst_size)
        burst_lay.addWidget(QLabel("条，休息"))
        burst_lay.addWidget(self.burst_rest_min)
        burst_lay.addWidget(QLabel("至"))
        burst_lay.addWidget(self.burst_rest_max)
        burst_lay.addWidget(QLabel("秒"))
        body.addWidget(
            self._row("爆发模式", "连续发送若干条后暂停一段时间再继续", SvgIcon.AUTO_AWESOME, burst_box)
        )

        self.delay_between = DoubleNumberBox()
        self.delay_between.setRange(0.0, 300.0)
        self.delay_between.setSingleStep(5.0)
        self.delay_between.setAccessibleName("任务间隔")
        body.addWidget(
            self._row(
                "任务间隔",
                "相邻两个任务之间的等待时间",
                SvgIcon.SYNC_ALT,
                self._spin_with_unit(self.delay_between, "秒"),
            )
        )

        body.addSpacing(6)
        danger_heading = QLabel("危险区")
        danger_heading.setObjectName("settingsSectionTitle")
        body.addWidget(danger_heading)

        self.allow_duplicates = QCheckBox()
        self.allow_duplicates.setAccessibleName("允许重复发送")
        body.addWidget(
            self._row(
                "允许重复发送",
                "开启后，发送将不再比对数据库。已经发出的弹幕会允许再次发送，视频内会出现重复。",
                SvgIcon.CONTENT_COPY,
                self.allow_duplicates,
                danger=True,
            )
        )
        body.addStretch()
        return page

    def _on_burst_toggled(self, checked: bool):
        for ctrl in self._burst_controls:
            ctrl.setEnabled(checked)

    @Slot(str, object)
    def _on_config_written(self, _field: str, _value: object) -> None:
        """配置写回成功 → 广播变更，由 MainWindow 防抖落盘。"""
        self.state.configChanged.emit()

    @Slot(str, object)
    def _on_theme_written(self, _field: str, value: object) -> None:
        """主题写回成功 → 广播变更并立刻应用主题。"""
        self.state.configChanged.emit()
        self.themeApplied.emit(value)

    @Slot(str, object)
    def _on_font_written(self, _field: str, value: object) -> None:
        """字体写回成功 → 广播变更并立刻应用字体。"""
        self.state.configChanged.emit()
        self.fontApplied.emit(value)

    def init_bindings(self) -> None:
        """将 UI 控件与配置模型进行单向写绑定"""
        # 主题：写成功后立刻广播，驱动 ThemeService 应用
        LiveFormBinder.bind(
            self.theme_combo,
            self.settings.theme_config,
            "theme_mode",
            after_write=self._on_theme_written,
        )
        LiveFormBinder.bind(
            self.font_combo,
            self.settings.theme_config,
            "font_name",
            after_write=self._on_font_written,
        )

        # 全局系统设置（跨发送器/监视器共享，单绑一份）
        LiveFormBinder.bind(self.prevent_sleep_checkbox, self.settings.global_config, "prevent_sleep", after_write=self._on_config_written)
        LiveFormBinder.bind(self.proxy_checkbox, self.settings.global_config, "use_system_proxy", after_write=self._on_config_written)

        # 发送节奏（单个任务内）
        pacing = self.settings.sender_config.pacing
        LiveFormBinder.bind(self.min_delay, pacing, "min_delay", after_write=self._on_config_written)
        LiveFormBinder.bind(self.max_delay, pacing, "max_delay", after_write=self._on_config_written)
        LiveFormBinder.bind(self.burst_enabled_cb, pacing, "burst_enabled", after_write=self._on_config_written)
        LiveFormBinder.bind(self.burst_size, pacing, "burst_size", after_write=self._on_config_written)
        LiveFormBinder.bind(self.burst_rest_min, pacing, "rest_min", after_write=self._on_config_written)
        LiveFormBinder.bind(self.burst_rest_max, pacing, "rest_max", after_write=self._on_config_written)

        # 整轮运行模式
        sender = self.settings.sender_config
        LiveFormBinder.bind(self.send_mode_combo, sender, "mode", after_write=self._on_config_written)

        # 整队规则（一次队列运行共享，不随单个任务走）
        queue = self.settings.sender_config.queue
        LiveFormBinder.bind(self.delay_between, queue, "delay_between_tasks", after_write=self._on_config_written)
        LiveFormBinder.bind(self.allow_duplicates, queue, "allow_duplicates", after_write=self._on_config_written)

    def showEvent(self, event):
        """打开页面时从状态重读控件值（无隐式同步）"""
        super().showEvent(event)
        LiveFormBinder.fill(self)
