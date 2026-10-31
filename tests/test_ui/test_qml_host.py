"""QML 令牌桥的字体回退行为。"""
from PySide6.QtGui import QFont, QPalette

from danmaku_sender.ui.framework import qml_host
from danmaku_sender.ui.framework.qml_host import QmlPaletteBridge


class _NoIconFontDatabase:
    """伪造无可用图标字体的系统字体表。"""

    @staticmethod
    def families() -> list[str]:
        return []


class _IconFontDatabase:
    """伪造含图标字体的系统字体表。"""

    @staticmethod
    def families() -> list[str]:
        return ["Segoe Fluent Icons"]


class TestPaletteBridgeIconFont:
    def test_icon_font_fallback_follows_font_change(self, qapp, monkeypatch):
        """无可用图标字体时，图标字体族跟随应用字体变更。"""
        monkeypatch.setattr(qml_host, "QFontDatabase", _NoIconFontDatabase)
        bridge = QmlPaletteBridge()

        bridge.sync(QPalette(), QFont("第一字体"))
        assert bridge.iconFontFamily == "第一字体"
        assert bridge.chevronCollapsed == "▸"

        bridge.sync(QPalette(), QFont("第二字体"))
        assert bridge.iconFontFamily == "第二字体"

    def test_icon_font_keeps_resolved_family(self, qapp, monkeypatch):
        """有可用图标字体时，图标字体族不随应用字体变更。"""
        monkeypatch.setattr(qml_host, "QFontDatabase", _IconFontDatabase)
        bridge = QmlPaletteBridge()
        assert bridge.iconFontFamily == "Segoe Fluent Icons"
        assert bridge.chevronCollapsed == chr(0xE76C)

        bridge.sync(QPalette(), QFont("任意字体"))
        assert bridge.iconFontFamily == "Segoe Fluent Icons"
