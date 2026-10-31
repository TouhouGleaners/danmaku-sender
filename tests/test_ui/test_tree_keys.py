"""TreeView 交互：键盘与鼠标的 WinUI 语义。"""
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtQuick import QQuickView

from danmaku_sender.ui.framework import qml_host
from danmaku_sender.ui.framework.qml_host import QmlPaletteBridge
from danmaku_sender.ui.framework.tree_model import TreeNode, TreeRowsModel

QML_DIR = Path(qml_host.__file__).parent / "qml"


def _tree_rows(model: TreeRowsModel) -> tuple[QQuickView, object]:
    """装载 TreeView.qml，返回 (视图, 行列表)。

    桥与模型须由调用方或视图持续持有：QML 初始属性只存 C++ 指针，
    Python 侧无引用即销毁。
    """
    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.setInitialProperties({"theme": QmlPaletteBridge(view), "model": model})
    view.setSource(QUrl.fromLocalFile(str(QML_DIR / "TreeView.qml")))
    view.resize(400, 300)
    view.show()
    for _ in range(5):
        QGuiApplication.processEvents()
    rows = view.rootObject().childItems()[0]
    view.rootObject().forceActiveFocus()
    return view, rows


def _press(view: QQuickView, key: Qt.Key) -> None:
    """向视图发送一个合成按键事件。"""
    QGuiApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def _click(view: QQuickView, x: int, y: int) -> None:
    """向视图发送合成鼠标单击。"""
    pos = QPointF(x, y)
    global_pos = view.mapToGlobal(QPoint(x, y))
    for typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        buttons = Qt.MouseButton.NoButton if typ == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        QGuiApplication.sendEvent(
            view,
            QMouseEvent(typ, pos, global_pos, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier),
        )


def _model() -> TreeRowsModel:
    """构造 年→叶A/叶B 三层行模型，年节点已展开。"""
    model = TreeRowsModel(("label",))
    model.set_roots([
        TreeNode(
            data={"label": "组"},
            children=[
                TreeNode(data={"label": "叶A"}, payload="a"),
                TreeNode(data={"label": "叶B"}, payload="b"),
            ],
        )
    ])
    model.expand(0)
    return model


class TestTreeKeys:
    def test_right_on_expanded_dives_to_first_child(self, qapp):
        model = _model()
        view, rows = _tree_rows(model)
        rows.setProperty("currentIndex", 0)
        _press(view, Qt.Key.Key_Right)
        assert rows.property("currentIndex") == 1

    def test_right_on_leaf_keeps_current_row(self, qapp):
        model = _model()
        view, rows = _tree_rows(model)
        rows.setProperty("currentIndex", 1)
        _press(view, Qt.Key.Key_Right)
        assert rows.property("currentIndex") == 1

    def test_left_on_expanded_collapses(self, qapp):
        model = _model()
        view, rows = _tree_rows(model)
        rows.setProperty("currentIndex", 0)
        _press(view, Qt.Key.Key_Left)
        assert rows.property("currentIndex") == 0
        assert rows.property("count") == 1

    def test_left_on_collapsed_returns_to_parent(self, qapp):
        model = _model()
        view, rows = _tree_rows(model)
        rows.setProperty("currentIndex", 0)
        _press(view, Qt.Key.Key_Left)
        _press(view, Qt.Key.Key_Right)
        rows.setProperty("currentIndex", 1)
        _press(view, Qt.Key.Key_Left)
        assert rows.property("currentIndex") == 0


class TestTreeMouse:
    def test_click_selects_row_without_toggle(self, qapp):
        model = _model()
        view, rows = _tree_rows(model)
        _click(view, 60, 16)
        assert rows.property("currentIndex") == 0
        assert rows.property("count") == 3

    def test_chevron_click_toggles_without_selecting(self, qapp):
        model = _model()
        view, rows = _tree_rows(model)
        _click(view, 20, 16)
        assert rows.property("currentIndex") == -1
        assert rows.property("count") == 1
