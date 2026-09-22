"""Danmaku 模型单元测试 — 不可变发送载荷"""
import dataclasses

import pytest

from danmaku_sender.types.models.danmaku import Danmaku


class TestDanmakuDefaults:
    """默认值与基本属性"""

    def test_default_mode_is_scroll(self):
        dm = Danmaku(msg="test", progress=1000)
        assert dm.mode == Danmaku.Mode.SCROLL

    def test_default_fontsize(self):
        dm = Danmaku(msg="test", progress=1000)
        assert dm.fontsize == 25

    def test_default_color_white(self):
        dm = Danmaku(msg="test", progress=1000)
        assert dm.color == 16777215  # 0xFFFFFF


class TestDanmakuFrozen:
    """不可变约束：载荷发出去就不能被改"""

    def test_msg_assignment_raises(self):
        dm = Danmaku(msg="test", progress=1000)
        with pytest.raises(dataclasses.FrozenInstanceError):
            dm.msg = "x"  # type: ignore[misc]

    def test_progress_assignment_raises(self):
        dm = Danmaku(msg="test", progress=1000)
        with pytest.raises(dataclasses.FrozenInstanceError):
            dm.progress = 0  # type: ignore[misc]

    def test_has_no_dmid_or_is_valid(self):
        dm = Danmaku(msg="test", progress=1000)
        assert not hasattr(dm, "dmid")
        assert not hasattr(dm, "is_valid")


class TestDanmakuReplace:
    """replace 换值语义"""

    def test_replace_returns_new_object(self):
        dm = Danmaku(msg="original", progress=1000, color=255)
        new = dm.replace(msg="modified")
        assert new is not dm
        assert new.msg == "modified"
        assert dm.msg == "original"

    def test_replace_keeps_other_fields(self):
        dm = Danmaku(msg="test", progress=1000, mode=Danmaku.Mode.TOP)
        new = dm.replace(msg="x")
        assert new.mode == Danmaku.Mode.TOP
        assert new.progress == 1000


class TestDanmakuProperties:
    """progress_sec"""

    def test_progress_sec_conversion(self):
        dm = Danmaku(msg="test", progress=5000)
        assert dm.progress_sec == 5.0

    def test_progress_sec_zero(self):
        dm = Danmaku(msg="test", progress=0)
        assert dm.progress_sec == 0.0


class TestDanmakuMode:
    """Mode 枚举"""

    def test_scroll_value(self):
        assert Danmaku.Mode.SCROLL == 1

    def test_bottom_value(self):
        assert Danmaku.Mode.BOTTOM == 4

    def test_top_value(self):
        assert Danmaku.Mode.TOP == 5


class TestDanmakuToApiParams:
    """to_api_params 转换"""

    def test_basic_params(self):
        dm = Danmaku(msg="hello", progress=3000, mode=Danmaku.Mode.SCROLL, fontsize=25, color=16777215)
        params = dm.to_api_params()
        assert params['type'] == 1
        assert params['msg'] == "hello"
        assert params['progress'] == 3000
        assert params['mode'] == 1
        assert params['fontsize'] == 25
        assert params['color'] == 16777215
        assert params['pool'] == 0

    def test_params_has_rnd(self):
        dm = Danmaku(msg="test", progress=1000)
        params = dm.to_api_params()
        assert 'rnd' in params
        assert isinstance(params['rnd'], int)

    def test_bottom_mode_params(self):
        dm = Danmaku(msg="底部弹幕", progress=2000, mode=Danmaku.Mode.BOTTOM)
        params = dm.to_api_params()
        assert params['mode'] == 4


class TestDanmakuFromXml:
    """from_xml 工厂方法"""

    def test_basic_scroll_danmaku(self):
        p_attr = ["12.5", "1", "25", "16777215", "1234567890", "0", "0", "abcdef"]
        dm = Danmaku.from_xml(p_attr, "Hello World")
        assert dm.msg == "Hello World"
        assert dm.progress == 12500
        assert dm.mode == Danmaku.Mode.SCROLL
        assert dm.fontsize == 25
        assert dm.color == 16777215

    def test_bottom_mode(self):
        p_attr = ["5.0", "4"]
        dm = Danmaku.from_xml(p_attr, "底部")
        assert dm.mode == Danmaku.Mode.BOTTOM

    def test_top_mode(self):
        p_attr = ["5.0", "5"]
        dm = Danmaku.from_xml(p_attr, "顶部")
        assert dm.mode == Danmaku.Mode.TOP

    def test_unknown_mode_fallback_to_scroll(self):
        p_attr = ["5.0", "99"]
        dm = Danmaku.from_xml(p_attr, "未知模式")
        assert dm.mode == Danmaku.Mode.SCROLL

    def test_minimal_p_attr(self):
        """只有 progress 和 mode，fontsize/color 使用默认值"""
        p_attr = ["1.0", "1"]
        dm = Danmaku.from_xml(p_attr, "最少参数")
        assert dm.fontsize == 25
        assert dm.color == 16777215

    def test_text_is_stripped(self):
        p_attr = ["1.0", "1"]
        dm = Danmaku.from_xml(p_attr, "  有空格  ")
        assert dm.msg == "有空格"

    def test_fractional_seconds(self):
        p_attr = ["0.5", "1"]
        dm = Danmaku.from_xml(p_attr, "半秒")
        assert dm.progress == 500

    def test_custom_fontsize_and_color(self):
        p_attr = ["1.0", "1", "36", "255"]
        dm = Danmaku.from_xml(p_attr, "大字红")
        assert dm.fontsize == 36
        assert dm.color == 255


class TestDmidFromXml:
    """dmid_from_xml：身份与载荷分离"""

    def test_extracts_dmid(self):
        p_attr = ["10.0", "1", "25", "16777215", "1234567890", "0", "0", "dmid123"]
        assert Danmaku.dmid_from_xml(p_attr) == "dmid123"

    def test_empty_when_missing(self):
        assert Danmaku.dmid_from_xml(["1.0", "1"]) == ""
