"""QML 装载冒烟：在测试中暴露组件语法错与加载失败路径。"""
from pathlib import Path

import pytest
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QWidget

from danmaku_sender.ui.framework import qml_host
from danmaku_sender.ui.framework.qml_host import QmlHost
from danmaku_sender.ui.framework.tree_model import TreeRowsModel

QML_DIR = Path(qml_host.__file__).parent / "qml"


class TestQmlLoad:
    def test_tree_view_loads(self, qapp):
        """TreeView.qml 装载成功：语法与绑定错误会在此暴露。"""
        model = TreeRowsModel(("label",))
        parent = QWidget()
        host = QmlHost(
            QML_DIR / "TreeView.qml",
            properties={"model": model},
            parent=parent,
        )
        assert host.status() == QQuickWidget.Status.Ready
        assert host.rootObject() is not None

    def test_load_failure_raises_and_detaches(self, qapp, tmp_path):
        """加载失败抛 RuntimeError，宿主不留在调用方父控件上。"""
        broken = tmp_path / "broken.qml"
        broken.write_text("Item {", encoding="utf-8")
        parent = QWidget()
        with pytest.raises(RuntimeError):
            QmlHost(broken, parent=parent)
        assert parent.children() == []
