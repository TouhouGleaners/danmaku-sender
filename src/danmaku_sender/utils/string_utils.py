import re


BV_PATTERN = re.compile(r"(BV[a-zA-Z0-9]{10})")  # 匹配 BV 号 (BV + 10位字母数字)
P_PATTERN = re.compile(r"[?&]p=(\d+)")  # 匹配分P参数


def parse_bilibili_link(text: str) -> tuple[str | None, int | None]:
    """
    从文本中提取 BVID 和分P序号（B 站 URL 的 p 参数）。
    如果文本本身就是一个纯 BVID，也可正常提取。

    Returns:
        (bvid, page)
        - bvid: BV号字符串 (如 BV1xx...) 或 None
        - page: 分P序号，1-based（与 B 站 ?p=、VideoPart.page 一致）；无分P时为 None
    """
    if not text:
        return None, None

    bv_match = BV_PATTERN.search(text)
    bvid = bv_match.group(0) if bv_match else None

    page = None
    p_match = P_PATTERN.search(text)
    if p_match:
        try:
            p_num = int(p_match.group(1))
            if p_num > 0:
                page = p_num
        except ValueError:
            pass

    return bvid, page
