"""SvgIcon 注册表与图标文件的一致性。"""

import pytest

from danmaku_sender.ui.framework.icons import ICONS_DIR, SvgIcon


def _registered() -> list[tuple[str, str]]:
    """取出注册名与文件名的配对（描述符在类字典里，属性访问返回的是渲染后的图标）。"""
    return [
        (name, SvgIcon.__dict__[name].filename)
        for name in sorted(SvgIcon.__dict__)
        if isinstance(SvgIcon.__dict__[name], object) and hasattr(SvgIcon.__dict__[name], "filename")
    ]


class TestIconRegistry:
    @pytest.mark.parametrize("name,filename", _registered(), ids=lambda v: str(v))
    def test_registered_file_exists(self, name: str, filename: str):
        """注册的每个图标都必须有对应的文件"""
        assert (ICONS_DIR / filename).is_file(), f"{name} 指向的 {filename} 不存在"

    def test_every_file_is_registered(self):
        """图标文件不注册就等于死资源，注册表与目录须一一对应"""
        registered = {filename for _, filename in _registered()}
        on_disk = {p.name for p in ICONS_DIR.glob("*.svg")}
        assert registered == on_disk, f"未注册: {on_disk - registered}；缺失: {registered - on_disk}"
