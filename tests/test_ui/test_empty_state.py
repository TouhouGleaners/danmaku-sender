"""EmptyStateHint 的行为测试。

覆盖：默认隐藏、set_empty 控显隐、随可视区重定位、CTA 按钮形态与样式。
"""
import pytest
from PySide6.QtWidgets import QLabel, QPushButton, QTableView

from danmaku_sender.ui.framework.empty_state import EmptyStateHint


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
