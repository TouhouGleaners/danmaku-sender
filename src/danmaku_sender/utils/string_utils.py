import re


def parse_bilibili_link(text: str) -> tuple[str | None, int | None]:
    """
    从文本中提取 BVID 和 分P索引 (p=X)。
    
    Returns:
        (bvid, p_index)
        - bvid: BV号字符串 (如 BV1xx...) 或 None
        - p_index: 分P索引 (0-based) 或 None
    """
    if not text:
        return None, None

    # 提取 BVID (BV + 10位字母数字)
    bv_pattern = re.compile(r"(BV[a-zA-Z0-9]{10})", re.IGNORECASE)
    bv_match = bv_pattern.search(text)

    bvid = bv_match.group(1) if bv_match else None

    # 提取分P参数 (?p=3 或 &p=3)
    p_index = None
    p_pattern = re.compile(r"[?&]p=(\d+)")
    p_match = p_pattern.search(text)

    if p_match:
        try:
            p_num = int(p_match.group(1))
            if p_num > 0:
                p_index = p_num - 1
        except ValueError:
            pass

    return bvid, p_index