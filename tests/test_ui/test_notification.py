"""应用内通知卡片测试"""
import time

import pytest
from PySide6.QtWidgets import QWidget

from danmaku_sender.ui.framework.notification import (
    Notification,
    NotificationHost,
    _NotificationCard,
)


def settle(qapp, predicate, timeout: float = 2.0) -> bool:
    """泵事件直到条件成立；超时返回 False。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        qapp.processEvents()
        time.sleep(0.01)
    return predicate()


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
        assert [c.level for c in host.cards] == ["info", "warning", "error"]

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
        assert settle(qapp, lambda: len(host.cards) == 2)
        first, second = host.cards
        assert [first.title, second.title] == ["旧的", "新的"]
        assert first.pos().y() + first.height() <= second.pos().y()

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
        assert settle(qapp, lambda: host.isHidden())

    def test_timeout_dismisses_automatically(self, host, qapp):
        Notification.info(title="短命", message="正文", timeout_ms=30)
        assert len(host.cards) == 1, "通知压根没弹出"
        assert host.isVisible()
        assert settle(qapp, lambda: host.isHidden())

    def test_remaining_cards_do_not_grow_when_sibling_exits(self, host, qapp):
        """旧卡退出后，剩下的卡片高度不许被布局撑开"""
        for i in range(3):
            Notification.info(title=f"第 {i} 条", message="正文")
        qapp.processEvents()
        before = [c.height() for c in host.cards]

        host.cards[0].dismiss()
        assert settle(qapp, lambda: len(host.cards) == 2)
        after = [c.height() for c in host.cards]

        assert after == before[1:]

    def test_second_card_does_not_overlap_first(self, host, qapp):
        """后弹出的卡片不许被动画拖到前一张的槽位上"""
        Notification.info(title="第一张", message="正文")
        Notification.info(title="第二张", message="正文")
        # 等进入动画（ENTER_MS）落地后再判位置
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        first, second = host.cards
        assert first.pos().y() + first.height() <= second.pos().y()

    def test_push_during_exit_does_not_exile_the_new_card(self, host, qapp):
        """旧卡淡出期间推新卡，新卡不许被旧动画按到宿主外"""
        Notification.info(title="即将消失", message="正文", timeout_ms=30)
        # 趁淡出还在跑就推下一张
        Notification.info(title="新来的", message="正文")
        assert settle(qapp, lambda: len(host.cards) == 1 and not host.isHidden())
        card = host.cards[0]
        assert card.isVisible()
        assert 0 <= card.pos().y()
        assert card.pos().y() + card.height() <= host.height()

    def test_stack_trims_oldest_when_parent_too_short(self, qapp):
        """父控件装不下整堆时丢最旧的，剩下的必须仍在宿主内可见"""
        window = QWidget()
        window.resize(800, 140)   # 连两张卡片都放不下（还要让开操作栏）
        window.show()
        h = Notification.install(window)
        try:
            for i in range(4):
                Notification.info(title=f"第 {i} 条", message="正文")
            # 等入场动画（ENTER_MS）落地再查坐标
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                qapp.processEvents()
                time.sleep(0.01)
            assert len(h.cards) >= 1
            assert len(h.cards) < 4
            for card in h.cards:
                assert card.isVisible()
                assert 0 <= card.pos().y()
                assert card.pos().y() + card.height() <= h.height()
        finally:
            Notification._host = None

    def test_host_height_matches_card_stack(self, host, qapp):
        """堆高必须等于卡片高度累加，多出来的空白会吃掉鼠标事件"""
        for i in range(3):
            Notification.info(title=f"第 {i} 条", message="一个明显更长的正文，用来撑开卡片高度")
        qapp.processEvents()
        cards = host.cards
        expected = sum(c.height() for c in cards) + NotificationHost.SPACING * (len(cards) - 1)
        assert host.height() == expected

    def test_host_stays_inside_narrow_parent(self, qapp):
        """窄窗口下宿主不许跑到父控件左边界外，卡片跟着缩宽"""
        window = QWidget()
        window.resize(300, 600)   # 比卡片还窄
        window.show()
        h = Notification.install(window)
        try:
            Notification.info(title="窄窗口", message="正文")
            assert settle(qapp, lambda: len(h.cards) == 1)
            assert h.x() >= 0
            assert h.y() >= 0
            assert h.cards[0].width() < 360
            assert h.cards[0].width() == h.width()
        finally:
            Notification._host = None

    def test_lone_card_capped_to_available_height(self, qapp):
        """单张卡装不下时压到可用高度，不越出宿主"""
        window = QWidget()
        window.resize(800, 120)   # 很矮
        window.show()
        h = Notification.install(window)
        try:
            Notification.info(title="矮窗口", message="正文" * 30)
            assert settle(qapp, lambda: len(h.cards) == 1)
            # 等入场动画（ENTER_MS）落地再查坐标
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                qapp.processEvents()
                time.sleep(0.01)
            card = h.cards[0]
            assert card.height() <= h.height()
            assert card.pos().y() + card.height() <= h.height()
        finally:
            Notification._host = None

    def test_host_stays_above_action_bar(self, host, qapp):
        Notification.info(title="不要压住底部按钮", message="正文")
        qapp.processEvents()
        window = host.parentWidget()
        assert window is not None
        assert host.y() + host.height() <= window.height() - NotificationHost.ACTION_BAR_CLEARANCE
