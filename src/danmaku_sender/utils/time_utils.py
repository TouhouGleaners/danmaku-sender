def format_seconds_to_duration(seconds: float) -> str:
    """将秒数格式化为 HH:MM:SS / MM:SS 字符串"""
    if seconds is None or seconds < 0:
        return "-:--:--"

    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

def format_ms_to_hhmmss(ms: int) -> str:
    """专门用于视频进度（毫秒）"""
    return format_seconds_to_duration(ms / 1000.0)