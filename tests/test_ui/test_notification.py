"""应用内通知卡片测试"""
import time

import pytest
from PySide6.QtWidgets import QWidget

from danmaku_sender.ui.framework import notification
from danmaku_sender.ui.framework.notification import (
    CARD_WIDTH,
    MAX_CARDS,
    NotificationHost,
)


@pytest.fixture
def host(qapp):
    """装在宿主窗口上的通知容器"""
    window = QWidget()
    window.resize(800, 600)
    window.show()
    h = NotificationHost(window)
    notification.attach(h)
    yield h
    notification.attach(None)  # type: ignore[arg-type]


class TestNotificationHost:
    def test_notify_makes_host_visible(self, host, qapp):
        assert host.isHidden()
        host.notify("第一条")
        qapp.processEvents()
        assert host.isVisible()

    def test_cards_stack_newest_at_bottom(self, host, qapp):
        host.notify("旧的")
        host.notify("新的")
        qapp.processEvents()
        assert [c.message for c in host.cards] == ["旧的", "新的"]

    def test_card_width_is_fixed(self, host, qapp):
        host.notify("短")
        host.notify("这是一个明显更长的正文，用来确认卡片宽度不随文案变化")
        qapp.processEvents()
        assert [c.width() for c in host.cards] == [CARD_WIDTH, CARD_WIDTH]

    def test_card_count_is_capped(self, host, qapp):
        for i in range(MAX_CARDS + 3):
            host.notify(f"第 {i} 条")
        qapp.processEvents()
        assert len(host.cards) == MAX_CARDS
        assert host.cards[0].message.startswith("第 3")

    def test_dismiss_hides_host_when_empty(self, host, qapp):
        host.notify("即将消失")
        host.cards[0].dismiss()
        qapp.processEvents()
        assert host.isHidden()

    def test_timeout_dismisses_automatically(self, host, qapp):
        host.notify("短命", timeout_ms=30)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and host.isVisible():
            qapp.processEvents()
            time.sleep(0.01)
        assert host.isHidden()

    def test_multiple_cards_isolated(self, host, qapp):
        host.notify("一")
        host.notify("二")
        host.cards[0].dismiss()
        qapp.processEvents()
        assert host.isVisible()
        assert [c.message for c in host.cards] == ["二"]

    def test_remaining_cards_do_not_grow_when_sibling_exits(self, host, qapp):
        """旧卡退出后，剩下的卡片高度不许被布局撑开"""
        for i in range(3):
            host.notify(f"第 {i} 条")
        qapp.processEvents()
        before = [c.height() for c in host.cards]

        host.cards[0].dismiss()
        qapp.processEvents()
        after = [c.height() for c in host.cards]

        assert after == before[1:]

    def test_host_stays_above_action_bar(self, host, qapp):
        from danmaku_sender.ui.framework.notification import ACTION_BAR_CLEARANCE

        host.notify("不要压住底部按钮")
        qapp.processEvents()
        window = host.parentWidget()
        assert window is not None
        assert host.y() + host.height() <= window.height() - ACTION_BAR_CLEARANCE


class TestNotificationModule:
    def test_notify_without_host_does_not_crash(self):
        notification.attach(None)  # type: ignore[arg-type]
        notification.notify("宿主未装")

    def test_notify_after_attach_reaches_host(self, qapp):
        window = QWidget()
        h = NotificationHost(window)
        notification.attach(h)
        try:
            notification.notify("接力成功")
            assert len(h.cards) == 1
        finally:
            notification.attach(None)  # type: ignore[arg-type]
