"""Danmaku 模型单元测试"""
from danmaku_sender.core.models.danmaku import Danmaku


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

    def test_default_dmid_empty(self):
        dm = Danmaku(msg="test", progress=1000)
        assert dm.dmid == ""

    def test_default_is_valid_true(self):
        dm = Danmaku(msg="test", progress=1000)
        assert dm.is_valid is True


class TestDanmakuProperties:
    """progress_sec / is_sent 属性"""

    def test_progress_sec_conversion(self):
        dm = Danmaku(msg="test", progress=5000)
        assert dm.progress_sec == 5.0

    def test_progress_sec_zero(self):
        dm = Danmaku(msg="test", progress=0)
        assert dm.progress_sec == 0.0

    def test_is_sent_false_when_no_dmid(self):
        dm = Danmaku(msg="test", progress=1000, dmid="")
        assert dm.is_sent is False

    def test_is_sent_true_when_has_dmid(self):
        dm = Danmaku(msg="test", progress=1000, dmid="12345")
        assert dm.is_sent is True


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


class TestDanmakuClone:
    """clone 深拷贝"""

    def test_clone_produces_equal_object(self):
        dm = Danmaku(msg="original", progress=1000, color=255)
        cloned = dm.clone()
        assert cloned == dm
        assert cloned is not dm

    def test_clone_is_independent(self):
        dm = Danmaku(msg="original", progress=1000)
        cloned = dm.clone()
        cloned.msg = "modified"
        assert dm.msg == "original"

    def test_clone_preserves_mode(self):
        dm = Danmaku(msg="test", progress=1000, mode=Danmaku.Mode.TOP)
        cloned = dm.clone()
        assert cloned.mode == Danmaku.Mode.TOP


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
        assert dm.dmid == ""  # is_online=False

    def test_online_danmaku_with_dmid(self):
        p_attr = ["10.0", "1", "25", "16777215", "1234567890", "0", "0", "dmid123"]
        dm = Danmaku.from_xml(p_attr, "在线弹幕", is_online=True)
        assert dm.dmid == "dmid123"

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
