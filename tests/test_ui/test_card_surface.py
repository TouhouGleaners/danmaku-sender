"""Card 表面色广播与宿主跟随的契约。"""

import pytest
from PySide6.QtGui import QColor

from danmaku_sender.config.theme_config import ThemeMode
from danmaku_sender.ui.framework.card import Card, CardAppearance
from danmaku_sender.ui.framework.settings_row import SettingsRow
from danmaku_sender.ui.framework.theme import ThemeService
from danmaku_sender.ui.framework.toggle_switch import ToggleSwitch


@pytest.fixture()
def tokens(qapp):
    """已渲染的浅色主题；Card 取色依赖 ThemeService.tokens，须先于 Card 构造就位。"""
    service = ThemeService()
    service.apply_theme(ThemeMode.LIGHT)
    return service.current_palette


class TestCardSurfaceColor:
    def test_layer_surface_matches_token(self, tokens) -> None:
        card = Card()
        assert card.surface_color == QColor(tokens.CardBackgroundFillColorDefault)

    def test_alt_surface_matches_token(self, tokens) -> None:
        card = Card()
        card.setAppearance(CardAppearance.LAYER_ALT)
        assert card.surface_color == QColor(tokens.CardBackgroundFillColorSecondary)

    def test_danger_surface_matches_token(self, tokens) -> None:
        """danger 属性晚于构造期落地时表面色仍须正确（危险区设置行的真实时序）。"""
        row = SettingsRow("允许重复发送", "说明", danger=True)
        assert row.surface_color == QColor(tokens.SystemFillColorAttentionBackground)

    def test_surface_changed_broadcasts(self, tokens) -> None:
        card = Card()
        fired: list[bool] = []
        card.surfaceChanged.connect(lambda: fired.append(True))
        card.setAppearance(CardAppearance.LAYER_ALT)
        assert fired == [True]


class TestHostFollowsSurface:
    def test_qml_surface_follows_card(self, tokens, qapp) -> None:
        switch = ToggleSwitch()
        row = SettingsRow("允许重复发送", "说明", trailing=switch, danger=True)
        row.show()
        qapp.processEvents()
        assert switch.rootObject().property("surface") == QColor(tokens.SystemFillColorAttentionBackground)
