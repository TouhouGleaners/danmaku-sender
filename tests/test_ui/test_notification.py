"""应用内通知卡片测试"""
import time

import pytest
from PySide6.QtWidgets import QWidget

from danmaku_sender.ui.framework.notification import (
    Notification,
    NotificationHost,
    _NotificationCard,
)


@pytest.fixture
def host(qapp):
    """装在宿主窗口上的通知容器"""
    window = QWidget()
    window.resize(800, 600)
    window.show()
    h = Notification.install(window)
    yield h
    Notification._host = None


class TestNotification:
    def test_info_warning_error_reach_host(self, host):
        Notification.info(title="提示", message="正文")
        Notification.warning(title="警告", message="正文")
        Notification.error(title="错误", message="正文")
        assert [c.title for c in host.cards] == ["提示", "警告", "错误"]
        assert [c.property("level") for c in host.cards] == ["info", "warning", "error"]

    def test_notify_without_host_does_not_crash(self):
        Notification._host = None
        Notification.warning(title="宿主未装", message="正文")


class TestNotificationHost:
    def test_notify_makes_host_visible(self, host, qapp):
        assert host.isHidden()
        Notification.info(title="第一条", message="正文")
        qapp.processEvents()
        assert host.isVisible()

    def test_cards_stack_newest_at_bottom(self, host, qapp):
        Notification.info(title="旧的", message="正文")
        Notification.info(title="新的", message="正文")
        qapp.processEvents()
        assert [c.title for c in host.cards] == ["旧的", "新的"]

    def test_card_width_is_fixed(self, host, qapp):
        Notification.info(title="短", message="短")
        Notification.info(title="长", message="这是一个明显更长的正文，用来确认卡片宽度不随文案变化")
        qapp.processEvents()
        assert [c.width() for c in host.cards] == [_NotificationCard.WIDTH] * 2

    def test_card_count_is_capped(self, host):
        for i in range(NotificationHost.MAX_CARDS + 3):
            Notification.info(title=f"第 {i} 条", message="正文")
        assert len(host.cards) == NotificationHost.MAX_CARDS
        assert host.cards[0].title == "第 3 条"

    def test_dismiss_hides_host_when_empty(self, host, qapp):
        Notification.info(title="即将消失", message="正文")
        host.cards[0].dismiss()
        qapp.processEvents()
        assert host.isHidden()

    def test_timeout_dismisses_automatically(self, host, qapp):
        Notification.info(title="短命", message="正文", timeout_ms=30)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and host.isVisible():
            qapp.processEvents()
            time.sleep(0.01)
        assert host.isHidden()

    def test_remaining_cards_do_not_grow_when_sibling_exits(self, host, qapp):
        """旧卡退出后，剩下的卡片高度不许被布局撑开"""
        for i in range(3):
            Notification.info(title=f"第 {i} 条", message="正文")
        qapp.processEvents()
        before = [c.height() for c in host.cards]

        host.cards[0].dismiss()
        qapp.processEvents()
        after = [c.height() for c in host.cards]

        assert after == before[1:]

    def test_host_stays_above_action_bar(self, host, qapp):
        Notification.info(title="不要压住底部按钮", message="正文")
        qapp.processEvents()
        window = host.parentWidget()
        assert window is not None
        assert host.y() + host.height() <= window.height() - NotificationHost.ACTION_BAR_CLEARANCE
