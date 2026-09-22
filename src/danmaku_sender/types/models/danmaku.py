import time
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Any, Self


@dataclass(frozen=True)
class Danmaku:
    """弹幕发送载荷（纯数据，不可变）。

    只描述「发什么」。身份/回执不在此：
    - 服务器回执 dmid → `DanmakuSendResult` / `HistoryManager.record_danmaku`
    - 校验结论 → `EditorItem.error_msg`
    改字段请用 `replace()` 生成新对象。
    """
    class Mode(IntEnum):
        SCROLL = 1
        BOTTOM = 4
        TOP = 5


    class Standards:
        """Bilibili 通用标准"""
        FONT_SIZES = {
            "标准 (25)": 25,
            "小 (18)": 18,
            "大 (36)": 36
        }

        COLORS = [
            "#FE0302", "#FF7204", "#FFAA02", "#FFD302", "#FFFF00", "#A0EE00", "#00CD00",
            "#019899", "#4266BE", "#89D5FF", "#CC0273", "#222222", "#9B9B9B", "#FFFFFF"
        ]


    msg: str                  # 内容 (API: msg, XML: text)
    progress: int             # 时间毫秒 (API: progress, XML: p[0])
    mode: Mode = Mode.SCROLL  # 模式 (API: mode)
    fontsize: int = 25        # 字号 (API: fontsize)
    color: int = 16777215     # 颜色 (API: color)

    @property
    def progress_sec(self) -> float:
        return self.progress / 1000.0

    def replace(self, **changes: Any) -> Self:
        """生成改过字段的新对象（换值，不是原地改）"""
        return replace(self, **changes)

    def to_api_params(self) -> dict[str, Any]:
        """转为 API 参数字典"""
        return {
            'type': 1,
            'msg': self.msg,
            'progress': self.progress,
            'mode': self.mode.value,
            'fontsize': self.fontsize,
            'color': self.color,
            'pool': 0,
            'rnd': int(time.time() * 1000000)
        }

    @classmethod
    def from_xml(cls, p_attr: list[str], text: str) -> Self:
        """工厂方法：解析 XML 的发送载荷部分"""
        progress = int(float(p_attr[0]) * 1000)

        try:
            mode = cls.Mode(int(p_attr[1]))
        except ValueError:
            mode = cls.Mode.SCROLL

        fontsize = int(p_attr[2]) if len(p_attr) > 2 else 25
        color = int(p_attr[3]) if len(p_attr) > 3 else 16777215

        return cls(
            msg=text.strip(),
            progress=progress,
            mode=mode,
            fontsize=fontsize,
            color=color,
        )

    @staticmethod
    def dmid_from_xml(p_attr: list[str]) -> str:
        """从 XML p 属性提取服务器 dmid（仅在线数据带）"""
        return p_attr[7] if len(p_attr) > 7 else ""
