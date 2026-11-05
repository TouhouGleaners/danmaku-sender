"""历史页 QML 场景的桥接对象。"""
from PySide6.QtCore import Property, QObject, Signal, Slot


class HistoryBridge(QObject):
    """历史页 QML 侧的事件入口与状态出口。

    QML 经槽（@Slot）上报事件，持有方连信号（Signal）接收；
    记录动作作用于 pick_record 挑定的记录，不在动作时刻按行号回查，避免模型刷新后动作指向其他记录；
    任务摘要经 summaryTitle / summaryPart / summaryRate / summaryStats 属性下发。

    Typical usage example::

        bridge = HistoryBridge(self)
        bridge.treeRowPicked.connect(self._on_tree_row_picked)
        bridge.set_summary("BV1xx  标题", "P1  分P", "95%", stats)

    Attributes:
        treeRowPicked (Signal): 选中树行，载荷为行号。
        searchSubmitted (Signal): 搜索提交，载荷为关键词。
        statusSelected (Signal): 状态筛选变更，载荷为筛选项索引。
        refreshRequested (Signal): 请求刷新表格。
        verifyAllRequested (Signal): 请求批量核销。
        recordPicked (Signal): 挑定记录动作对象，载荷为行号。
        openRecordRequested (Signal): 打开挑定记录的完整详情。
        openBrowserRequested (Signal): 浏览器打开挑定记录所在分P。
        verifyPartRequested (Signal): 核销挑定记录所在分P的所有弹幕。
        copyBvidRequested (Signal): 复制挑定记录的 BVID。
        copyContentRequested (Signal): 复制挑定记录的弹幕内容。
        summaryChanged (Signal): 任务摘要变更广播。
        emptyChanged (Signal): 表格空态提示变更广播。
    """

    treeRowPicked = Signal(int)
    searchSubmitted = Signal(str)
    statusSelected = Signal(int)
    refreshRequested = Signal()
    verifyAllRequested = Signal()
    recordPicked = Signal(int)
    openRecordRequested = Signal()
    openBrowserRequested = Signal()
    verifyPartRequested = Signal()
    copyBvidRequested = Signal()
    copyContentRequested = Signal()
    summaryChanged = Signal()
    emptyChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._summary_title = ""
        self._summary_part = ""
        self._summary_rate = ""
        self._summary_stats: list[dict[str, str]] = []
        self._empty_title = ""
        self._empty_description = ""
        self._empty_action_text = ""

    @Property(str, notify=summaryChanged)
    def summaryTitle(self) -> str:
        """任务标识上行，形如 ``BV1xx  标题``（BV 号与视频标题）。"""
        return self._summary_title

    @Property(str, notify=summaryChanged)
    def summaryPart(self) -> str:
        """任务标识下行，形如 ``P1  分P``（分P序号与分P标题）；无内容时为空串。"""
        return self._summary_part

    @Property(str, notify=summaryChanged)
    def summaryRate(self) -> str:
        """存活率文本；无统计时为 ``-``。"""
        return self._summary_rate

    @Property(list, notify=summaryChanged)
    def summaryStats(self) -> list[dict[str, str]]:
        """汇总指标序列，每项含 label 与 value。"""
        return self._summary_stats

    def set_summary(self, title: str, part: str, rate: str, stats: list[dict[str, str]]) -> None:
        """更新任务摘要。

        Args:
            title (str): 任务标识上行。
            part (str): 任务标识下行；空串表示不显示下行。
            rate (str): 存活率文本。
            stats (list[dict[str, str]]): 汇总指标序列，每项含 label 与 value。
        """
        self._summary_title = title
        self._summary_part = part
        self._summary_rate = rate
        self._summary_stats = stats
        self.summaryChanged.emit()

    @Property(str, notify=emptyChanged)
    def emptyTitle(self) -> str:
        """表格空态提示标题；查询失败时为失败标题，与「无记录」区分。"""
        return self._empty_title

    @Property(str, notify=emptyChanged)
    def emptyDescription(self) -> str:
        """表格空态提示说明；留空则不显示。"""
        return self._empty_description

    @Property(str, notify=emptyChanged)
    def emptyActionText(self) -> str:
        """表格空态动作按钮文字；留空则不显示按钮。"""
        return self._empty_action_text

    def set_empty(self, title: str, description: str = "", action_text: str = "") -> None:
        """更新表格空态提示。

        Args:
            title (str): 主标题。
            description (str): 说明文字；留空则不显示。
            action_text (str): 动作按钮文字；留空则不显示按钮。
        """
        self._empty_title = title
        self._empty_description = description
        self._empty_action_text = action_text
        self.emptyChanged.emit()

    @Slot(int)
    def pick_tree_row(self, row: int) -> None:
        """QML 树行单击入口。"""
        self.treeRowPicked.emit(row)

    @Slot(str)
    def search(self, text: str) -> None:
        """QML 搜索提交入口。"""
        self.searchSubmitted.emit(text.strip())

    @Slot(int)
    def select_status(self, index: int) -> None:
        """QML 状态筛选入口。"""
        self.statusSelected.emit(index)

    @Slot()
    def refresh(self) -> None:
        """QML 刷新按钮入口。"""
        self.refreshRequested.emit()

    @Slot()
    def verify_all(self) -> None:
        """QML 验证全部入口。"""
        self.verifyAllRequested.emit()

    @Slot(int)
    def pick_record(self, row: int) -> None:
        """QML 行双击与右键入口：挑定后续记录动作的对象。"""
        self.recordPicked.emit(row)

    @Slot()
    def open_record(self) -> None:
        """QML 打开完整详情入口。"""
        self.openRecordRequested.emit()

    @Slot()
    def open_in_browser(self) -> None:
        """QML 浏览器打开入口。"""
        self.openBrowserRequested.emit()

    @Slot()
    def verify_part(self) -> None:
        """QML 核销该分P入口。"""
        self.verifyPartRequested.emit()

    @Slot()
    def copy_bvid(self) -> None:
        """QML 复制 BVID 入口。"""
        self.copyBvidRequested.emit()

    @Slot()
    def copy_content(self) -> None:
        """QML 复制弹幕内容入口。"""
        self.copyContentRequested.emit()
