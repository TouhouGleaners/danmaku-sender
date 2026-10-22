"""EmptyStateHint 的行为测试。

覆盖：默认隐藏、set_empty 控显隐、随可视区重定位、CTA 按钮形态与样式、
销毁期对已拆解自身的免疫。
"""
import pytest
from PySide6.QtCore import QEvent, QObject, QStringListModel, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QTableView

from danmaku_sender.ui.framework.empty_state import EmptyStateHint


class _Emitter(QObject):
    """测试用信号源，模拟调用方的数据变化通知。"""

    changed = Signal()


@pytest.fixture
def view(qapp):
    table = QTableView()
    table.resize(400, 200)
    table.show()
    yield table
    table.close()
    table.deleteLater()


class TestEmptyStateHint:
    """空状态引导块的显隐、定位与 CTA 形态"""
    def test_hidden_until_set_empty(self, view):
        hint = EmptyStateHint(view, title="暂无数据")
        assert not hint.isVisible()

        hint.set_empty(True)
        assert hint.isVisible()

        hint.set_empty(False)
        assert not hint.isVisible()

    def test_reflow_fills_viewport(self, view, qapp):
        hint = EmptyStateHint(view, title="暂无数据")
        hint.set_empty(True)
        qapp.processEvents()
        assert hint.geometry() == view.viewport().rect()

        view.resize(320, 120)
        qapp.processEvents()
        assert hint.geometry() == view.viewport().rect()

    def test_description_renders_as_second_line(self, view):
        hint = EmptyStateHint(view, title="当前任务无弹幕", description="选择 XML 文件导入")
        assert [label.text() for label in hint.findChildren(QLabel)] == [
            "当前任务无弹幕",
            "选择 XML 文件导入",
        ]

    def test_omitted_description_and_buttons(self, view):
        hint = EmptyStateHint(view, title="暂无数据")
        assert [label.text() for label in hint.findChildren(QLabel)] == ["暂无数据"]
        assert hint.findChildren(QPushButton) == []

    def test_cta_buttons_are_styled(self, view):
        action = QPushButton("导入 XML")
        secondary = QPushButton("添加示例弹幕")
        hint = EmptyStateHint(view, title="当前任务无弹幕", action=action, secondary=secondary)

        assert [b.text() for b in hint.findChildren(QPushButton)] == ["导入 XML", "添加示例弹幕"]
        # 主按钮挂 primary="true"，交给既有 QSS；次按钮不挂
        assert action.property("primary") == "true"
        assert secondary.property("primary") is None

    def test_follows_model_rows(self, qapp):
        """表格有 model 时按行数自动显隐，构造即求值一次"""
        table = QTableView()
        model = QStringListModel()
        table.setModel(model)
        table.resize(300, 150)
        table.show()
        hint = EmptyStateHint(table, title="暂无数据")

        assert hint.isVisible()

        model.setStringList(["a", "b"])
        assert not hint.isVisible()

        model.setStringList([])
        assert hint.isVisible()

        table.close()
        table.deleteLater()

    def test_custom_predicate_and_signal(self, qapp):
        """「空」的口径不同时由调用方给出判定与刷新时机"""
        table = QTableView()
        table.show()
        emitter = _Emitter()
        state = {"empty": False}

        hint = EmptyStateHint(
            table,
            title="暂无数据",
            is_empty=lambda: state["empty"],
            on_change=emitter.changed,
        )
        assert not hint.isVisible()

        state["empty"] = True
        emitter.changed.emit()
        assert hint.isVisible()

        table.close()
        table.deleteLater()

    def test_event_filter_immune_after_teardown(self, view):
        """销毁期属性表被清空后，事件过滤不再抛异常"""
        hint = EmptyStateHint(view, title="暂无数据")
        hint.set_empty(True)
        hint.__dict__.clear()

        assert hint.eventFilter(view, QEvent(QEvent.Type.Resize)) is False

    def test_refresh_immune_after_teardown(self, view):
        """销毁期属性表被清空后，model 信号触发的刷新不再抛异常"""
        model = QStringListModel()
        view.setModel(model)
        hint = EmptyStateHint(view, title="暂无数据")
        assert hint.isVisible()  # 空 model，构造时即判空
        hint.__dict__.clear()

        model.setStringList(["a"])  # 触发 rowsInserted → refresh
        # 免疫意味着刷新被跳过，可见性保持拆解前的状态
        assert hint.isVisible()

    def test_slot_registered(self, view):
        """refresh 是信号回调，须注册为 Qt 槽"""
        hint = EmptyStateHint(view, title="暂无数据")
        meta = hint.metaObject()
        names = {meta.method(i).name().data().decode() for i in range(meta.methodCount())}
        assert "refresh" in names
