"""小标签配色：浅色取 Primer subtle 形制，深色按 GitHub 标签（Primer IssueLabel）公式。

色值取 Primer 基础色阶（github/primer/primitives）。
浅色 = 色阶 0 档淡色底 + 同族 5 档较深字色（淡而不灰、彩度保留）；警档取 severe 橙，避免黄系字色偏棕。
深色 = 18% 同色相底色 + 按 (0.6 - 感知亮度) 提亮的同色相字色（IssueLabelToken 公式）。
"""
import colorsys
from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Tint:
    """标签的渲染结果。

    Attributes:
        fg (str): 字色，#RRGGBB。
        bg (str): 底色，#AARRGGBB。
        border (str): 描边色，#AARRGGBB。
    """

    fg: str
    bg: str
    border: str


@dataclass(frozen=True)
class LabelBase:
    """标签基色，同 GitHub 标签内联的 --label-* 变量。

    Attributes:
        r (int): 红，0–255。
        g (int): 绿，0–255。
        b (int): 蓝，0–255。
        h (int): 色相，0–360。
        s (int): 饱和度，0–100。
        l (int): 明度，0–100。
    """

    r: int
    g: int
    b: int
    h: int
    s: int
    l: int

    @staticmethod
    def from_hex(value: str) -> "LabelBase":
        """由十六进制基色构造，色相/饱和度/明度取整同 GitHub 内联变量。

        Args:
            value (str): 十六进制颜色，形如 ``#2da44e``。

        Returns:
            LabelBase: 标签基色。
        """
        r = int(value[1:3], 16)
        g = int(value[3:5], 16)
        b = int(value[5:7], 16)
        h, s, l = LabelBase._to_hsl(r, g, b)
        return LabelBase(r=r, g=g, b=b, h=h, s=s, l=l)

    @staticmethod
    def _to_hsl(r: int, g: int, b: int) -> tuple[int, int, int]:
        """折算 RGB 到 CSS 的 HSL 整数值。

        Args:
            r (int): 红，0–255。
            g (int): 绿，0–255。
            b (int): 蓝，0–255。

        Returns:
            tuple[int, int, int]: 色相 0–360、饱和度 0–100、明度 0–100。
        """
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        return round(h * 360) % 360, round(s * 100), round(l * 100)

    @staticmethod
    def _hsl_to_hex(h: int, s: float, l: float, alpha: float = 1.0) -> str:
        """把 HSL 折算成 QML 取色字符串。

        Args:
            h (int): 色相，0–360。
            s (float): 饱和度，0–100。
            l (float): 明度，0–100。
            alpha (float): 不透明度，0–1。

        Returns:
            str: 字色为 #RRGGBB；带透明度时为 #AARRGGBB。
        """
        rr, gg, bb = colorsys.hls_to_rgb((h % 360) / 360, min(max(l, 0), 100) / 100, min(max(s, 0), 100) / 100)
        r, g, b = round(rr * 255), round(gg * 255), round(bb * 255)
        if alpha >= 1:
            return f"#{r:02x}{g:02x}{b:02x}"
        return f"#{int(alpha * 255 + 0.5):02x}{r:02x}{g:02x}{b:02x}"

    def render_dark(self) -> Tint:
        """按 GitHub 标签公式渲染深色一套配色。

        Returns:
            Tint: 字色、底色与描边色。
        """
        perceived = (self.r * 0.2126 + self.g * 0.7152 + self.b * 0.0722) / 255
        # lightness-switch 等价于感知亮度越过 0.6 时补光归零
        switch = 1.0 if perceived <= 0.6 else 0.0
        lighten = (0.6 - perceived) * 100 * switch
        fg = LabelBase._hsl_to_hex(self.h, self.s, self.l + lighten)
        bg = f"#{int(0.18 * 255 + 0.5):02x}{self.r:02x}{self.g:02x}{self.b:02x}"
        border = LabelBase._hsl_to_hex(self.h, self.s, self.l + lighten, 0.3)
        return Tint(fg=fg, bg=bg, border=border)


class HealthColors:
    """健康档标签配色：好 / 警 / 坏，外加无健康语义的中性档。

    浅色一套（LIGHT）为手选的 Primer subtle 形制；深色一套由基色按 GitHub 公式折算。

    Attributes:
        GOOD (LabelBase): 好（存活率 ≥90%、已存活），档位取值 good；深色基色 Primer green.3。
        WARN (LabelBase): 警（存活率 ≥60%、待验证），档位取值 warn；深色基色 Primer yellow.3。
        BAD (LabelBase): 坏（存活率 <60%、已丢失），档位取值 bad；深色基色 Primer red.3。
        NEUTRAL (LabelBase): 中性（无健康语义标签），深色基色 GitHub 标签默认 #999。
        LIGHT (ClassVar[dict[str, Tint]]): 浅色配色表，同族 0 档淡色底 + 5 档较深字色；警档取 severe 橙，避免黄系字色偏棕。
    """

    GOOD: LabelBase = LabelBase.from_hex("#4ac26b")
    WARN: LabelBase = LabelBase.from_hex("#d4a72c")
    BAD: LabelBase = LabelBase.from_hex("#ff8182")
    NEUTRAL: LabelBase = LabelBase.from_hex("#999999")

    TONES: ClassVar[dict[str, LabelBase]] = {
        "good": GOOD,
        "warn": WARN,
        "bad": BAD,
        "neutral": NEUTRAL,
    }

    LIGHT: ClassVar[dict[str, Tint]] = {
        "good": Tint(fg="#1a7f37", bg="#dafbe1", border="#331a7f37"),
        "warn": Tint(fg="#bc4c00", bg="#fff1e5", border="#33bc4c00"),
        "bad": Tint(fg="#cf222e", bg="#ffebe9", border="#33cf222e"),
        "neutral": Tint(fg="#59636e", bg="#e6eaef", border="#3359636e"),
    }

    @staticmethod
    def to_qml() -> dict[str, dict[str, dict[str, str]]]:
        """转成 QML 取色表：档位 → 明暗 → {fg, bg, border}。

        Returns:
            dict: 档位到深浅两套渲染结果的映射。
        """
        return {
            tone: {"light": asdict(HealthColors.LIGHT[tone]), "dark": asdict(base.render_dark())}
            for tone, base in HealthColors.TONES.items()
        }
