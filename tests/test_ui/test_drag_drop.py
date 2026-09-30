"""拖放事件的 XML 文件提取与拖放覆盖层测试。"""
import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QLabel, QTableView

from danmaku_sender.ui.framework.drag_drop import DropOverlay, xml_files_from_drop


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


class TestXmlFilesFromDrop:
    """XML 文件提取的筛选规则"""

    def test_keeps_local_xml(self, qapp):
        mime = _mime([QUrl.fromLocalFile("C:/tmp/a.xml"), QUrl.fromLocalFile("C:/tmp/b.XML")])
        assert xml_files_from_drop(_make_drop(mime)) == ["C:/tmp/a.xml", "C:/tmp/b.XML"]

    def test_drops_non_xml_and_remote(self, qapp):
        mime = _mime([
            QUrl("https://example.com/c.xml"),
            QUrl.fromLocalFile("C:/tmp/a.txt"),
            QUrl.fromLocalFile("C:/tmp/b.xml"),
        ])
        assert xml_files_from_drop(_make_drop(mime)) == ["C:/tmp/b.xml"]

    def test_empty_result(self, qapp):
        mime = _mime([])
        assert xml_files_from_drop(_make_drop(mime)) == []


@pytest.fixture
def host(qapp):
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
