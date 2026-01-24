import re


BV_PATTERN = re.compile(r"(BV[a-zA-Z0-9]{10})")  # 匹配 BV 号 (BV + 10位字母数字)
P_PATTERN = re.compile(r"[?&]p=(\d+)")  # 匹配分P参数


def parse_bilibili_link(text: str) -> tuple[str | None, int | None]:
    """
    从文本中提取 BVID 和 分P索引 (p=X)。
    如果文本本身就是一个纯 BVID，也可正常提取。
    
    Returns:
        (bvid, p_index)
        - bvid: BV号字符串 (如 BV1xx...) 或 None
        - p_index: 分P索引 (0-based) 或 None
    """
    if not text:
        return None, None

    # 提取 BVID
    bv_match = BV_PATTERN.search(text)
    bvid = bv_match.group(0) if bv_match else None

    # 提取分P参数
    p_index = None
    p_match = P_PATTERN.search(text)

    if p_match:
        try:
            p_num = int(p_match.group(1))
            if p_num > 0:
                p_index = p_num - 1
        except ValueError:
            pass

    return bvid, p_index