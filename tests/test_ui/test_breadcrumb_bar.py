"""BreadcrumbBar 的路径排布与回溯交互测试。

约定的边界是回溯与定位之分：末段是当前位置不可点，其余段点击发回溯信号。
"""
import itertools

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from danmaku_sender.ui.framework.breadcrumb_bar import BreadcrumbBar


@pytest.fixture
def bar(qapp):
    """构造铺满三条段路径的导航条。"""
    widget = BreadcrumbBar()
    widget.setItems(["设置", "系统", "显示"])
    widget.resize(600, widget.ROW_HEIGHT)
    widget.show()
    qapp.processEvents()
    return widget


def _press(widget: BreadcrumbBar, x: float, y: float) -> None:
    """在控件坐标系下按下左键。"""
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(event)


class TestBreadcrumbPath:
    def test_items_roundtrip(self, bar):
        """setItems 后 items() 返回同样的段文本"""
        assert bar.items() == ["设置", "系统", "显示"]

    def test_layout_alternates_segment_and_separator(self, bar):
        """排布结果为段与分隔槽交替，段数比分隔槽数多一"""
        records = bar._records
        segments = [r for r in records if r.index is not None]
        separators = [r for r in records if r.index is None]
        assert len(segments) == 3
        assert len(separators) == 2
        assert [r.index for r in segments] == [0, 1, 2]

    def test_records_are_left_to_right(self, bar):
        """各绘制单元自左至右排布"""
        rects = [r.rect for r in bar._records]
        for earlier, later in itertools.pairwise(rects):
            assert earlier.right() == pytest.approx(later.x())


class TestBreadcrumbActivation:
    def test_ancestor_segment_reports_index(self, bar):
        """点击上级段发回溯信号并带上段下标"""
        fired = []
        bar.itemActivated.connect(fired.append)
        _press(bar, bar._records[0].rect.x() + 5, bar.ROW_HEIGHT / 2)
        assert fired == [0]

    def test_each_ancestor_reports_its_own_index(self, bar):
        """中间段点击报出自身下标"""
        fired = []
        bar.itemActivated.connect(fired.append)
        middle = bar._records[2].rect
        _press(bar, middle.x() + 5, bar.ROW_HEIGHT / 2)
        assert fired == [1]

    def test_last_segment_is_not_clickable(self, bar):
        """末段是当前位置，点击不发信号"""
        fired = []
        bar.itemActivated.connect(fired.append)
        last = bar._records[-1].rect
        _press(bar, last.x() + 5, bar.ROW_HEIGHT / 2)
        assert fired == []

    def test_separator_is_not_clickable(self, bar):
        """分隔槽不发信号"""
        fired = []
        bar.itemActivated.connect(fired.append)
        separator = bar._records[1].rect
        _press(bar, separator.center().x(), separator.center().y())
        assert fired == []

    def test_non_left_button_is_ignored(self, bar):
        """非左键不发信号"""
        fired = []
        bar.itemActivated.connect(fired.append)
        pos = QPointF(bar._records[0].rect.x() + 5, bar.ROW_HEIGHT / 2)
        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            pos,
            pos,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
        bar.mousePressEvent(event)
        assert fired == []


class TestBreadcrumbHitTest:
    def test_ancestor_hit_reports_index(self, bar):
        """上级段上返回段下标"""
        assert bar._hit(QPointF(bar._records[0].rect.x() + 5, 10)) == 0

    def test_last_hit_reports_none(self, bar):
        """末段上无可回溯段"""
        assert bar._hit(QPointF(bar._records[-1].rect.x() + 5, 10)) is None

    def test_separator_hit_reports_none(self, bar):
        """分隔槽上无可回溯段"""
        assert bar._hit(bar._records[1].rect.center()) is None

    def test_empty_bar_has_no_records(self, qapp):
        """无段时排布为空"""
        widget = BreadcrumbBar()
        widget.resize(200, widget.ROW_HEIGHT)
        assert widget.items() == []
        assert widget._records == []
        assert widget._hit(QPointF(10, 10)) is None
