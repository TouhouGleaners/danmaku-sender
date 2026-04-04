class BiliNetworkError(Exception):
    """
    物理层网络错误

    超时、断网、DNS解析失败、HTTP 500等
    """
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"网络请求失败: {message}")


class BiliApiError(Exception):
    """
    业务层 API 错误

    HTTP 返回 200，但 B 站返回了 code != 0
    """
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Bili API Error [Code: {code}]: {message}")