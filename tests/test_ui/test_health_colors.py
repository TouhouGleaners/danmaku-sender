"""健康档标签配色的渲染合约：浅色锁 subtle 配色，深色锁 GitHub 标签公式的折算值。"""
import pytest

from danmaku_sender.ui.framework.health_colors import HealthColors, LabelBase, Tint

# 渲染折算的黄金值；改动配色或渲染管线须同步复核
GOLDEN = {
    "great": {
        "light": Tint(fg="#116329", bg="#dafbe1", border="#33116329"),
        "dark": Tint(fg="#36c45e", bg="#2e2da44e", border="#4d36c45e"),
    },
    "good": {
        "light": Tint(fg="#1a7f37", bg="#dafbe1", border="#331a7f37"),
        "dark": Tint(fg="#4bc36b", bg="#2e4ac26b", border="#4d4bc36b"),
    },
    "warn": {
        "light": Tint(fg="#bc4c00", bg="#fff1e5", border="#33bc4c00"),
        "dark": Tint(fg="#d4a72b", bg="#2ed4a72c", border="#4dd4a72b"),
    },
    "bad": {
        "light": Tint(fg="#cf222e", bg="#ffebe9", border="#33cf222e"),
        "dark": Tint(fg="#ff8080", bg="#2eff8182", border="#4dff8080"),
    },
    "neutral": {
        "light": Tint(fg="#59636e", bg="#e6eaef", border="#3359636e"),
        "dark": Tint(fg="#999999", bg="#2e999999", border="#4d999999"),
    },
}


class TestHealthColors:
    def test_hsl_matches_github_inline_vars(self):
        """RGB→HSL 折算同 GitHub 标签内联的 --label-h/s/l 取整口径。"""
        base = LabelBase.from_hex("#2da44e")
        assert (base.h, base.s, base.l) == (137, 57, 41)

    @pytest.mark.parametrize("tone", list(GOLDEN))
    def test_light_matches_golden(self, tone: str):
        """浅色配色锁黄金值。"""
        assert HealthColors.LIGHT[tone] == GOLDEN[tone]["light"]

    @pytest.mark.parametrize("tone", list(GOLDEN))
    def test_dark_matches_github_formula(self, tone: str):
        """深色渲染锁 GitHub 标签公式的折算值。"""
        assert HealthColors.TONES[tone].render_dark() == GOLDEN[tone]["dark"]

    def test_to_qml_shape(self):
        """QML 取色表为 档位 → 明暗 → {fg, bg, border}。"""
        table = HealthColors.to_qml()
        assert set(table) == set(GOLDEN)
        for tone, modes in table.items():
            assert set(modes) == set(GOLDEN[tone])
            for mode, tint in modes.items():
                assert set(tint) == {"fg", "bg", "border"}
                assert tint == {field: getattr(GOLDEN[tone][mode], field) for field in ("fg", "bg", "border")}
