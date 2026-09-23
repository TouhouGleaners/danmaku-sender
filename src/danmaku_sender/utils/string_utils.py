"""纯字符串工具：零副作用，任意层可依赖。"""

import re


BV_PATTERN = re.compile(r"(BV[a-zA-Z0-9]{10})")  # BV + 10 位字母数字
P_PATTERN = re.compile(r"[?&]p=(\d+)")  # B 站 URL 分P参数


def parse_bilibili_link(text: str) -> tuple[str | None, int | None]:
    """
    从文本中提取 BVID 和分P序号（B 站 URL 的 p 参数）。
    纯 BVID、夹在说明文字里的 BV 号均可提取。`text` 必须是 str（可为空）。

    Returns:
        (bvid, page)
        - bvid: BV号 (如 BV1xx...) 或 None
        - page: 分P序号，1-based（与 ?p=、VideoPart.page 一致）；无分P时为 None
    """
    if not text:
        return None, None

    bv_match = BV_PATTERN.search(text)
    bvid = bv_match.group(0) if bv_match else None

    page = None
    p_match = P_PATTERN.search(text)
    if p_match:
        p_num = int(p_match.group(1))
        if p_num > 0:
            page = p_num

    return bvid, page


def parse_keywords(text: str) -> list[str]:
    """将逗号分隔的关键词文本解析为列表。

    支持中英文逗号，忽略空白项，结果去重并排序。用于文本框与
    ``list[str]`` 配置字段之间的转换。

    Args:
        text: 原始输入文本，例如 ``"应用, 过滤"``。

    Returns:
        去重、排序后的关键词列表。
    """
    raw = text.replace("，", ",").lower()
    parts = [k.strip() for k in raw.split(",") if k.strip()]
    return sorted(set(parts))


def join_keywords(keywords: list[str]) -> str:
    """将关键词列表拼接为文本框展示文本。

    Args:
        keywords: 关键词列表。

    Returns:
        逗号分隔的字符串，例如 ``"应用, 过滤"``。
    """
    return ", ".join(keywords)
