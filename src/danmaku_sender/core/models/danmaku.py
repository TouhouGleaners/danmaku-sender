import time
from dataclasses import dataclass, replace
from typing import Any


@dataclass
class Danmaku:
    """弹幕实体对象"""
    # === 发送参数 (Request) ===
    msg: str                # 内容 (API: msg, XML: text)
    progress: int           # 时间毫秒 (API: progress, XML: p[0])
    mode: int = 1           # 模式 (API: mode)
    fontsize: int = 25      # 字号 (API: fontsize)
    color: int = 16777215   # 颜色 (API: color)

    # === 响应/状态数据 (Response) ===
    # 本地未发送时为空，发送成功后由 Sender 回填 API 返回的 dmid_str
    # 在线获取时直接解析 p_attr[7]
    dmid: str = ""

    # 校验标记 (本地逻辑使用)
    is_valid: bool = True

    @property
    def progress_sec(self) -> float:
        return self.progress / 1000.0
    
    @property
    def is_sent(self) -> bool:
        """判断是否已获得正式身份"""
        return bool(self.dmid)
    
    def to_api_params(self) -> dict[str, Any]:
        """转为 API 参数字典"""
        return {
            'type': 1,
            'msg': self.msg,
            'progress': self.progress,
            'mode': self.mode,
            'fontsize': self.fontsize,
            'color': self.color,
            'pool': 0,
            'rnd': int(time.time() * 1000000)
        }
    
    def clone(self) -> 'Danmaku':
        return replace(self)
    
    @classmethod
    def from_xml(cls, p_attr: list[str], text: str, is_online: bool = False) -> 'Danmaku':
        """工厂方法：解析 XML"""
        progress = int(float(p_attr[0]) * 1000)
        mode = int(p_attr[1]) if len(p_attr) > 1 else 1
        fontsize = int(p_attr[2]) if len(p_attr) > 2 else 25
        color = int(p_attr[3]) if len(p_attr) > 3 else 16777215

        dmid = ""
        if is_online and len(p_attr) > 7:
            dmid = p_attr[7]

        return cls(
            msg=text.strip(),
            progress=progress,
            mode=mode,
            fontsize=fontsize,
            color=color,
            dmid=dmid
        )