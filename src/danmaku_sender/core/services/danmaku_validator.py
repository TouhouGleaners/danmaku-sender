from typing import TypedDict

from ..models.danmaku import Danmaku
from ..state import ValidationConfig


FORBIDDEN_SYMBOLS = "☢⚠☣☠⚡💣⚔🔥"


class ValidationIssue(TypedDict):
    original_index: int
    danmaku: Danmaku
    reason: str


def validate_danmaku_list(
        danmaku_list: list[Danmaku],
        video_duration_ms: int = -1,
        validation_config: ValidationConfig | None = None
    ) -> list[ValidationIssue]:
    """
    校验弹幕列表，找出不符合B站发送规则的弹幕。
    Args:
        danmaku_list (list): 待校验的弹幕对象列表。
        video_duration_ms (int): 视频总时长（毫秒）。
    Returns:
        list: 一个包含问题弹幕信息的字典列表。
    """
    # 提取用户规则
    custom_enabled = validation_config.enabled if validation_config else False
    keywords = validation_config.blocked_keywords if validation_config else []

    problems: list[ValidationIssue] = []
    for i, dm in enumerate(danmaku_list):
        msg = dm.msg
        progress = dm.progress

        reasons = []

        # 换行符检查
        if '\\n' in msg or '/n' in msg:
            reasons.append('内容包含换行符')

        # 长度检查
        if len(msg) > 100:
            reasons.append('内容超过100个字符')

        # 时间戳检查
        if video_duration_ms > 0 and progress > video_duration_ms:
            reasons.append('时间戳超出视频总时长')

        # 特殊符号检查
        found_forbidden = [char for char in FORBIDDEN_SYMBOLS if char in msg]
        if found_forbidden:
            # 只报告第一个禁用符号，避免信息过长
            reasons.append(f"包含禁用符号'{found_forbidden[0]}'")

        # 自定义关键词检查
        if custom_enabled and keywords:
            msg_lower = msg.lower()

            found_ks = [k for k in keywords if k and k in msg_lower]
            
            if found_ks:
                # 格式化输出：命中自定义过滤词: '词A', '词B'
                ks = ", ".join(f"'{k}'" for k in found_ks)
                reasons.append(f"命中自定义过滤词: {ks}")

        # 问题汇总
        if reasons:
            dm.is_valid = False
            problems.append({
                'original_index': i,
                'danmaku': dm,
                'reason': ", ".join(reasons)
            })
        else:
            dm.is_valid = True

    return problems