"""主题调色板（ThemeService / Palette）的结构性约束"""
from PySide6.QtGui import QPalette

from danmaku_sender.config.theme_config import ThemeMode
from danmaku_sender.ui.framework.theme import ROLE_SOURCES, ThemeService


class TestPaletteCoverage:
    def test_role_sources_cover_all_qpalette_roles(self):
        """调色板映射必须覆盖 Qt 全部 ColorRole，杜绝「漏设退回系统默认」。

        回归：原先按需逐个 setColor，漏掉 PlaceholderText 后暗色主题下占位符仍是黑的（Qt 回退到 #000000），而真实文字正常跟随主题。
        """
        real = {
            r for r in QPalette.ColorRole
            if r not in (QPalette.ColorRole.NoRole, QPalette.ColorRole.NColorRoles)
        }
        assert set(ROLE_SOURCES) == real

    def test_every_role_resolves_to_a_color(self):
        """映射表中每个角色都应能解析出有效颜色。"""
        svc = ThemeService()
        for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
            svc.apply_theme(mode)
            qpal = svc.current_palette.to_qpalette()
            for role in ROLE_SOURCES:
                color = qpal.color(role)
                assert color.isValid(), f"{mode} 下 {role} 解析失败"
