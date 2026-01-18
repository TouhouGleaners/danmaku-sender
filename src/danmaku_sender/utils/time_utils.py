def format_ms_to_hhmmss(ms: int) -> str:
    """将毫秒格式化为 HH:MM:SS / MM:SS 字符串。"""
    if not isinstance(ms, (int, float)) or ms < 0:
        return "-:--:--"
    
    total_seconds = int(ms // 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"