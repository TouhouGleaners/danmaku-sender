def format_duration(seconds: float | int | None) -> str:
    """将秒数格式化为 HH:MM:SS / MM:SS 字符串"""
    if seconds is None or seconds < 0:
        return "-:--:--"

    total_minutes, secs = divmod(int(seconds), 60)
    hours, mins = divmod(total_minutes, 60)

    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    else:
        return f"{mins:02d}:{secs:02d}"