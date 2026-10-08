"""拖放事件的 XML 文件提取与拖放覆盖层测试。"""
import re
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPalette
from PySide6.QtWidgets import QLabel, QTableView

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.ui.framework.drag_drop import (
    DropOverlay,
    XmlDropFilter,
    xml_files_from_drop,
)


def _mime(urls: list[QUrl]) -> QMimeData:
    """构造承载 URL 的 mime 数据，由调用方持有引用。"""
    mime = QMimeData()
    mime.setUrls(urls)
    return mime


def _make_drop(mime: QMimeData) -> QDropEvent:
    """按给定 mime 数据构造拖放事件。

    QDropEvent 只保存 mimeData 的指针，不持有所有权，调用方必须让 mime
    活得比事件久。
    """
    return QDropEvent(
        QPointF(0, 0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _make_enter(mime: QMimeData) -> QDragEnterEvent:
    """构造拖入事件；mime 的存活要求同 :func:`_make_drop`。"""
    return QDragEnterEvent(
        QPoint(0, 0),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


class TestXmlFilesFromDrop:
    """XML 文件提取的筛选规则"""

    def test_keeps_local_xml(self, qapp):
        src = ["/tmp/a.xml", "/tmp/b.XML"]
        mime = _mime([QUrl.fromLocalFile(p) for p in src])
        # 路径形态随平台而异，期望值同样经 toLocalFile() 换算
        expected = [Path(QUrl.fromLocalFile(p).toLocalFile()) for p in src]
        assert xml_files_from_drop(_make_drop(mime)) == expected

    def test_drops_non_xml_and_remote(self, qapp):
        mime = _mime([
            QUrl("https://example.com/c.xml"),
            QUrl.fromLocalFile("/tmp/a.txt"),
            QUrl.fromLocalFile("/tmp/b.xml"),
        ])
        expected = Path(QUrl.fromLocalFile("/tmp/b.xml").toLocalFile())
        assert xml_files_from_drop(_make_drop(mime)) == [expected]

    def test_empty_result(self, qapp):
        mime = _mime([])
        assert xml_files_from_drop(_make_drop(mime)) == []


@pytest.fixture(scope="module")
def themed_qapp(qapp):
    """载入 style.qss：遮罩的外观由 QSS 提供，测试需自带主题管线。"""
    css = (AppInfo.Paths.ASSETS / "qss" / "style.qss").read_text(encoding="utf-8")
    qapp.setStyleSheet(re.sub(r"\{[a-z_]+\}", "#888888", css))
    yield qapp
    qapp.setStyleSheet("")


@pytest.fixture
def host(themed_qapp):
    table = QTableView()
    table.resize(400, 200)
    table.show()
    yield table
    table.close()
    table.deleteLater()


class TestDropOverlay:
    """拖放覆盖层的显隐与定位"""

    def test_hidden_until_shown(self, host):
        overlay = DropOverlay(host, title="松开以导入文件", hint="支持 .xml 格式的弹幕文件")
        assert not overlay.isVisible()

        overlay.show_overlay()
        assert overlay.isVisible()

        overlay.hide()
        assert not overlay.isVisible()

    def test_show_overlay_fills_host(self, host, qapp):
        overlay = DropOverlay(host, title="松开以导入文件", hint="支持 .xml 格式的弹幕文件")
        overlay.show_overlay()
        qapp.processEvents()
        assert overlay.geometry() == host.rect()

        host.resize(320, 120)
        qapp.processEvents()
        assert overlay.geometry() == host.rect()

    def test_renders_title_and_hint(self, host):
        overlay = DropOverlay(host, title="松开以导入文件", hint="支持 .xml 格式的弹幕文件")
        assert [label.text() for label in overlay.findChildren(QLabel) if label.text()] == [
            "松开以导入文件",
            "支持 .xml 格式的弹幕文件",
        ]

    def test_scrim_composites_into_parent(self, host, qapp):
        """遮罩必须合成到父控件，而非只在自身绘制。"""
        overlay = DropOverlay(host, title="松开以导入文件", hint="支持 .xml 格式的弹幕文件")
        qapp.processEvents()
        bare = host.grab().toImage().pixelColor(host.width() // 2, host.height() // 2)

        overlay.show_overlay()
        qapp.processEvents()
        covered = host.grab().toImage().pixelColor(host.width() // 2, host.height() // 2)

        assert covered.getRgb() != bare.getRgb()

    @pytest.mark.parametrize("dark", [False, True], ids=["浅色主题", "深色主题"])
    def test_scrim_colour_is_stable_across_show_hide(self, host, themed_qapp, dark):
        """遮罩颜色在反复显隐下必须稳定：取色读自身调色板会与 QSS 形成正反馈。"""
        if dark:
            palette = host.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e1e"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#e0e0e0"))
            host.setPalette(palette)
            themed_qapp.processEvents()

        overlay = DropOverlay(host, title="松开以导入文件", hint="支持 .xml 格式的弹幕文件")
        cx, cy = host.width() // 2, host.height() // 2
        seen: set[tuple[int, int, int]] = set()
        for _ in range(10):
            overlay.hide()
            themed_qapp.processEvents()
            overlay.show_overlay()
            themed_qapp.processEvents()
            pixel = overlay.grab().toImage().pixelColor(cx, cy)
            seen.add((pixel.red(), pixel.green(), pixel.blue()))

        assert len(seen) == 1, f"遮罩颜色在显隐间翻转: {seen}"


class TestXmlDropFilter:
    """拖入单个 XML 的过滤器：判定、拦截与回调"""

    def _filter(self, host, drops: list):
        overlay = DropOverlay(host, title="松开以导入文件", hint="支持 .xml")
        return overlay, XmlDropFilter(host, overlay, drops.append)

    def test_single_xml_accepts_exactly_one(self, qapp):
        mime = _mime([QUrl.fromLocalFile("/tmp/a.xml")])
        assert XmlDropFilter.single_xml(_make_drop(mime)) == Path("/tmp/a.xml")

    def test_single_xml_rejects_multiple(self, qapp):
        mime = _mime([QUrl.fromLocalFile("/tmp/a.xml"), QUrl.fromLocalFile("/tmp/b.xml")])
        assert XmlDropFilter.single_xml(_make_drop(mime)) is None

    def test_single_xml_rejects_empty(self, qapp):
        assert XmlDropFilter.single_xml(_make_drop(_mime([]))) is None

    def test_drop_invokes_callback(self, host):
        drops: list = []
        _overlay, filt = self._filter(host, drops)
        mime = _mime([QUrl.fromLocalFile("/tmp/a.xml")])
        assert filt.eventFilter(host.viewport(), _make_drop(mime)) is True
        assert drops == [Path("/tmp/a.xml")]

    def test_drop_of_multiple_is_refused(self, host):
        drops: list = []
        _overlay, filt = self._filter(host, drops)
        mime = _mime([QUrl.fromLocalFile("/tmp/a.xml"), QUrl.fromLocalFile("/tmp/b.xml")])
        assert filt.eventFilter(host.viewport(), _make_drop(mime)) is False
        assert drops == []

    def test_drag_enter_of_single_xml_is_accepted(self, host):
        drops: list = []
        _overlay, filt = self._filter(host, drops)
        mime = _mime([QUrl.fromLocalFile("/tmp/a.xml")])
        event = _make_enter(mime)
        assert filt.eventFilter(host.viewport(), event) is True
        assert event.isAccepted()
        assert drops == [], "拖动中不应触发导入"

    def test_drag_enter_of_multiple_is_refused(self, host):
        drops: list = []
        _overlay, filt = self._filter(host, drops)
        mime = _mime([QUrl.fromLocalFile("/tmp/a.xml"), QUrl.fromLocalFile("/tmp/b.xml")])
        event = _make_enter(mime)
        filt.eventFilter(host.viewport(), event)
        assert not event.isAccepted()
        assert drops == []

    def test_non_drop_event_is_ignored(self, host):
        drops: list = []
        _overlay, filt = self._filter(host, drops)
        assert filt.eventFilter(host.viewport(), QEvent(QEvent.Type.MouseButtonPress)) is False
        assert drops == []
