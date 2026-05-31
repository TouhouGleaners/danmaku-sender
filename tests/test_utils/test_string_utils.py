"""string_utils 单元测试 — parse_bilibili_link"""
from danmaku_sender.utils.string_utils import parse_bilibili_link


class TestParseBilibiliLink:
    """parse_bilibili_link 的各种输入场景"""

    # === 正常 URL ===

    def test_full_url_with_p_index(self):
        bvid, p = parse_bilibili_link("https://www.bilibili.com/video/BV1xx411c7mD?p=3")
        assert bvid == "BV1xx411c7mD"
        assert p == 2  # 0-based

    def test_full_url_without_p_index(self):
        bvid, p = parse_bilibili_link("https://www.bilibili.com/video/BV1xx411c7mD")
        assert bvid == "BV1xx411c7mD"
        assert p is None

    def test_short_url(self):
        bvid, p = parse_bilibili_link("https://b23.tv/BV1xx411c7mD")
        assert bvid == "BV1xx411c7mD"
        assert p is None

    def test_url_with_ampersand_p(self):
        bvid, p = parse_bilibili_link("https://www.bilibili.com/video/BV1xx411c7mD?vd_source=abc&p=5")
        assert bvid == "BV1xx411c7mD"
        assert p == 4

    def test_url_with_p_equals_1(self):
        """p=1 应解析为 0-based 索引 0"""
        _, p = parse_bilibili_link("https://www.bilibili.com/video/BV1xx411c7mD?p=1")
        assert p == 0

    # === 纯 BVID ===

    def test_plain_bvid(self):
        bvid, p = parse_bilibili_link("BV1xx411c7mD")
        assert bvid == "BV1xx411c7mD"
        assert p is None

    def test_bvid_in_text(self):
        bvid, p = parse_bilibili_link("请看这个视频 BV1xx411c7mD 很有趣")
        assert bvid == "BV1xx411c7mD"
        assert p is None

    # === 边界/异常输入 ===

    def test_empty_string(self):
        bvid, p = parse_bilibili_link("")
        assert bvid is None
        assert p is None

    def test_none_input(self):
        bvid, p = parse_bilibili_link(None)
        assert bvid is None
        assert p is None

    def test_no_bvid_no_p(self):
        bvid, p = parse_bilibili_link("这是一段普通文本")
        assert bvid is None
        assert p is None

    def test_invalid_p_index_zero(self):
        """p=0 不应被解析（正则要求 >0）"""
        _, p = parse_bilibili_link("https://www.bilibili.com/video/BV1xx411c7mD?p=0")
        assert p is None

    def test_multiple_bvids_returns_first(self):
        bvid, _ = parse_bilibili_link("BV1xx411c7mD 和 BV2yy422d8nE")
        assert bvid == "BV1xx411c7mD"
