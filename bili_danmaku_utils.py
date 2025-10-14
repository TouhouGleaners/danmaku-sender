from enum import Enum


class BiliDmErrorCode(Enum):
    """
    Bilibili弹幕发送错误码及其默认描述
    定义格式: (code, description, is_fatal)
    """
    # 成功
    SUCCESS = (0, "弹幕发送成功。", False)
    # B站API返回的错误码
    UNAUTHORIZED = (-101, "账号未登录或登录态失效！请检查SESSDATA和bili_jct。", True)
    ACCOUNT_BANNED = (-102, "账号被封停。", True)
    CSRF_FAILED = (-111, "CSRF 校验失败 (bili_jct 可能失效)，请检查登录凭证或尝试重新获取。", True)
    REQUEST_ERROR = (-400, "请求错误，参数不合法。", False)
    NOT_FOUND = (-404, "请求资源不存在。", True)
    
    SYSTEM_UPGRADING = (36700, "系统升级中，暂无法发送弹幕。", True)
    CONTENT_FORBIDDEN = (36701, "弹幕包含被禁止的内容，请修改后重试。", False)
    DANMAKU_TOO_LONG = (36702, "弹幕长度大于100字，请精简。", False)
    FREQ_LIMIT = (36703, "发送频率过快，请降低发送速度或稍后再试。", False)
    VIDEO_NOT_REVIEWED = (36704, "禁止向未审核的视频发送弹幕。", True)
    LEVEL_INSUFFICIENT_GENERAL = (36705, "您的等级不足，不能发送弹幕。", True)
    LEVEL_INSUFFICIENT_TOP = (36706, "您的等级不足，不能发送顶端弹幕。", False)
    LEVEL_INSUFFICIENT_BOTTOM = (36707, "您的等级不足，不能发送底端弹幕。", False)
    LEVEL_INSUFFICIENT_COLOR = (36708, "您的等级不足，不能发送彩色弹幕。", False)
    LEVEL_INSUFFICIENT_ADVANCED = (36709, "您的等级不足，不能发送高级弹幕。", False)
    PERMISSION_INSUFFICIENT_STYLE = (36710, "您的权限不足，不能发送这种样式的弹幕。", False)
    VIDEO_DANMAKU_FORBIDDEN = (36711, "该视频禁止发送弹幕，无法发送。", True)
    LENGTH_LIMIT_LEVEL1 = (36712, "Level 1用户发送弹幕的最大长度为20字。", False)
    VIDEO_NOT_PAID = (36713, "此稿件未付费，暂时无法发送弹幕。", True)
    INVALID_PROGRESS = (36714, "弹幕发送时间（progress）不合法。", False)
    DAILY_LIMIT_EXCEEDED = (36715, "当日操作数量超过上限。", False)
    NOT_PREMIUM_MEMBER = (36718, "目前您不是大会员，无法使用会员权益。", False)
    # 自定义错误码
    NETWORK_ERROR = (-9999, "发送弹幕时发生网络或请求异常。请检查您的网络连接。", True)
    UNKNOWN_ERROR = (-9998, "发送弹幕时发生未知异常，请联系开发者或稍后再试。", True)
    GENERIC_FAILURE = (-1, "操作失败，详见原始消息或尝试稍后再试。", False)  # 当B站返回code是-1或未识别的code时使用

    def __init__(self, code: int, description: str, is_fatal: bool):
        self._code = code
        self._description = description
        self._is_fatal = is_fatal

    @property
    def value(self):
        """返回错误码的数值"""
        return self._code

    @property
    def description(self):
        """返回错误码的描述"""
        return self._description
    
    @property
    def is_fatal(self):
        """该错误是否是致命的（应中断任务）"""
        return self._is_fatal
    
    @classmethod
    def from_code(cls, code: int):
        """通过数字错误码反向查找对应的枚举成员"""
        for member in cls:
            if member.value == code:
                return member
        return None # 如果没找到对应的枚举值，返回None
    
    @staticmethod
    def resolve_bili_error(code: int, raw_message: str) -> tuple[int, str]:
        """根据B站返回的code和原始信息，解析出最终的code和用于显示的友好消息"""
        # 尝试从枚举中获取友好提示
        enum_member = BiliDmErrorCode.from_code(code)
        display_msg = enum_member.description if enum_member else raw_message

        # 如果 B站原始消息为空且 code 不是成功，并且枚举也未提供描述，则使用通用提示
        if not display_msg and code != BiliDmErrorCode.SUCCESS.value:
            display_msg = BiliDmErrorCode.UNKNOWN_ERROR.description
            
        return code, display_msg
        

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
