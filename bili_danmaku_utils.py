from enum import Enum


class BiliDmErrorCode(Enum):
    """Bilibili弹幕发送错误码及其默认描述"""
    # 成功
    SUCCESS = (0, "弹幕发送成功。")
    # B站API返回的错误码
    UNAUTHORIZED = (-101, "账号未登录或登录态失效！请检查SESSDATA和bili_jct。")
    ACCOUNT_BANNED = (-102, "账号被封停。")
    CSRF_FAILED = (-111, "CSRF 校验失败 (bili_jct 可能失效)，请检查登录凭证或尝试重新获取。")
    REQUEST_ERROR = (-400, "请求错误，参数不合法。")
    NOT_FOUND = (-404, "请求资源不存在。")
    
    SYSTEM_UPGRADING = (36700, "系统升级中，暂无法发送弹幕。")
    CONTENT_FORBIDDEN = (36701, "弹幕包含被禁止的内容，请修改后重试。")
    DANMAKU_TOO_LONG = (36702, "弹幕长度大于100字，请精简。")
    FREQ_LIMIT = (36703, "发送频率过快，请降低发送速度或稍后再试。")
    VIDEO_NOT_REVIEWED = (36704, "禁止向未审核的视频发送弹幕。")
    LEVEL_INSUFFICIENT_GENERAL = (36705, "您的等级不足，不能发送弹幕。")
    LEVEL_INSUFFICIENT_TOP = (36706, "您的等级不足，不能发送顶端弹幕。")
    LEVEL_INSUFFICIENT_BOTTOM = (36707, "您的等级不足，不能发送底端弹幕。")
    LEVEL_INSUFFICIENT_COLOR = (36708, "您的等级不足，不能发送彩色弹幕。")
    LEVEL_INSUFFICIENT_ADVANCED = (36709, "您的等级不足，不能发送高级弹幕。")
    PERMISSION_INSUFFICIENT_STYLE = (36710, "您的权限不足，不能发送这种样式的弹幕。")
    VIDEO_DANMAKU_FORBIDDEN = (36711, "该视频禁止发送弹幕，无法发送。")
    LENGTH_LIMIT_LEVEL1 = (36712, "Level 1用户发送弹幕的最大长度为20字。")
    VIDEO_NOT_PAID = (36713, "此稿件未付费，暂时无法发送弹幕。")
    INVALID_PROGRESS = (36714, "弹幕发送时间（progress）不合法。")
    DAILY_LIMIT_EXCEEDED = (36715, "当日操作数量超过上限。")
    NOT_PREMIUM_MEMBER = (36718, "目前您不是大会员，无法使用会员权益。")
    # 自定义错误码
    NETWORK_ERROR = (-9999, "发送弹幕时发生网络或请求异常。请检查您的网络连接。")
    UNKNOWN_ERROR = (-9998, "发送弹幕时发生未知异常，请联系开发者或稍后再试。")
    GENERIC_FAILURE = (-1, "操作失败，详见原始消息或尝试稍后再试。")  # 当B站返回code是-1或未识别的code时使用

    def __init__(self, code: int, description: str):
        self._code = code
        self._description = description

    @property
    def value(self):
        """返回错误码的数值"""
        return self._code

    @property
    def description(self):
        """返回错误码的描述"""
        return self._description
    
    @classmethod
    def from_code(cls, code: int):
        """通过数字错误码反向查找对应的枚举成员"""
        for member in cls:
            if member.value == code:
                return member
        return None # 如果没找到对应的枚举值，返回None
    

class DanmakuSendResult:
    """封装弹幕发送结果"""
    def __init__(self, code: int, success: bool, message: str, display_message: str = ""):
        self.code = code
        self.success = success
        self.raw_message = message if message else "无原始错误信息"  # B站返回的原始信息
        self.display_message = display_message if display_message else self.raw_message  # 用于显示给用户的信息

    def __str__(self):
        status = "成功" if self.success else "失败"
        if self.code == BiliDmErrorCode.SUCCESS.value:
            return f"[发送结果: {status}] {self.display_message}"
        else:
            return f"[发送结果: {status}] Code: {self.code}, 消息: \"{self.display_message}\" (原始: \"{self.raw_message}\")"
