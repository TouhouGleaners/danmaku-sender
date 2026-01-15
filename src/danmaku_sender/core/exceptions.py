class BiliApiException(Exception):
    """当B站API返回非零错误码或发生不可恢复的网络错误时抛出"""
    def __init__(self, code: int, message: str, is_network_error: bool = False):
        self.code = code
        self.message = message
        self.is_network_error = is_network_error
        super().__init__(f"Bili API Error [Code: {code}]: {message}")